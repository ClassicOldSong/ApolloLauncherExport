#!/usr/bin/env python3
import threading
import queue
import shutil
from pathlib import Path
from tkinter import messagebox

try:
    import requests
except ImportError:
    requests = None

try:
    from igdb.wrapper import IGDBWrapper
    if not requests:
        raise ImportError("IGDBWrapper also needs 'requests' library.")
except ImportError:
    IGDBWrapper = None

from utils import open_directory, download_image
from gui_components import show_progress_dialog
from api_clients import fetch_steamgriddb_assets_for_game, fetch_igdb_metadata_for_game

def _generate_pegasus_metadata_file(app_map, host_uuid, host_name, out_dir, igdb_metadata_cache):
    """Generates the metadata.pegasus.txt file."""
    metadata_content = []
    metadata_content.append(f"collection: {host_name}")
    metadata_content.append("shortname: artemis")
    metadata_content.append("extension: artp")
    launch_command = f"am start -n com.limelight.noir/com.limelight.ShortcutTrampoline --es UUID {host_uuid} --es AppUUID {{file.basename}}"
    metadata_content.append(f"launch: {launch_command}")
    metadata_content.append("")

    for name, game_data in app_map.items():
        uuid = game_data["uuid"]
        metadata_content.append(f"game: {name}")
        metadata_content.append(f"file: {uuid}.artp")

        # Check for and append IGDB metadata if available
        if uuid in igdb_metadata_cache:
            igdb_data = igdb_metadata_cache[uuid]
            pegasus_igdb_mapping = {
                # IGDB field name : Pegasus field name
                # 'game' is already handled by 'name' from app_map
                "summary": "summary",
                "description": "description",
                "developer": "developer",
                "publisher": "publisher",
                "genre": "genre",
                "rating": "rating",
                "release": "release",
                "tags": "tags" # Assuming 'tags' is a desired Pegasus field from IGDB game_modes/player_perspectives
            }
            for igdb_key, pegasus_key in pegasus_igdb_mapping.items():
                if igdb_data.get(igdb_key):
                    # Format multi-line text properly for Pegasus
                    text_value = str(igdb_data[igdb_key])
                    if "\n" in text_value or len(text_value) > 80: # Arbitrary length for multi-line consideration
                        lines = text_value.split('\n')
                        metadata_content.append(f"{pegasus_key}: {lines[0]}")
                        for line in lines[1:]:
                            metadata_content.append(f"  {line}") # Indent subsequent lines
                    else:
                        metadata_content.append(f"{pegasus_key}: {text_value}")

        metadata_content.append("")
    
    (out_dir / "metadata.pegasus.txt").write_text("\n".join(metadata_content).strip(), encoding="utf-8")
    print("Pegasus metadata file generated.")

def _parse_existing_metadata(out_dir):
    """Parse existing metadata.pegasus.txt file to retain previous metadata."""
    metadata_file = out_dir / "metadata.pegasus.txt"
    existing_metadata_cache = {}
    
    if not metadata_file.exists():
        return existing_metadata_cache
    
    try:
        content = metadata_file.read_text(encoding="utf-8")
        lines = content.split('\n')
        
        current_game = None
        current_file = None
        current_metadata = {}
        
        for line in lines:
            line = line.strip()
            if not line:
                # End of game section, store if we have both game and file
                if current_game and current_file and current_metadata:
                    # Extract UUID from file name (remove .artp extension)
                    uuid = current_file.replace('.artp', '')
                    existing_metadata_cache[uuid] = current_metadata.copy()
                current_game = None
                current_file = None
                current_metadata = {}
                continue
                
            if line.startswith('game: '):
                current_game = line[6:]  # Remove 'game: '
            elif line.startswith('file: '):
                current_file = line[6:]  # Remove 'file: '
            elif ':' in line and current_game:
                # This is metadata for the current game
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                
                # Skip collection-level metadata
                if key not in ['collection', 'shortname', 'extension', 'launch']:
                    current_metadata[key] = value
        
        # Handle last game if file doesn't end with empty line
        if current_game and current_file and current_metadata:
            uuid = current_file.replace('.artp', '')
            existing_metadata_cache[uuid] = current_metadata.copy()
            
        print(f"Parsed existing metadata for {len(existing_metadata_cache)} games.")
        
    except Exception as e:
        print(f"Error parsing existing metadata.pegasus.txt: {e}")
    
    return existing_metadata_cache

