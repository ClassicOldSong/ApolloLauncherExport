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

from utils import open_directory
from gui_components import show_progress_dialog
from api_clients import MetadataFetcher, FetchJob

def _generate_pegasus_metadata_file(app_map, host_uuid, host_name, out_dir, all_fetched_text_data):
    """Generates the metadata.pegasus.txt file using collated fetched text data."""
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

        # Check for and append IGDB metadata if available from the fetch results
        if uuid in all_fetched_text_data and all_fetched_text_data[uuid]:
            igdb_data = all_fetched_text_data[uuid] # This now directly contains the text fields
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
                        # Trim and filter empty lines for description/summary
                        if pegasus_key in ["summary", "description"]:
                            processed_lines = [line.strip() for line in lines if line.strip()]
                            if not processed_lines: continue # Skip if all lines are empty after processing
                            metadata_content.append(f"{pegasus_key}: {processed_lines[0]}")
                            for line in processed_lines[1:]:
                                metadata_content.append(f"  {line}")
                        else:
                            metadata_content.append(f"{pegasus_key}: {lines[0].strip()}") # Trim first line for other fields
                            for line in lines[1:]:
                                stripped_line = line.strip()
                                if stripped_line: # Add only if not empty after stripping
                                    metadata_content.append(f"  {stripped_line}")
                    else:
                        metadata_content.append(f"{pegasus_key}: {text_value.strip()}") # Trim single line text

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

