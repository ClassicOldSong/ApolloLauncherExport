#!/usr/bin/env python3
# ApolloLauncherExport.py
#
# Derived from:
# https://github.com/Jetup13/Retroid-Pocket-3-Plus-Wiki/blob/main/Files/Backup/MoonlightFileGenerator.py
#
# Generate Pegasus Frontend (.artp) / Daijishō (.art) / ES-DE launcher files (.artes) for Apollo–Artemis.
# Python 3.8+ -- only stdlib (tkinter, configparser, json, shutil, pathlib).

import json, re, sys, shutil, os, subprocess
from pathlib import Path
from tkinter import Tk, Button, Label, filedialog, messagebox, Frame, simpledialog, Toplevel
from configparser import ConfigParser, NoSectionError, NoOptionError
import threading
import queue
try:
    import requests # For SteamGridDB integration
except ImportError:
    messagebox.showwarning("Missing Dependency", "The 'requests' library is not installed. SteamGridDB functionality will be disabled. Please install it using: pip install requests")
    requests = None

def get_script_dir() -> Path:
	"""Get the base directory for the application, whether running as script or exe."""
	if getattr(sys, 'frozen', False):
		# Running as PyInstaller exe
		return Path(sys.executable).parent
	else:
		# Running as script
		return Path(__file__).parent

SCRIPT_DIR = get_script_dir()
BASE_DIR   = SCRIPT_DIR / "export"
CONFIG_FILE_PATH = SCRIPT_DIR / "config.ini"

# Global store for loaded configuration
app_config = {
    "apollo_conf_path": None,
    "steamgriddb_api_key": None
}

# ────────────────────────────────────────────────────────────────────────────
# Configuration File Handling
# ────────────────────────────────────────────────────────────────────────────
def load_config():
    """Loads configuration from config.ini."""
    config = ConfigParser()
    if not CONFIG_FILE_PATH.exists():
        return # No config file yet, will use defaults or prompt

    try:
        config.read(CONFIG_FILE_PATH, encoding='utf-8')
        if 'settings' in config:
            app_config["apollo_conf_path"] = config['settings'].get("apollo_conf_path")
            app_config["steamgriddb_api_key"] = config['settings'].get("steamgriddb_api_key")
            # Validate path exists if loaded
            if app_config["apollo_conf_path"] and not Path(app_config["apollo_conf_path"]).exists():
                print(f"Warning: Apollo config path from settings does not exist: {app_config['apollo_conf_path']}")
                # app_config["apollo_conf_path"] = None # Optionally invalidate here or let user fix
    except Exception as e:
        print(f"Error loading config: {e}")
        # Reset to defaults if loading fails critically
        app_config["apollo_conf_path"] = None
        app_config["steamgriddb_api_key"] = None

def save_config():
    """Saves current app_config to config.ini."""
    config = ConfigParser()
    config['settings'] = {}
    if app_config["apollo_conf_path"]:
        config['settings']["apollo_conf_path"] = app_config["apollo_conf_path"]
    if app_config["steamgriddb_api_key"]:
        config['settings']["steamgriddb_api_key"] = app_config["steamgriddb_api_key"]
    
    try:
        with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as configfile:
            config.write(configfile)
        print(f"Configuration saved to {CONFIG_FILE_PATH}")
    except Exception as e:
        messagebox.showerror("Config Save Error", f"Could not save configuration: {e}")

# ────────────────────────────────────────────────────────────────────────────
# SteamGridDB Asset Fetching
# ────────────────────────────────────────────────────────────────────────────

STEAMGRIDDB_API_URL = "https://www.steamgriddb.com/api/v2"