def _metadata_fetching_worker(app_map, steamgriddb_api_key, results_queue, cancel_event, 
                            fetch_igdb_enabled, igdb_client_id, igdb_app_access_token, skip_existing, out_dir):
    """Worker function to fetch metadata and asset URLs for all games."""
    total_games = len(app_map)
    processed_games = 0
    errors_occurred = False
    steamgriddb_assets_cache = {}
    igdb_metadata_cache = {}
    
    # Parse existing metadata if skip_existing is enabled (as fallback)
    existing_metadata_cache = {}
    if skip_existing:
        existing_metadata_cache = _parse_existing_metadata(out_dir)
    
    print(f"[Metadata Thread] Starting metadata fetching for {total_games} games.")

    for name, game_data in app_map.items():
        if cancel_event.is_set():
            print("[Metadata Thread] Cancellation detected before processing game:", name)
            break
        
        processed_games += 1
        results_queue.put({
            "status": "game_update", 
            "game_name": name, 
            "current_game_num": processed_games, 
            "total_games": total_games
        })

        uuid = game_data["uuid"]
        
        # Check if we should skip fetching images for this game
        skip_images_for_this_game = False
        if skip_existing:
            artp_file_path = out_dir / f"{uuid}.artp"
            if artp_file_path.exists():
                skip_images_for_this_game = True
                results_queue.put({
                    "status": "asset_update", 
                    "game_name": name, 
                    "asset_info": f"Skipping image fetching for existing ROM file."
                })
                print(f"[Metadata Thread] Skipping image fetching for {name} - ROM file already exists.")

        try:
            # Fetch SteamGridDB asset URLs (skip if we're skipping images for this game)
            steamgriddb_assets_info = {}
            if not skip_images_for_this_game and steamgriddb_api_key:
                steamgriddb_assets_info = fetch_steamgriddb_assets_for_game(name, steamgriddb_api_key, results_queue, cancel_event)
                if steamgriddb_assets_info:
                    steamgriddb_assets_cache[uuid] = steamgriddb_assets_info
                    
            if cancel_event.is_set():
                print(f"[Metadata Thread] Cancellation detected after SteamGridDB fetch for {name}.")
                break

            # Fetch IGDB metadata - always try for textual metadata, control image fetching
            if fetch_igdb_enabled:
                if igdb_client_id and igdb_app_access_token and IGDBWrapper:
                    # For games where we're skipping images, pass a special marker to indicate we have "all images"
                    # This will make IGDB skip image fetching but still get textual metadata
                    steamgriddb_for_igdb = steamgriddb_assets_info if not skip_images_for_this_game else {"_skip_images": True}
                    
                    igdb_data = fetch_igdb_metadata_for_game(name, igdb_client_id, igdb_app_access_token, 
                                                 results_queue, cancel_event, steamgriddb_for_igdb)
                    if igdb_data:
                        # If we're skipping images, remove image_urls from the data
                        if skip_images_for_this_game and "image_urls" in igdb_data:
                            igdb_data_without_images = {k: v for k, v in igdb_data.items() if k != "image_urls"}
                            igdb_metadata_cache[uuid] = igdb_data_without_images
                        else:
                            igdb_metadata_cache[uuid] = igdb_data
                        
                        # Send textual metadata (excluding image_urls) for immediate use
                        igdb_text_data = {k: v for k, v in igdb_data.items() if k != "image_urls"}
                        if igdb_text_data:
                            results_queue.put({
                                "status": "igdb_text_data_ready",
                                "game_uuid": uuid,
                                "game_name": name,
                                "data": igdb_text_data
                            })
                    elif skip_images_for_this_game and uuid in existing_metadata_cache:
                        # Fallback to existing metadata if IGDB call failed and we're skipping images
                        igdb_metadata_cache[uuid] = existing_metadata_cache[uuid]
                        results_queue.put({
                            "status": "igdb_text_data_ready",
                            "game_uuid": uuid,
                            "game_name": name,
                            "data": existing_metadata_cache[uuid]
                        })
                        print(f"[Metadata Thread] Used existing metadata for {name} (IGDB call failed)")
                else:
                    # IGDB not available, try to use existing metadata if skipping images
                    if skip_images_for_this_game and uuid in existing_metadata_cache:
                        igdb_metadata_cache[uuid] = existing_metadata_cache[uuid]
                        results_queue.put({
                            "status": "igdb_text_data_ready",
                            "game_uuid": uuid,
                            "game_name": name,
                            "data": existing_metadata_cache[uuid]
                        })
                        print(f"[Metadata Thread] Used existing metadata for {name} (IGDB not configured)")
                    else:
                        results_queue.put({"status": "asset_update", "game_name": name, "asset_info": "Skipping IGDB: Not configured or library missing."})
                        print(f"[Metadata Thread] Skipping IGDB metadata for {name}: Not configured or library missing.")

        except Exception as e:
            error_msg = f"[Metadata Thread] Error processing metadata for {name}: {e}"
            results_queue.put({"status": "asset_update", "game_name": name, "asset_info": error_msg})
            print(error_msg)
            errors_occurred = True
            
            # If there was an error and we're skipping images, try to use existing metadata
            if skip_images_for_this_game and uuid in existing_metadata_cache:
                igdb_metadata_cache[uuid] = existing_metadata_cache[uuid]
                results_queue.put({
                    "status": "igdb_text_data_ready",
                    "game_uuid": uuid,
                    "game_name": name,
                    "data": existing_metadata_cache[uuid]
                })
                print(f"[Metadata Thread] Used existing metadata for {name} (due to error)")
        
        if cancel_event.is_set():
            print("[Metadata Thread] Cancellation detected after processing game:", name)
            break

    # Send the collected metadata caches back
    results_queue.put({
        "status": "metadata_complete",
        "steamgriddb_assets_cache": steamgriddb_assets_cache,
        "igdb_metadata_cache": igdb_metadata_cache,
        "errors_occurred": errors_occurred
    })
    
    if cancel_event.is_set():
        print("[Metadata Thread] Metadata fetching was cancelled.")
    else:
        print("[Metadata Thread] Metadata fetching complete (not cancelled).")