def generate_pegasus(root, app_map, host_uuid, host_name, out_dir, config_path, 
                     metadata_fetcher: MetadataFetcher | None, 
                     skip_existing_rom_files_for_images=False): # Renamed for clarity, this is the UI checkbox
    """Handles Pegasus generation, using MetadataFetcher for asset/metadata tasks."""

    assets_dir = config_path.parent.parent / "assets"
    media_base_dir = out_dir / "media" # This is where FetchJob will place downloaded assets

    # --- Part 1: Generate .artp files and copy local boxFront (main thread) ---
    # This part also helps determine if image fetching for a specific game can be skipped
    game_specific_image_skip_flags = {}

    for name, game_data in app_map.items():
        uuid = game_data["uuid"]
        app_image_path_str = game_data.get("app_image")

        (out_dir / f"{uuid}.artp").write_text(f"[metadata]\napp_name={name}\napp_uuid={uuid}\nhost_uuid={host_uuid}\n", encoding="utf-8")
        
        media_game_dir = media_base_dir / uuid # Define media_game_dir for each game
        # No need to mkdir here yet, FetchJob output_directory will ensure it.

        # Check for local image copy logic
        if app_image_path_str:
            app_image_path = Path(app_image_path_str)
            if not app_image_path.is_absolute():
                app_image_path = assets_dir / app_image_path
            
            if app_image_path.exists() and app_image_path.is_file():
                # Create directory if we are going to copy something
                media_game_dir.mkdir(parents=True, exist_ok=True)

                boxfront_png_path = media_game_dir / "boxFront.png" # Default local copy filename
                # We don't check for steam.png or boxFront.jpg here for *skipping the copy*
                # because those will be handled by the MetadataFetcher based on desired assets.
                # The local copy is a fallback if no other cover-like asset is specifically requested or found.
                # However, if skip_existing_rom_files_for_images is true, AND an .artp exists, 
                # we might want to inform the FetchJob to skip images.
                
                if not boxfront_png_path.exists(): # Only copy if our specific target doesn't exist
                    try:
                        shutil.copy2(app_image_path, boxfront_png_path)
                        print(f"Copied local image for {name} to {boxfront_png_path.name}")
                    except Exception as e:
                        print(f"Skipping local image copy for {name} ({boxfront_png_path.name}) due to error: {e}")
                else:
                    print(f"Local image {boxfront_png_path.name} already exists for {name}. Not overwriting with local copy.")
            else:
                print(f"Skipping local image for {name}: {app_image_path_str} not found or not a file.")

        # Determine game_specific_image_skip_flags based on UI checkbox and .artp existence
        artp_file_path = out_dir / f"{uuid}.artp"
        if skip_existing_rom_files_for_images and artp_file_path.exists():
            game_specific_image_skip_flags[uuid] = True
            print(f"Flagging {name} ({uuid}) to skip all image downloads due to existing .artp and UI setting.")
        else:
            game_specific_image_skip_flags[uuid] = False

    # Initial metadata file without online data, or with previously cached data if we were to load it here.
    # For now, always generate an initial empty one, to be overwritten if fetching occurs.
    _generate_pegasus_metadata_file(app_map, host_uuid, host_name, out_dir, {}) 

    # --- Part 2: Prepare and Execute Fetch Plan via MetadataFetcher (threaded) ---
    if not metadata_fetcher:
        messagebox.showinfo("Done", f"Pegasus Frontend files created in '{out_dir.name}'! (Online fetching disabled/not configured)")
        open_directory(out_dir)
        return

    fetch_jobs = []
    for name, game_data in app_map.items():
        uuid = game_data["uuid"]
        game_output_dir = media_base_dir / uuid

        # Define desired assets for Pegasus - this is where frontend specific logic goes
        desired_sgdb_assets_map = {}
        if metadata_fetcher.steamgriddb_api_key:
            desired_sgdb_assets_map = {
                "logo": "logo",      # API asset type: desired basename for Pegasus
                "steam": "steam",    # For grid/cover
                "hero": "marqee",    # SGDB "hero" is Pegasus "marqee"
                "tile": "tile"
            }

        igdb_assets_map = {}
        if metadata_fetcher.igdb_client_id: # Also implies token is likely present if fetcher is used
            igdb_assets_map = {
                "boxFront": "boxFront", # For cover
                "screenshot": "screenshot",
                "background": "background"
            }

        job = FetchJob(
            game_name=name,
            uuid=uuid,
            output_directory=game_output_dir,
            steamgriddb_assets=desired_sgdb_assets_map,
            fetch_igdb_text_metadata=True if metadata_fetcher.igdb_client_id else False,
            igdb_assets=igdb_assets_map,
            skip_all_image_fetching_for_this_game=game_specific_image_skip_flags.get(uuid, False)
        )
        fetch_jobs.append(job)

    if not fetch_jobs:
        messagebox.showinfo("Done", f"Pegasus Frontend files created in '{out_dir.name}'! (No fetch jobs prepared)")
        open_directory(out_dir)
        return

    cancel_event = threading.Event()
    # The show_progress_dialog now needs to be more generic or adapted for new queue messages
    # For now, let's assume it can be updated to reflect "Job X/Y" and "Current task..."
    progress_dialog, lbl_job_status, lbl_task_status = show_progress_dialog(root, cancel_event, len(fetch_jobs))
    
    results_q = queue.Queue()
    
    # The MetadataFetcher.execute_fetch_plan will run in this thread.
    # The generator waits for it to complete.
    fetch_thread = threading.Thread(target=metadata_fetcher.execute_fetch_plan,
                                    args=(fetch_jobs, results_q, cancel_event, None)) # Passing root_ui=None for now
    fetch_thread.start()

    final_all_results_cache = {} # To store {uuid: {text_data: {}, downloaded_steamgriddb_assets: {}, downloaded_igdb_assets: {}} }
    final_text_data_for_metadata_file = {} # Specifically {uuid: text_data_dict}
    errors_during_fetch = False
    was_cancelled = False
    final_steps_executed = False

    def execute_final_pegasus_steps():
        nonlocal final_steps_executed, errors_during_fetch, was_cancelled
        if final_steps_executed: return
        final_steps_executed = True

        if progress_dialog.winfo_exists(): progress_dialog.destroy()
        
        # Regenerate metadata file with all fetched text data
        _generate_pegasus_metadata_file(app_map, host_uuid, host_name, out_dir, final_text_data_for_metadata_file)
        
        final_message = f"Pegasus Frontend files created in '{out_dir.name}'!"
        if was_cancelled:
            final_message = f"Asset fetching cancelled. Metadata file generated (may be incomplete)."
        elif errors_during_fetch: # We need a way to flag errors from queue messages
            final_message += "\n\nNote: Some errors may have occurred during asset/metadata fetching. Check console."
        
        messagebox.showinfo("Done", final_message)
        open_directory(out_dir)
        print("Pegasus generation steps completed.")

    def check_pegasus_queue():
        nonlocal errors_during_fetch, was_cancelled, final_all_results_cache, final_text_data_for_metadata_file
        try:
            message = results_q.get_nowait()

            if message["status"] == "job_update":
                # Update main progress label (e.g., "Job 2/10: Processing The Witcher 3")
                lbl_job_status.config(text=f"Game {message['current_job_num']}/{message['total_jobs']}: {message['game_name']}")
                lbl_task_status.config(text="Starting...") # Generic message for new job
            elif message["status"] == "asset_update":
                # Update secondary progress label (e.g., "SteamGridDB: Downloading logo...")
                asset_info_str = str(message.get("asset_info", ""))
                max_len = 70 # Allow more length for task status
                display_info = (asset_info_str[:max_len] + '...') if len(asset_info_str) > max_len else asset_info_str
                lbl_task_status.config(text=display_info)
                if "error" in asset_info_str.lower() or "failed" in asset_info_str.lower():
                    errors_during_fetch = True
            elif message["status"] == "job_completed":
                # A single job from the plan has finished, its data is in message["data"]
                # We can store this if needed for very detailed post-processing
                uuid = message["uuid"]
                final_all_results_cache[uuid] = message["data"]
                if message["data"].get("text_data"):
                    final_text_data_for_metadata_file[uuid] = message["data"]["text_data"]
                print(f"[Queue] Job for {message["data"]["game_name"]} ({uuid}) completed.")
            elif message["status"] == "fetch_plan_complete":
                # All jobs are done. message["all_results"] contains everything.
                # This is the main signal to finalize things.
                # final_all_results_cache should already be populated by job_completed messages, 
                # but all_results is the definitive final state.
                for uuid, result_data in message["all_results"].items():
                     if result_data.get("text_data"):
                        final_text_data_for_metadata_file[uuid] = result_data["text_data"]
                print("[Queue] Fetch plan complete signal received.")
                execute_final_pegasus_steps()
            elif message["status"] == "global_update" and "cancelled" in message.get("info", "").lower():
                was_cancelled = True
                # Fetch plan might send this if cancel_event was set early
                print("[Queue] Fetch plan cancellation acknowledged.")
                if not fetch_thread.is_alive(): # Ensure thread has fully stopped
                    execute_final_pegasus_steps()
            elif message["status"] == "cancelled": # This might come from the dialog's cancel button action directly
                was_cancelled = True
                cancel_event.set() # Ensure the event is set for the fetch_thread
                print("[Queue] UI Cancel button acknowledged.")
                # Wait for thread to see cancel and finish up before executing final steps

        except queue.Empty:
            pass
        finally:
            if not final_steps_executed:
                if fetch_thread.is_alive():
                    root.after(100, check_pegasus_queue)
                else:
                    # Thread finished, but fetch_plan_complete might not have been the last message
                    # or cancel occurred. Ensure final steps are run.
                    print("[Queue] Fetch thread dead. Forcing final steps if not already executed.")
                    execute_final_pegasus_steps()

    root.after(100, check_pegasus_queue) 