def download_image(url: str, save_path: Path, headers: dict = None):
    """Downloads an image from a URL and saves it."""
    if not requests:
        print("Skipping download: 'requests' library not available.")
        return False
    try:
        # For CDN URLs, we generally don't want to pass the API auth headers.
        # Create a new session or use default headers for CDN downloads.
        cdn_request_headers = {}
        if headers and 'Authorization' in headers and not url.startswith(STEAMGRIDDB_API_URL):
             # If custom headers were provided, but it's a CDN URL, don't use Auth header.
             # We might want to copy other potentially useful headers like User-Agent if set, but keep it simple for now.
             pass # Effectively using default headers for CDN, or only non-Auth headers if any were passed for other reasons
        elif url.startswith(STEAMGRIDDB_API_URL):
            cdn_request_headers = headers # Use provided headers (with Auth) for direct API image links if any

        response = requests.get(url, stream=True, headers=cdn_request_headers, timeout=15)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            shutil.copyfileobj(response.raw, f)
        print(f"Successfully downloaded {save_path.name}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error downloading {url}: {e}")
        return False

def fetch_steamgriddb_assets_for_game(game_name: str, api_key: str, media_game_dir: Path, results_queue, cancel_event) -> dict:
    """
    Fetches specified assets for a game from SteamGridDB.
    Returns a dictionary of Pegasus asset types to local filenames.
    e.g., {"logo": "logo.png", "steam": "steam.png", "banner": "banner.png"}
    """
    if not requests or not api_key:
        if not requests:
            print("Skipping SteamGridDB fetch: 'requests' library not available.")
        if not api_key:
            print("Skipping SteamGridDB fetch: API key not provided to fetch_steamgriddb_assets_for_game.")
        return {}

    # Debug: Print masked API key to verify
    # masked_key = api_key[:4] + "****" + api_key[-4:] if len(api_key) > 8 else "****"
    # print(f"[Debug] Attempting to use SteamGridDB API Key (masked): {masked_key}")

    headers = {"Authorization": f"Bearer {api_key}"}
    fetched_assets_summary = {} # To track what was fetched

    # 1. Search for game ID
    try:
        search_response = requests.get(f"{STEAMGRIDDB_API_URL}/search/autocomplete/{requests.utils.quote(game_name)}", headers=headers, timeout=10)
        search_response.raise_for_status()
        search_data = search_response.json()
        if not search_data.get("success") or not search_data.get("data"):
            print(f"Game not found on SteamGridDB: {game_name}")
            return {}
        game_id = search_data["data"][0]["id"] # Take the first result
    except requests.exceptions.RequestException as e:
        print(f"Error searching for game {game_name} on SteamGridDB: {e}")
        return {}
    except (IndexError, KeyError):
        print(f"No valid game ID found for {game_name} on SteamGridDB.")
        return {}

    asset_map = {
        "logo":   {"endpoint": f"/logos/game/{game_id}",  "filename": "logo.png",   "params": {}},
        "steam":  {"endpoint": f"/grids/game/{game_id}",  "filename": "steam.png",  "params": {"dimensions": "460x215,920x430,600x900,342x482,660x930", "types": "static", "mimes": "image/png"}},
        "marqee": {"endpoint": f"/heroes/game/{game_id}", "filename": "marqee.png", "params": {"types": "static", "mimes": "image/png"}},
        "tile":   {"endpoint": f"/grids/game/{game_id}",  "filename": "tile.png",   "params": {"dimensions": "512x512,1024x1024", "types": "static", "mimes": "image/png"}},
    }

    for asset_type_pegasus, details in asset_map.items():
        if cancel_event.is_set():
            print(f"[Thread] Cancellation detected before fetching {asset_type_pegasus} for {game_name}.")
            return fetched_assets_summary # Return what was fetched so far for this game

        results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"Fetching {asset_type_pegasus}..."})
        
        save_path = media_game_dir / details["filename"]
        if save_path.exists() and save_path.is_file():
            print(f"[Thread] Skipping download for {game_name} - {details['filename']}, already exists.")
            fetched_assets_summary[asset_type_pegasus] = details["filename"]
            results_queue.put({
                "status": "asset_update",
                "game_name": game_name,
                "asset_info": f"{details['filename']} already exists. Skipped."
            })
            continue

        try:
            asset_response = requests.get(
                f"{STEAMGRIDDB_API_URL}{details['endpoint']}", 
                headers=headers, 
                params=details.get("params"), # Use .get() in case "params" is not in all dicts
                timeout=10
            )
            asset_response.raise_for_status()
            asset_data = asset_response.json()

            if asset_data.get("success") and asset_data.get("data"):
                # Prefer assets with more downloads or just take the first one
                # For grids (steam), could filter by dimension or style if API supports easily, for now take first
                asset_url = asset_data["data"][0]["url"]
                if download_image(asset_url, save_path, headers):
                    fetched_assets_summary[asset_type_pegasus] = details["filename"]
                else:
                    results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"No {asset_type_pegasus} found."})
                    print(f"No {asset_type_pegasus} found for {game_name} (ID: {game_id})")
            else:
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"No {asset_type_pegasus} found."})
                print(f"No {asset_type_pegasus} found for {game_name} (ID: {game_id})")

        except requests.exceptions.RequestException as e:
            error_msg = f"Error fetching {asset_type_pegasus} for {game_name}: {e}"
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": error_msg})
            print(error_msg)
        except (IndexError, KeyError):
            error_msg = f"Could not parse {asset_type_pegasus} data for {game_name}."
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": error_msg})
            print(error_msg)
            
    return fetched_assets_summary