def _download_assets_worker(app_map, media_base_dir, steamgriddb_assets_cache, igdb_metadata_cache, results_queue, cancel_event):
    """Worker function to download assets based on cached metadata."""
    print(f"[Download Thread] Starting asset downloads.")
    
    for name, game_data in app_map.items():
        if cancel_event.is_set():
            print(f"[Download Thread] Cancellation detected before downloading for {name}.")
            break
            
        uuid = game_data["uuid"]
        media_game_dir = media_base_dir / uuid
        media_game_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Download SteamGridDB assets
            if uuid in steamgriddb_assets_cache:
                steamgriddb_assets = steamgriddb_assets_cache[uuid]
                for asset_type, asset_data in steamgriddb_assets.items():
                    if cancel_event.is_set():
                        break
                        
                    save_path = media_game_dir / asset_data["filename"]
                    if save_path.exists():
                        results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"{asset_data['filename']} already exists. Skipped."})
                        continue
                        
                    results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"Downloading {asset_type}..."})
                    
                    if download_image(asset_data["url"], save_path, headers=asset_data.get("headers")):
                        results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"{asset_data['filename']} downloaded."})
                    else:
                        results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"Failed to download {asset_type}."})
            
            # Download IGDB assets
            if uuid in igdb_metadata_cache:
                image_urls = igdb_metadata_cache[uuid].get("image_urls", {})
                for image_type, image_data in image_urls.items():
                    if cancel_event.is_set():
                        break
                        
                    save_path = media_game_dir / image_data["filename"]
                    if save_path.exists():
                        results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"{image_data['filename']} already exists. Skipped IGDB download."})
                        continue
                        
                    results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"Downloading {image_type} (IGDB)..."})
                    
                    if download_image(image_data["url"], save_path):
                        results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"{image_data['filename']} (IGDB) downloaded."})
                    else:
                        results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"Failed to download {image_data['filename']} (IGDB)."})
                        
        except Exception as e:
            error_msg = f"[Download Thread] Error downloading assets for {name}: {e}"
            results_queue.put({"status": "asset_update", "game_name": name, "asset_info": error_msg})
            print(error_msg)
        
        if cancel_event.is_set():
            break

    results_queue.put({"status": "download_complete"})
    print("[Download Thread] Asset downloads complete.")

