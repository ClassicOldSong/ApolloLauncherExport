#!/usr/bin/env python3
import threading
import queue
from tkinter import messagebox
from utils import open_directory, sanitize_filename
from .generic_generator import generate_generic_art_files
from api_clients import FetchJob, MetadataFetcher
from gui_components import show_progress_dialog
from .gamelist_generator import _generate_gamelist_xml

def generate_esde(root, app_map, host_uuid, host_name, out_dir,
                  metadata_fetcher: MetadataFetcher | None,
                  skip_existing_rom_files_for_images: bool):
    """Generate ES-DE launcher files and optionally fetch metadata."""

    es_system_name_for_gamelist = "artemis"

    (out_dir / "es_systems.xml").write_text(f"""<systemList>
  <system>
    <name>{es_system_name_for_gamelist}</name>
    <fullname>{host_name}</fullname>
    <path>%ROMPATH%/{es_system_name_for_gamelist}</path>
    <extension>.art</extension>
    <command label=\"Artemis\">%EMULATOR_Artemis% %ACTION%=android.intent.action.VIEW %DATA%=%ROMPROVIDER%</command>
    <platform>{es_system_name_for_gamelist}</platform>
    <theme>{es_system_name_for_gamelist}</theme>
  </system>
</systemList>""", encoding="utf-8")
    print("ES-DE es_systems.xml generated.")

    (out_dir / "es_find_rules.xml").write_text("""<ruleList>
  <emulator name=\"Artemis\">
    <rule type=\"androidpackage\">
      <entry>com.limelight.noir/com.limelight.ShortcutTrampoline</entry>
    </rule>
  </emulator>
</ruleList>""", encoding="utf-8")
    print("ES-DE es_find_rules.xml generated.")

    if not metadata_fetcher:
        _generate_gamelist_xml(app_map, {}, out_dir, ".art", es_system_name_for_gamelist)
        messagebox.showinfo("Done", f"ES-DE files and basic gamelist.xml created in '{out_dir.name}'!\n(Online fetching disabled/not configured)")
        open_directory(out_dir)
        return

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
                "background": media_base_dir / "backgrounds" / sanitized_game_name 
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
        generate_generic_art_files(app_map, host_uuid, host_name, out_dir)
        _generate_gamelist_xml(app_map, {}, out_dir, ".art", es_system_name_for_gamelist)
        messagebox.showinfo("Done", f"ES-DE files created in '{out_dir.name}'! (No fetch jobs prepared)")
        open_directory(out_dir)
        return

    cancel_event = threading.Event()
    progress_dialog, lbl_job_status, lbl_task_status = show_progress_dialog(root, cancel_event, len(fetch_jobs))
    results_q = queue.Queue()

    fetch_thread = threading.Thread(target=metadata_fetcher.execute_fetch_plan,
                                    args=(fetch_jobs, results_q, cancel_event, None))
    fetch_thread.start()

    final_all_results_cache = {}
    errors_during_fetch = False
    was_cancelled = False
    final_steps_executed = False

    def execute_final_esde_steps():
        nonlocal final_steps_executed, errors_during_fetch, was_cancelled
        if final_steps_executed: return
        final_steps_executed = True

        if progress_dialog.winfo_exists(): progress_dialog.destroy()
        
        generate_generic_art_files(app_map, host_uuid, host_name, out_dir)
        _generate_gamelist_xml(app_map, final_all_results_cache, out_dir, ".art", es_system_name_for_gamelist)

        final_message = f"ES-DE files created in '{out_dir.name}'!"
        if was_cancelled:
            final_message = f"Asset fetching cancelled. Files generated (metadata may be incomplete)."
        elif errors_during_fetch:
            final_message += "\n\nNote: Some errors occurred during asset/metadata fetching."
        
        messagebox.showinfo("Done", final_message)
        open_directory(out_dir)
        print("ES-DE generation steps completed.")

    def check_esde_queue():
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
                final_all_results_cache[uuid] = message["data"]
            elif message["status"] == "fetch_plan_complete":
                print("[ES-DE Queue] Fetch plan complete.")
                execute_final_esde_steps()
            elif message["status"] == "global_update" and "cancelled" in message.get("info", "").lower():
                was_cancelled = True
                print("[ES-DE Queue] Fetch plan cancellation acknowledged.")
                if not fetch_thread.is_alive():
                    execute_final_esde_steps()
            elif message["status"] == "cancelled":
                was_cancelled = True
                cancel_event.set()
                print("[ES-DE Queue] UI Cancel button acknowledged.")

        except queue.Empty:
            pass
        finally:
            if not final_steps_executed:
                if fetch_thread.is_alive():
                    root.after(100, check_esde_queue)
                else:
                    print("[ES-DE Queue] Fetch thread dead. Forcing final steps.")
                    execute_final_esde_steps()

    root.after(100, check_esde_queue) 