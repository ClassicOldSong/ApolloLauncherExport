#!/usr/bin/env python3
import threading
import queue
import shutil
from pathlib import Path
from tkinter import messagebox
from generators.generic_generator import generate_generic_art_files

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

from utils import open_directory, sanitize_filename
from gui_components import show_progress_dialog
from api_clients import MetadataFetcher, FetchJob

def _generate_pegasus_metadata_file(app_map, host_uuid, host_name, out_dir, all_fetched_text_data):
    """Generates the metadata.pegasus.txt file using collated fetched text data."""
    metadata_content = []
    metadata_content.append(f"collection: {host_name}")
    metadata_content.append("shortname: artemis")
    metadata_content.append("extension: art")
    launch_command = f"am start -n com.limelight.noir/com.limelight.ShortcutTrampoline -a android.intent.action.VIEW -d {{file.uri}}"
    metadata_content.append(f"launch: {launch_command}")
    metadata_content.append("")

    generate_generic_art_files(app_map, host_uuid, host_name, out_dir)

    for name, game_data in app_map.items():
        uuid = game_data["uuid"]
        metadata_content.append(f"game: {name}")
        metadata_content.append(f"file: {sanitize_filename(name)}.art")

        # Check for and append IGDB metadata if available from the fetch results
        if uuid in all_fetched_text_data and all_fetched_text_data[uuid]:
            igdb_data = all_fetched_text_data[uuid]
            
            pegasus_field_mapping = {
                "summary": "summary",
                "storyline": "description",
                "developer": "developer",
                "publisher": "publisher",
                "genre": "genre",
                "rating": "rating",
                "release_date": "release"
            }

            for igdb_processed_key, pegasus_key in pegasus_field_mapping.items():
                if igdb_data.get(igdb_processed_key):
                    raw_value = igdb_data[igdb_processed_key]
                    processed_value_str = ""

                    if isinstance(raw_value, list):
                        processed_value_str = ", ".join(str(item).strip() for item in raw_value if str(item).strip())
                    elif igdb_processed_key == "release_date" and isinstance(raw_value, str):
                        processed_value_str = raw_value.split(" ")[0]
                    elif isinstance(raw_value, (float, int)):
                        processed_value_str = str(raw_value)
                    elif isinstance(raw_value, str):
                        processed_value_str = raw_value
                    else:
                        processed_value_str = str(raw_value)

                    if not processed_value_str.strip():
                        continue
                    
                    # Multi-line formatting logic:
                    # Check for actual newline character OR if the string is very long (for summary/description)
                    is_potentially_multiline = "\n" in processed_value_str
                    is_long_text = len(processed_value_str) > 80
                    
                    if pegasus_key in ["summary", "description"] and (is_potentially_multiline or is_long_text):
                        # Use splitlines() to handle different newline types correctly (\n, \r\n)
                        current_lines = [line.strip() for line in processed_value_str.splitlines() if line.strip()]
                        if not current_lines: # If all lines are empty after stripping
                            # Try splitting by sentence for very long lines without explicit newlines for summary/description
                            if is_long_text and not is_potentially_multiline and len(processed_value_str.split(". ")) > 1 :
                                current_lines = [line.strip() + "." if not line.endswith(".") else line.strip() for line in processed_value_str.split(". ") if line.strip()]
                                # Remove trailing period from last sentence if split added extra
                                if current_lines and processed_value_str.endswith(".") and current_lines[-1].endswith(".."):
                                     current_lines[-1] = current_lines[-1][:-1]
                                elif not processed_value_str.endswith(".") and current_lines and current_lines[-1].endswith("."): # if original didn't end with '.'
                                     current_lines[-1] = current_lines[-1][:-1]


                            if not current_lines: continue # Skip if still no content

                        metadata_content.append(f"{pegasus_key}: {current_lines[0]}")
                        for line_content in current_lines[1:]:
                            metadata_content.append(f"  {line_content}")
                    else:
                        # For other fields or non-multiline summary/description,
                        # replace newlines with spaces to ensure a single line.
                        final_single_line_value = processed_value_str.replace("\n", " ").strip()
                        if final_single_line_value: # ensure not empty
                           metadata_content.append(f"{pegasus_key}: {final_single_line_value}")

            # Handle 'tags' by combining multiple list fields from IGDB
            tag_source_keys = ["game_modes", "player_perspectives", "themes", "keywords"]
            all_tags_list = []
            for key in tag_source_keys:
                if igdb_data.get(key) and isinstance(igdb_data[key], list):
                    all_tags_list.extend(str(item).strip() for item in igdb_data[key] if str(item).strip())
            
            if all_tags_list:
                # Create a unique, sorted list of tags
                unique_tags = sorted(list(set(tag_item for tag_item in all_tags_list if tag_item)))
                if unique_tags:
                    metadata_content.append(f"tags: {', '.join(unique_tags)}")

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

        
        # media_game_dir is where FetchJob places downloads initially (media/uuid/)
        # It will be created by FetchJob if needed. Local copies go elsewhere.

        # Check for local image copy logic
        if app_image_path_str:
            app_image_path = Path(app_image_path_str)
            if not app_image_path.is_absolute():
                app_image_path = assets_dir / app_image_path
            
            if app_image_path.exists() and app_image_path.is_file():
                sanitized_game_name = sanitize_filename(name)
                media_type_for_local_copy = "box2dfront" # Local images are treated as boxFront
                target_media_dir_for_local = media_base_dir / media_type_for_local_copy
                
                source_file_extension = app_image_path.suffix # e.g. ".png"
                new_local_copy_path = target_media_dir_for_local / f"{sanitized_game_name}{source_file_extension}"

                # Create directory if we are going to copy something
                target_media_dir_for_local.mkdir(parents=True, exist_ok=True)
                
                if not new_local_copy_path.exists(): # Only copy if our specific target doesn't exist
                    try:
                        shutil.copy2(app_image_path, new_local_copy_path)
                        print(f"Copied local image for {name} to {new_local_copy_path}")
                    except Exception as e:
                        print(f"Skipping local image copy for {name} ({new_local_copy_path}) due to error: {e}")
                else:
                    print(f"Local image {new_local_copy_path} already exists for {name}. Not overwriting with local copy.")
            else:
                print(f"Skipping local image for {name}: {app_image_path_str} not found or not a file.")

        # Determine game_specific_image_skip_flags based on UI checkbox and .artp existence
        art_file_path = out_dir / f"{sanitized_game_name}.art"
        if skip_existing_rom_files_for_images and art_file_path.exists():
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
        sanitized_game_name = sanitize_filename(name)

        # Define desired assets for Pegasus - this is where frontend specific logic goes
        desired_sgdb_assets_map = {}
        if metadata_fetcher.steamgriddb_api_key:
            desired_sgdb_assets_map = {
                "logo": media_base_dir / "logo" / sanitized_game_name,      # API asset type: desired basename for Pegasus
                "steam": media_base_dir / "steam" / sanitized_game_name,    # For grid/cover
                "hero": media_base_dir / "marqee" / sanitized_game_name,    # SGDB "hero" is Pegasus "marqee"
                "tile": media_base_dir / "tile" / sanitized_game_name
            }

        igdb_assets_map = {}
        if metadata_fetcher.igdb_client_id: # Also implies token is likely present if fetcher is used
            igdb_assets_map = {
                "boxFront": media_base_dir / "box2dfront" / sanitized_game_name, # For cover
                "screenshot": media_base_dir / "screenshot" / sanitized_game_name,
                "background": media_base_dir / "background" / sanitized_game_name
            }

        job = FetchJob(
            game_name=name,
            game_uuid=uuid,
            steamgriddb_assets=desired_sgdb_assets_map,
            fetch_igdb_text_metadata=True if metadata_fetcher.igdb_client_id else False,
            igdb_assets=igdb_assets_map,
            skip_images=game_specific_image_skip_flags.get(uuid, False)
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
            final_message += "\n\nNote: Some errors may have occurred during asset/metadata fetching."
        
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