def generate_pegasus(root, app_map, host_uuid, host_name, out_dir, config_path, use_steamgriddb, steamgriddb_api_key, 
                     fetch_igdb_enabled, igdb_client_id, igdb_app_access_token, skip_existing=False):
    """Handles Pegasus generation, with threaded asset fetching if enabled."""

    # --- Part 1: Generate .artp files and local boxFront (main thread) ---
    assets_dir = config_path.parent.parent / "assets"
    media_base_dir = out_dir / "media"

    for name, game_data in app_map.items():
        uuid = game_data["uuid"]
        app_image_path_str = game_data.get("app_image")

        (out_dir / f"{uuid}.artp").write_text(f"[metadata]\napp_name={name}\napp_uuid={uuid}\nhost_uuid={host_uuid}\n", encoding="utf-8")

        if app_image_path_str:
            app_image_path = Path(app_image_path_str)
            if not app_image_path.is_absolute():
                app_image_path = assets_dir / app_image_path
            
            if app_image_path.exists() and app_image_path.is_file():
                media_game_dir = media_base_dir / uuid
                media_game_dir.mkdir(parents=True, exist_ok=True)
                
                boxfront_jpg_path = media_game_dir / "boxFront.jpg"
                boxfront_png_path = media_game_dir / "boxFront.png"
                steamgrid_steam_png_path = media_game_dir / "steam.png"

                prioritized_asset_exists = False
                if steamgrid_steam_png_path.exists():
                    print(f"Skipping local image copy for {name} (boxFront.png) as steam.png from SteamGridDB already exists.")
                    prioritized_asset_exists = True
                elif boxfront_jpg_path.exists():
                    print(f"Skipping local image copy for {name} (boxFront.png) as boxFront.jpg from IGDB already exists.")
                    prioritized_asset_exists = True
                
                if not prioritized_asset_exists:
                    if not boxfront_png_path.exists(): 
                        try:
                            shutil.copy2(app_image_path, boxfront_png_path)
                            print(f"Copied local image for {name} to boxFront.png")
                        except Exception as e:
                            print(f"Skipping local image copy for {name} (boxFront.png) due to error: {e}")
                    else:
                        print(f"Skipping local image copy for {name} (boxFront.png), as it already exists and no other prioritized asset was found.")
            else:
                print(f"Skipping local image for {name} (boxFront.png): {app_image_path_str} not found or not a file.")

    _generate_pegasus_metadata_file(app_map, host_uuid, host_name, out_dir, {}) # Initial generation without online metadata

    # --- Part 2: Fetch SteamGridDB and/or IGDB assets/metadata (threaded) ---
    errors_during_fetch = False
    was_cancelled = False
    igdb_metadata_cache = {} 

    # Conditions for starting the threaded fetcher: SteamGridDB enabled OR IGDB enabled.
    # SteamGridDB also requires its API key and requests library.
    # IGDB requires its credentials, requests, and IGDBWrapper.
    should_start_fetch_thread = False
    if use_steamgriddb and steamgriddb_api_key and requests:
        should_start_fetch_thread = True
    
    # Ensure fetch_igdb_enabled is also considered for starting the thread, even if SteamGridDB is not used.
    if fetch_igdb_enabled and igdb_client_id and igdb_app_access_token and requests and IGDBWrapper:
        should_start_fetch_thread = True
    else:
        # If IGDB was intended but prerequisites are missing at this stage, inform the user.
        if fetch_igdb_enabled and not (igdb_client_id and igdb_app_access_token and requests and IGDBWrapper):
            print("IGDB fetching was enabled, but prerequisites (credentials, requests, or IGDBWrapper) are missing. Skipping IGDB.")
            fetch_igdb_enabled = False # Disable it for the worker if it can't run

    if should_start_fetch_thread:
        cancel_event = threading.Event()
        progress_dialog, lbl_game_status, lbl_asset_status = show_progress_dialog(root, cancel_event, len(app_map))
        results_q = queue.Queue()
        
        # Pass the explicit IGDB parameters and skip_existing to the worker
        fetch_thread = threading.Thread(target=_metadata_fetching_worker, 
                                        args=(app_map, 
                                              steamgriddb_api_key if use_steamgriddb else None, # Pass key only if use_steamgriddb
                                              results_q, 
                                              cancel_event,
                                              fetch_igdb_enabled, # Use the parameter passed to generate_pegasus
                                              igdb_client_id,    # Use the parameter
                                              igdb_app_access_token, # Use the parameter
                                              skip_existing,    # Pass the skip_existing parameter
                                              out_dir           # Pass out_dir for checking .artp files
                                              ))
        fetch_thread.start()

        final_steps_executed = False
        def execute_final_steps():
            nonlocal final_steps_executed
            if final_steps_executed: return
            final_steps_executed = True
            if progress_dialog.winfo_exists(): progress_dialog.destroy()
            _generate_pegasus_metadata_file(app_map, host_uuid, host_name, out_dir, igdb_metadata_cache)
            final_message = f"Pegasus Frontend files created in '{out_dir.name}'!"
            if was_cancelled: final_message = f"Asset fetching cancelled. Metadata file generated (may be incomplete)."
            elif errors_during_fetch: final_message += "\n\nNote: Some errors occurred during asset/metadata fetching. Check console."
            messagebox.showinfo("Done", final_message)
            open_directory(out_dir)
            print("Pegasus generation steps completed.")

        def check_queue():
            nonlocal errors_during_fetch, was_cancelled, download_thread
            
            try:
                message = results_q.get_nowait()
                if message["status"] == "game_update":
                    lbl_game_status.config(text=f"Game {message['current_game_num']}/{message['total_games']}: {message['game_name']}")
                    lbl_asset_status.config(text="Preparing...")
                elif message["status"] == "asset_update":
                    asset_info_str = str(message.get("asset_info", ""))
                    max_len = 50
                    display_info = (asset_info_str[:max_len] + '...') if len(asset_info_str) > max_len else asset_info_str
                    lbl_asset_status.config(text=display_info)
                elif message["status"] == "igdb_text_data_ready":
                    igdb_metadata_cache[message["game_uuid"]] = message["data"]
                    print(f"[Queue] IGDB text data for {message['game_name']} ({message['game_uuid']}) cached.")
                elif message["status"] == "metadata_complete":
                    # Metadata collection is complete, now start downloads
                    steamgriddb_assets_cache = message["steamgriddb_assets_cache"]
                    igdb_metadata_cache_full = message["igdb_metadata_cache"]
                    errors_during_fetch = message.get("errors_occurred", False)
                    
                    lbl_game_status.config(text="Starting asset downloads...")
                    lbl_asset_status.config(text="Preparing downloads...")
                    
                    # Start download thread
                    download_thread = threading.Thread(target=_download_assets_worker, 
                                                     args=(app_map, media_base_dir, steamgriddb_assets_cache, 
                                                           igdb_metadata_cache_full, results_q, cancel_event))
                    download_thread.start()
                elif message["status"] == "download_complete":
                    execute_final_steps()
                elif message["status"] == "cancelled":
                    was_cancelled = True
                    execute_final_steps()
            except queue.Empty:
                pass 
            finally:
                if not final_steps_executed:
                    # Check if any threads are still running or if queue has items
                    threads_running = fetch_thread.is_alive()
                    if download_thread and download_thread.is_alive():
                        threads_running = True
                        
                    if threads_running or not results_q.empty():
                        root.after(100, check_queue)
                    else: 
                        print("[Queue] All threads complete, queue empty, no final signal. Forcing final steps.")
                        execute_final_steps()
        
        # Initialize download_thread in the outer scope
        download_thread = None
        root.after(100, check_queue)
    else: 
        print("Skipping online asset/metadata fetching (SteamGridDB/IGDB not enabled or prerequisites missing).")
        _generate_pegasus_metadata_file(app_map, host_uuid, host_name, out_dir, igdb_metadata_cache) # Final metadata with empty cache
        messagebox.showinfo("Done", f"Pegasus Frontend files created in '{out_dir.name}'! (No assets/metadata fetched online)")
        open_directory(out_dir) 