# ────────────────────────────────────────────────────────────────────────────
def sanitize(name: str) -> str:
    """Remove filename-hostile characters."""
    name = name.replace(":", " - ")
    return re.sub(r'[<>:"/\\|?*]', "", name)


# ─── read *.conf* as INI ────────────────────────────────────────────────────
def parse_conf(conf_path: Path):
    """
    Return absolute paths to apps.json & sunshine_state.json.
    If not set, defaults are relative to the .conf location.
    """
    raw = conf_path.read_text(encoding="utf-8", errors="ignore")
    cfg = ConfigParser(delimiters=("="))
    cfg.read_string("[root]\n" + raw)

    base = conf_path.parent
    apps_file  = cfg["root"].get("file_apps",  "apps.json")
    state_file = cfg["root"].get("file_state", "sunshine_state.json")
    host_name  = cfg["root"].get("sunshine_name", "Apollo Streaming")

    return (base / apps_file).resolve(), (base / state_file).resolve(), host_name.strip()


def collect_data(apps_json: Path, state_json: Path):
    """Return {game_name: {"uuid": uuid, "app_image": app_image_path}} (skip missing UUID) and host_uuid."""
    with state_json.open(encoding="utf-8") as f:
        host_uuid = json.load(f)["root"]["uniqueid"]

    app_map = {}
    with apps_json.open(encoding="utf-8") as f:
        for app in json.load(f)["apps"]:
            name  = app.get("name")
            uuid  = app.get("uuid")
            app_image = app.get("image-path") # Get app-image
            if name and uuid:            # skip orphan entries
                app_map[name.lstrip()] = {"uuid": uuid, "app_image": app_image}

    return app_map, host_uuid


# ─── output helpers ────────────────────────────────────────────────────────
def ensure_out_dir(out_dir):
    if out_dir.exists():
        if not messagebox.askyesno(
            "Output exists",
            f"Folder '{out_dir}' already exists.\nDelete its contents first?"
        ):
            return
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)


# ─── generators ────────────────────────────────────────────────────────────
def open_directory(path: Path):
    """Opens the given directory in the default file explorer."""
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.call(["open", path])
    else:
        subprocess.call(["xdg-open", path])


