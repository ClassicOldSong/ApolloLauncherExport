#!/usr/bin/env python3
import json
import threading
import queue
from tkinter import messagebox
from utils import open_directory
from utils import sanitize_filename
from generators.generic_generator import generate_generic_art_files
from api_clients import FetchJob, MetadataFetcher
from gui_components import show_progress_dialog
from .gamelist_generator import _generate_gamelist_xml

def generate_daijishou(root, app_map, host_uuid, host_name, out_dir,
                       metadata_fetcher: MetadataFetcher | None,
                       skip_existing_rom_files_for_images: bool):
    """Generate Daijishō launcher files and optionally fetch metadata."""

    # Daijishō specific platform JSON
    payload = {
        "databaseVersion": 14,
        "revisionNumber": 2,
        "platform": {
            "name": host_name,
            "uniqueId": host_uuid,
            "shortname": "artemis",
            "acceptedFilenameRegex": r"^(?!(?:\._|\.).*).*$",
            "screenAspectRatioId": 1,
            "boxArtAspectRatioId": 0,
            "extra": "",
        },
        "playerList": [
            {
                "name": "artemis",
                "uniqueId": "com.limelight.noir",
                "description": "Supported extensions: art",
                "acceptedFilenameRegex": r"^(.*)\.(?:art)$",
                "amStartArguments": (
                    "-n com.limelight.noir/com.limelight.ShortcutTrampoline\n"
                    " -a android.intent.action.VIEW\n"
                    " -d {file.uri}\n"
                ),
                "killPackageProcesses": True,
                "killPackageProcessesWarning": True,
                "extra": "",
            }
        ],
    }
    platform_json_path = out_dir / f"{sanitize_filename(host_name)}.json"
    platform_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Daijishō platform JSON generated at {platform_json_path}")

    if not metadata_fetcher:
        # Still generate a basic gamelist.xml even if no fetching
        generate_generic_art_files(app_map, host_uuid, host_name, out_dir)
        _generate_gamelist_xml(app_map, {}, out_dir, ".art", host_name)
        messagebox.showinfo("Done", f"Daijishō files (.art), platform JSON, and basic gamelist.xml created in '{out_dir.name}'!\n(Online fetching disabled/not configured)")
        open_directory(out_dir)
        return

    # --- Metadata Fetching Logic ---
    media_base_dir = out_dir / "media"

    fetch_jobs = []
    game_specific_image_skip_flags = {}

    for name, game_data in app_map.items():
        uuid = game_data["uuid"]
        sanitized_game_name = sanitize_filename(name)
        art_file_path = out_dir / f"{sanitized_game_name}.art"

        if skip_existing_rom_files_for_images and art_file_path.exists():
            game_specific_image_skip_flags[uuid] = True
        else:
            game_specific_image_skip_flags[uuid] = False
        
        desired_sgdb_assets_map = {}
        if metadata_fetcher.steamgriddb_api_key:
            desired_sgdb_assets_map = {
                "steam": media_base_dir / "images" / sanitized_game_name, 
                "logo": media_base_dir / "logos" / sanitized_game_name,
            }

        igdb_assets_map = {}
        if metadata_fetcher.igdb_client_id:
            igdb_assets_map = {
                "boxFront": media_base_dir / "images" / sanitized_game_name, 
                "screenshot": media_base_dir / "screenshots" / sanitized_game_name,
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

    if not fetch_jobs: # Should not happen if metadata_fetcher is present, but as a safeguard
        _generate_gamelist_xml(app_map, {}, out_dir, ".art", host_name)
        messagebox.showinfo("Done", f"Daijishō files created in '{out_dir.name}'! (No fetch jobs prepared)")
        open_directory(out_dir)
        return

    cancel_event = threading.Event()
    progress_dialog, lbl_job_status, lbl_task_status = show_progress_dialog(root, cancel_event, len(fetch_jobs))
    results_q = queue.Queue()

    fetch_thread = threading.Thread(target=metadata_fetcher.execute_fetch_plan,
                                    args=(fetch_jobs, results_q, cancel_event, None)) # root_ui=None
    fetch_thread.start()

    final_all_results_cache = {} # To store {uuid: {text_data: {}, downloaded_steamgriddb_assets: {}, ...}}
    errors_during_fetch = False
    was_cancelled = False
    final_steps_executed = False

    def execute_final_daijishou_steps():
        nonlocal final_steps_executed, errors_during_fetch, was_cancelled
        if final_steps_executed: return
        final_steps_executed = True

        if progress_dialog.winfo_exists(): progress_dialog.destroy()
        
        generate_generic_art_files(app_map, host_uuid, host_name, out_dir)
        _generate_gamelist_xml(app_map, final_all_results_cache, out_dir, ".art", host_name)

        final_message = f"Daijishō files created in '{out_dir.name}'!"
        if was_cancelled:
            final_message = f"Asset fetching cancelled. Files generated (metadata may be incomplete)."
        elif errors_during_fetch:
            final_message += "\n\nNote: Some errors occurred during asset/metadata fetching."
        
        messagebox.showinfo("Done", final_message)
        open_directory(out_dir)
        print("Daijishō generation steps completed.")

    def check_daijishou_queue():
        nonlocal errors_during_fetch, was_cancelled, final_all_results_cache, final_steps_executed
        try:
            message = results_q.get_nowait()

            if message["status"] == "job_update":
                lbl_job_status.config(text=f"Game {message['current_job_num']}/{message['total_jobs']}: {message['game_name']}")
                lbl_task_status.config(text="Starting...")
            elif message["status"] == "asset_update":
                asset_info_str = str(message.get("asset_info", ""))
                max_len = 70
                display_info = (asset_info_str[:max_len] + '...') if len(asset_info_str) > max_len else asset_info_str
                lbl_task_status.config(text=display_info)
                if "error" in asset_info_str.lower() or "failed" in asset_info_str.lower():
                    errors_during_fetch = True
            elif message["status"] == "job_completed":
                uuid = message["uuid"]
                final_all_results_cache[uuid] = message["data"] # Store all data for this job
                # print(f"[Daijishō Queue] Job for {message['data']['game_name']} ({uuid}) completed.")
            elif message["status"] == "fetch_plan_complete":
                # final_all_results_cache is already populated by job_completed messages.
                # message["all_results"] could be used to overwrite/confirm if needed.
                # For simplicity, we'll rely on job_completed incrementally building the cache.
                print("[Daijishō Queue] Fetch plan complete.")
                execute_final_daijishou_steps()
            elif message["status"] == "global_update" and "cancelled" in message.get("info", "").lower():
                was_cancelled = True
                print("[Daijishō Queue] Fetch plan cancellation acknowledged.")
                if not fetch_thread.is_alive(): # Ensure thread has fully stopped
                    execute_final_daijishou_steps()
            elif message["status"] == "cancelled": # This might come from the dialog's cancel button action
                was_cancelled = True
                cancel_event.set() # Ensure the event is set for the fetch_thread
                print("[Daijishō Queue] UI Cancel button acknowledged.")
                # Wait for thread to see cancel and finish up if it's still alive

        except queue.Empty:
            pass
        finally:
            if not final_steps_executed:
                if fetch_thread.is_alive():
                    root.after(100, check_daijishou_queue)
                else:
                    # Thread finished, but fetch_plan_complete might not have been the last message
                    # or cancel occurred. Ensure final steps are run.
                    print("[Daijishō Queue] Fetch thread dead. Forcing final steps if not already executed.")
                    execute_final_daijishou_steps()

    root.after(100, check_daijishou_queue) 