def generate_daijishou(app_map, host_uuid, host_name, out_dir):
    for name, game_data in app_map.items():
        uuid = game_data["uuid"]
        (out_dir / f"{sanitize(name)}.art").write_text(
            f"# Daijishou Player Template\n[app_uuid] {uuid}\n", encoding="utf-8"
        )

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
                    f" --es UUID {host_uuid}\n"
                    " --es AppUUID {tags.app_uuid}"
                ),
                "killPackageProcesses": True,
                "killPackageProcessesWarning": True,
                "extra": "",
            }
        ],
    }
    (out_dir / "Artemis.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    messagebox.showinfo("Done", "Daijishō files (.art) created!")
    open_directory(out_dir)


def generate_esde(app_map, host_uuid, host_name, out_dir):
    for name, game_data in app_map.items():
        uuid = game_data["uuid"]
        (out_dir / f"{sanitize(name)}.artes").write_text(uuid, encoding="utf-8")

    (out_dir / "Apollo.uuid").write_text(host_uuid, encoding="utf-8")

    (out_dir / "es_systems.xml").write_text(f"""<systemList>
  <system>
    <name>artemis</name>
    <fullname>{host_name}</fullname>
    <path>%ROMPATH%/artemis</path>
    <extension>.artes</extension>
    <command label="Artemis">%EMULATOR_Artemis% %EXTRA_UUID%=%INJECT%=Apollo.uuid %EXTRA_AppUUID%=%INJECT%=%BASENAME%.artes</command>
    <platform>artemis</platform>
    <theme>artemis</theme>
  </system>
</systemList>""", encoding="utf-8")

    (out_dir / "es_find_rules.xml").write_text("""<ruleList>
  <emulator name="Artemis">
    <rule type="androidpackage">
      <entry>com.limelight.noir/com.limelight.ShortcutTrampoline</entry>
    </rule>
  </emulator>
</ruleList>""", encoding="utf-8")

    messagebox.showinfo("Done", "ES-DE files (.artes) created!")
    open_directory(out_dir)


def _generate_pegasus_metadata_file(app_map, host_uuid, host_name, out_dir, media_base_dir):
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

        metadata_content.append("")
    
    (out_dir / "metadata.pegasus.txt").write_text("\n".join(metadata_content).strip(), encoding="utf-8")
    print("Pegasus metadata file generated.")


# --- Progress Dialog and Threading --- 
def show_progress_dialog(root, cancel_event, total_games):
    dialog = Toplevel(root)
    dialog.title("Fetching Assets...")
    dialog.geometry("400x150")
    dialog.transient(root)
    dialog.grab_set()
    dialog.protocol("WM_DELETE_WINDOW", lambda: None) # Disable X button

    lbl_overall_text = Label(dialog, text="Overall Progress:")
    lbl_overall_text.pack(pady=(10,0))
    lbl_game_status = Label(dialog, text=f"Preparing... (0 of {total_games} games)")
    lbl_game_status.pack()

    lbl_current_asset_text = Label(dialog, text="Current Action:")
    lbl_current_asset_text.pack(pady=(10,0))
    lbl_asset_status = Label(dialog, text="Initializing...")
    lbl_asset_status.pack()

    def do_cancel():
        print("[Dialog] Cancel button clicked.")
        cancel_event.set()
        # Dialog will be destroyed by check_queue once "cancelled" status is processed
        # Or if thread ends abruptly and cancel_event is set.

    btn_cancel = Button(dialog, text="Cancel", command=do_cancel)
    btn_cancel.pack(pady=10, side="bottom")

    root.update_idletasks()
    return dialog, lbl_game_status, lbl_asset_status

def asset_fetching_worker(app_map, steamgriddb_api_key, out_dir_media_base, results_queue, cancel_event):
    """Worker function to fetch assets for all games."""
    total_games = len(app_map)
    processed_games = 0
    errors_occurred = False
    print(f"[Thread] Starting asset fetching for {total_games} games.")

    for name, game_data in app_map.items():
        if cancel_event.is_set():
            print("[Thread] Cancellation detected before processing game:", name)
            break # Exit the loop over games
        
        processed_games += 1
        results_queue.put({
            "status": "game_update", 
            "game_name": name, 
            "current_game_num": processed_games, 
            "total_games": total_games
        })

        uuid = game_data["uuid"]
        current_game_media_dir = out_dir_media_base / uuid
        current_game_media_dir.mkdir(parents=True, exist_ok=True)

        try:
            fetched_assets_info = fetch_steamgriddb_assets_for_game(name, steamgriddb_api_key, current_game_media_dir, results_queue, cancel_event)
            if not fetched_assets_info and not any(current_game_media_dir.iterdir()):
                results_queue.put({"status": "asset_update", "game_name": name, "asset_info": "No assets found/downloaded."})
                print(f"[Thread] No assets were fetched for {name}.")
        except Exception as e:
            error_msg = f"[Thread] Error processing assets for {name}: {e}"
            results_queue.put({"status": "asset_update", "game_name": name, "asset_info": error_msg })
            print(error_msg)
            errors_occurred = True
        
        if cancel_event.is_set(): # Check again after a game is processed
            print("[Thread] Cancellation detected after processing game:", name)
            break

    if cancel_event.is_set():
        results_queue.put({"status": "cancelled"})
        print("[Thread] Asset fetching was cancelled.")
    else:
        results_queue.put({"status": "complete", "errors_occurred": errors_occurred})
        print("[Thread] Asset fetching complete (not cancelled).")


def generate_pegasus(root, app_map, host_uuid, host_name, out_dir, config_path, use_steamgriddb, steamgriddb_api_key):
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
                dest_path = media_game_dir / "boxFront.png"
                try:
                    shutil.copy2(app_image_path, dest_path)
                except Exception as e:
                    print(f"Skipping local image copy for {name} (boxFront.png) due to error: {e}")
            else:
                print(f"Skipping local image for {name} (boxFront.png): {app_image_path_str} not found or not a file.")

    _generate_pegasus_metadata_file(app_map, host_uuid, host_name, out_dir, media_base_dir)

    # --- Part 2: Fetch SteamGridDB assets (threaded if use_steamgriddb) ---
    errors_during_fetch = False
    was_cancelled = False

    if use_steamgriddb and steamgriddb_api_key and requests:
        cancel_event = threading.Event()
        progress_dialog, lbl_game_status, lbl_asset_status = show_progress_dialog(root, cancel_event, len(app_map))
        results_q = queue.Queue()
        
        fetch_thread = threading.Thread(target=asset_fetching_worker, 
                                        args=(app_map, steamgriddb_api_key, media_base_dir, results_q, cancel_event))
        fetch_thread.start()

        # Keep track of whether the final steps have been run to avoid multiple calls
        final_steps_executed = False

        def execute_final_steps():
            nonlocal final_steps_executed
            if final_steps_executed:
                return
            final_steps_executed = True

            if progress_dialog.winfo_exists():
                progress_dialog.destroy()
            
            # _generate_pegasus_metadata_file(app_map, host_uuid, host_name, out_dir, media_base_dir)

            final_message = f"Pegasus Frontend files created in '{out_dir.name}'!"
            if was_cancelled:
                final_message = f"Asset fetching was cancelled by the user.\nPegasus metadata file generated (may be incomplete for newly fetched assets)."
            elif errors_during_fetch:
                final_message += "\n\nNote: Some errors occurred during SteamGridDB asset fetching. Check the console for details."
            messagebox.showinfo("Done", final_message)
            open_directory(out_dir)
            print("All Pegasus generation steps completed.")

        def check_queue():
            nonlocal errors_during_fetch, was_cancelled
            try:
                message = results_q.get_nowait()
                if message["status"] == "game_update":
                    lbl_game_status.config(text=f"Game {message['current_game_num']} of {message['total_games']}: {message['game_name']}")
                    lbl_asset_status.config(text="Preparing to fetch assets...")
                elif message["status"] == "asset_update":
                    asset_info_str = str(message.get("asset_info", ""))
                    max_len = 50
                    display_info = (asset_info_str[:max_len] + '...') if len(asset_info_str) > max_len else asset_info_str
                    lbl_asset_status.config(text=display_info)
                elif message["status"] == "complete":
                    errors_during_fetch = message.get("errors_occurred", False)
                    print("[Queue] Received 'complete' status.")
                    execute_final_steps()
                elif message["status"] == "cancelled":
                    was_cancelled = True
                    print("[Queue] Received 'cancelled' status.")
                    execute_final_steps()

            except queue.Empty:
                pass 
            finally:
                # If final steps haven't run yet, check if we should continue polling
                if not final_steps_executed:
                    if fetch_thread.is_alive() or not results_q.empty():
                        root.after(100, check_queue)
                    else: # Thread is dead, queue is empty, but 'complete' or 'cancelled' not received.
                          # This could happen if thread dies unexpectedly. Ensure final steps run.
                        print("[Queue] Thread dead and queue empty, but no final signal. Forcing final steps.")
                        execute_final_steps()
        
        root.after(100, check_queue) # Start polling the queue

    else: # Not using SteamGridDB or prerequisites missing
        print("Skipping SteamGridDB asset fetching. Generating metadata directly.")
        # _generate_pegasus_metadata_file(app_map, host_uuid, host_name, out_dir, media_base_dir)
        messagebox.showinfo("Done", f"Pegasus Frontend files created in '{out_dir.name}'! (No assets fetched from SteamGridDB)")
        open_directory(out_dir)


# ─── GUI ────────────────────────────────────────────────────────────────────
def choose_and_run(root, mode: str, api_key_label_widget=None, apollo_conf_label_widget=None):
    apollo_conf_path_str = app_config.get("apollo_conf_path")
    config_file_path_obj = None # Will hold Path object if valid

    # 1. Check existing configured path
    if apollo_conf_path_str:
        temp_path = Path(apollo_conf_path_str)
        if temp_path.exists() and temp_path.is_file():
            config_file_path_obj = temp_path
            print(f"Using configured Apollo config path: {config_file_path_obj}")
        else:
            messagebox.showwarning(
                "Invalid Apollo Config Path",
                f"The previously configured Apollo config path is invalid or the file does not exist: {apollo_conf_path_str}\n\nPlease select a valid sunshine.conf file."
            )
            # Fall through to prompt for a new path
    else:
        # No path configured yet
        messagebox.showinfo(
            "Apollo Config Path Not Set",
            "The Apollo config (sunshine.conf) path is not yet set.\n\nPlease select your Apollo (sunshine.conf) file to proceed."
        )
        # Fall through to prompt for a new path

    # 2. Prompt for path if not valid or not set
    if not config_file_path_obj:
        initial_dir_prompt = SCRIPT_DIR
        # Try to use parent of old path for initialdir if it existed
        if apollo_conf_path_str and Path(apollo_conf_path_str).parent.exists():
            initial_dir_prompt = Path(apollo_conf_path_str).parent
        
        new_path_str = filedialog.askopenfilename(
            title="Select Apollo config file (sunshine.conf)",
            filetypes=[("Apollo conf", "*.conf")],
            initialdir=str(initial_dir_prompt)
        )

        if new_path_str:
            config_file_path_obj = Path(new_path_str).resolve()
            app_config["apollo_conf_path"] = str(config_file_path_obj)
            save_config()
            if apollo_conf_label_widget:
                update_apollo_path_label(apollo_conf_label_widget) # Update the main UI label
            messagebox.showinfo("Path Saved", f"Apollo config path set to: {app_config['apollo_conf_path']}")
        else:
            messagebox.showerror("Operation Cancelled", "Apollo config file selection was cancelled or is missing. Cannot proceed with export.")
            return

    # At this point, config_file_path_obj should be a valid Path object
    if not config_file_path_obj or not config_file_path_obj.exists():
        # This case should ideally be caught above, but as a final safeguard
        messagebox.showerror("Critical Error", "A valid Apollo config file could not be secured. Aborting.")
        return

    # Proceed with the validated config_file_path_obj
    apps_json, state_json, host_name = parse_conf(config_file_path_obj)
    app_map, host_uuid    = collect_data(apps_json, state_json)
    if not app_map:
        messagebox.showerror("No games", "No apps with UUID found in apps.json")
        return

    out_dir = BASE_DIR / mode / host_name
    ensure_out_dir(out_dir) # Call ensure_out_dir before any generation logic

    use_steamgriddb = False

    if mode == "Pegasus":
        if requests: # Only ask if requests library is available
            if messagebox.askyesno("Download Game Assets?", 
                                   "Do you want to attempt to download game assets (logos, banners, etc.) from SteamGridDB for Pegasus?\n\nThis requires a configured SteamGridDB API key."):
                # User wants to try fetching assets
                if app_config.get("steamgriddb_api_key"):
                    use_steamgriddb = True
                    print("SteamGridDB asset fetching enabled with configured API key.")
                else: # API key is missing, but user wants to fetch assets
                    messagebox.showwarning("SteamGridDB API Key Missing",
                                           "SteamGridDB API key is not configured. Please set it via the dialog that will now appear to enable asset fetching.")
                    print("SteamGridDB API key not configured. Prompting user to set it.")
                    if api_key_label_widget: # Ensure the label widget was passed
                        prompt_and_save_api_key(api_key_label_widget)
                        # After attempting to save, check again if the key exists
                        if app_config.get("steamgriddb_api_key"):
                            use_steamgriddb = True
                            print("SteamGridDB asset fetching enabled with newly configured API key.")
                        else:
                            print("API Key still not set after prompt. SteamGridDB fetching disabled for this run.")
                    else:
                         print("Could not prompt for API key as UI label was not available. SteamGridDB fetching disabled.")
            else:
                # User chose not to download assets from SteamGridDB
                print("User opted out of SteamGridDB asset fetching for this run.")
        else:
            print("Skipping SteamGridDB prompt: 'requests' library not installed.")
            
        generate_pegasus(root, app_map, host_uuid, host_name, out_dir, config_file_path_obj, use_steamgriddb, app_config.get("steamgriddb_api_key"))
    elif mode == "ES-DE":
        generate_esde(app_map, host_uuid, host_name, out_dir)
    else: # daijishou
        generate_daijishou(app_map, host_uuid, host_name, out_dir)


def main():
    root = Tk(); root.title("Apollo Launcher Export")
    Label(root, text="Generate launcher files for:").pack(pady=10)

    # Buttons for generating files will now pass the api key label to choose_and_run for Pegasus
    # Other buttons don't need it.
    # To do this, we need lbl_api_key_val to be defined before these buttons if we use it directly.
    # Let's define the config UI elements first, then the action buttons.

    # --- Configuration Management UI ---
    config_frame = Frame(root, pady=10)
    config_frame.pack(fill="x", padx=10)

    # Apollo Config Path Management
    apollo_path_frame = Frame(config_frame)
    apollo_path_frame.pack(fill="x")
    lbl_apollo_conf_text = Label(apollo_path_frame, text="Apollo Config (.conf): ")
    lbl_apollo_conf_text.pack(side="left")
    lbl_apollo_conf_path_val = Label(apollo_path_frame, text="Not Set", fg="blue", width=30, anchor="w")
    lbl_apollo_conf_path_val.pack(side="left", expand=True, fill="x")
    btn_set_apollo_path = Button(apollo_path_frame, text="Set/Change", 
                                 command=lambda: prompt_and_save_apollo_conf_path(lbl_apollo_conf_path_val))
    btn_set_apollo_path.pack(side="left")

    # SteamGridDB API Key Management
    api_key_frame = Frame(config_frame)
    api_key_frame.pack(fill="x", pady=5)
    lbl_api_key_text = Label(api_key_frame, text="SteamGridDB API Key: ")
    lbl_api_key_text.pack(side="left")
    lbl_api_key_val = Label(api_key_frame, text="Not Set", fg="blue", width=30, anchor="w")
    lbl_api_key_val.pack(side="left", expand=True, fill="x")
    btn_set_api_key = Button(api_key_frame, text="Set/Change", 
                             command=lambda: prompt_and_save_api_key(lbl_api_key_val))
    btn_set_api_key.pack(side="left")

    # --- Action Buttons ---
    Button(root, text="Pegasus", width=28,
           command=lambda: choose_and_run(root, "Pegasus", lbl_api_key_val, lbl_apollo_conf_path_val)).pack(pady=4) # Pass root & labels
    Button(root, text="ES-DE",   width=28,
           command=lambda: choose_and_run(root, "ES-DE", api_key_label_widget=None, apollo_conf_label_widget=lbl_apollo_conf_path_val)).pack(pady=4) # Pass root & apollo label
    Button(root, text="Daijishō", width=28,
           command=lambda: choose_and_run(root, "Daijishō", api_key_label_widget=None, apollo_conf_label_widget=lbl_apollo_conf_path_val)).pack(pady=4) # Pass root & apollo label

    # Load initial config and update UI
    load_config() # Load existing config
    update_apollo_path_label(lbl_apollo_conf_path_val)
    update_api_key_label(lbl_api_key_val)

    root.mainloop()


def prompt_and_save_apollo_conf_path(label_widget):
    """Prompts user for Apollo config path and saves it."""
    initial_dir = SCRIPT_DIR # Or derive from existing app_config["apollo_conf_path"]
    if app_config.get("apollo_conf_path") and Path(app_config["apollo_conf_path"]).parent.exists():
        initial_dir = Path(app_config["apollo_conf_path"]).parent

    new_path = filedialog.askopenfilename(
        title="Select Apollo config file (sunshine.conf)", 
        filetypes=[("Apollo conf", "*.conf")],
        initialdir=str(initial_dir)
    )
    if new_path:
        app_config["apollo_conf_path"] = str(Path(new_path).resolve())
        save_config()
        update_apollo_path_label(label_widget)
        messagebox.showinfo("Path Saved", f"Apollo config path set to: {app_config['apollo_conf_path']}")
    else:
        # User cancelled, update label if path was previously set but now cleared somehow (not typical here)
        update_apollo_path_label(label_widget)

def prompt_and_save_api_key(label_widget):
    """Prompts user for SteamGridDB API key and saves it."""
    current_key = app_config.get("steamgriddb_api_key", "")
    new_key = simpledialog.askstring("SteamGridDB API Key", 
                                     "Enter your SteamGridDB API Key:",
                                     initialvalue=current_key)
    if new_key is not None: # User clicked OK (new_key can be empty string if they clear it)
        app_config["steamgriddb_api_key"] = new_key.strip()
        save_config()
        update_api_key_label(label_widget)
        if new_key.strip():
            messagebox.showinfo("API Key Saved", "SteamGridDB API Key has been updated.")
        else:
            messagebox.showinfo("API Key Cleared", "SteamGridDB API Key has been cleared.")
    # Else: User clicked Cancel, do nothing to the stored key or label

def update_apollo_path_label(label_widget):
    """Updates the Apollo config path display label."""
    path_to_display = "Not Set"
    if app_config.get("apollo_conf_path"):
        # Display a shortened version for readability, e.g., last 2 components
        p = Path(app_config["apollo_conf_path"])
        path_to_display = f".../{p.parent.name}/{p.name}" if len(p.parts) > 2 else str(p)
    label_widget.config(text=path_to_display)

def update_api_key_label(label_widget):
    """Updates the API key display label (masked)."""
    key_to_display = "Not Set"
    if app_config.get("steamgriddb_api_key"):
        key = app_config["steamgriddb_api_key"]
        if len(key) > 7:
            key_to_display = f"{key[:4]}...{key[-3:]}"
        elif key: # Key is short but not empty
             key_to_display = "*****"
        else: # Key is an empty string
            key_to_display = "Set (but empty)"

    label_widget.config(text=key_to_display)

if __name__ == "__main__":
    main()
