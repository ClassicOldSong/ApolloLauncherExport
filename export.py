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
import time # For epoch to datetime conversion
from datetime import datetime, timezone
import difflib # For fuzzy string matching
import webbrowser # Added for opening URLs
try:
    import requests # For SteamGridDB integration and IGDB (implicitly)
except ImportError:
    messagebox.showwarning("Missing Dependency", "The 'requests' library is not installed. SteamGridDB and IGDB functionality will be disabled. Please install it using: pip install requests")
    requests = None

try:
    from igdb.wrapper import IGDBWrapper
    if not requests:
        raise ImportError("IGDBWrapper also needs 'requests' library.")
except ImportError:
    # Don't show messagebox here, we'll handle IGDB setup more dynamically.
    # User will be prompted if they try to use IGDB features without it.
    print("Warning: 'igdb-api-python' library not installed or 'requests' is missing. IGDB functionality will require setup.")
    IGDBWrapper = None

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
    "steamgriddb_api_key": None,
    "igdb_client_id": None,
    "igdb_app_access_token": None
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
            app_config["igdb_client_id"] = config['settings'].get("igdb_client_id")
            app_config["igdb_app_access_token"] = config['settings'].get("igdb_app_access_token")
            # Validate path exists if loaded
            if app_config["apollo_conf_path"] and not Path(app_config["apollo_conf_path"]).exists():
                print(f"Warning: Apollo config path from settings does not exist: {app_config['apollo_conf_path']}")
                # app_config["apollo_conf_path"] = None # Optionally invalidate here or let user fix
    except Exception as e:
        print(f"Error loading config: {e}")
        # Reset to defaults if loading fails critically
        app_config["apollo_conf_path"] = None
        app_config["steamgriddb_api_key"] = None
        app_config["igdb_client_id"] = None
        app_config["igdb_app_access_token"] = None

def save_config():
    """Saves current app_config to config.ini."""
    config = ConfigParser()
    config['settings'] = {}
    if app_config["apollo_conf_path"]:
        config['settings']["apollo_conf_path"] = app_config["apollo_conf_path"]
    if app_config["steamgriddb_api_key"]:
        config['settings']["steamgriddb_api_key"] = app_config["steamgriddb_api_key"]
    if app_config["igdb_client_id"]:
        config['settings']["igdb_client_id"] = app_config["igdb_client_id"]
    if app_config["igdb_app_access_token"]:
        config['settings']["igdb_app_access_token"] = app_config["igdb_app_access_token"]
    
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
IGDB_API_URL = "https://api.igdb.com/v4" # Base URL for IGDB API v4

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
# IGDB Metadata Fetching
# ────────────────────────────────────────────────────────────────────────────
def format_igdb_image_url(image_id: str, size_suffix: str = "t_cover_big") -> str:
    """Formats an IGDB image URL."""
    if not image_id:
        return ""
    return f"https://images.igdb.com/igdb/image/upload/{size_suffix}/{image_id}.jpg"

def fetch_igdb_metadata_for_game(game_name: str, client_id: str, app_access_token: str, media_game_dir: Path, 
                               results_queue, cancel_event, steamgriddb_fetched_assets: dict) -> dict | None:
    """
    Fetches detailed metadata for a game from IGDB.com.
    Downloads cover, screenshot, and artwork images, prioritizing SteamGridDB assets.
    Saves metadata to igdb_metadata.json in the game's media directory.
    Returns a dictionary of textual metadata for Pegasus, or None on failure.
    """
    if not IGDBWrapper or not requests:
        print("Skipping IGDB fetch: 'igdb-api-python' or 'requests' library not available.")
        return None
    if not client_id or not app_access_token:
        print("Skipping IGDB fetch: Client ID or App Access Token not provided.")
        return None

    results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"Fetching IGDB metadata for {game_name}..."})
    
    wrapper = IGDBWrapper(client_id, app_access_token)
    pegasus_metadata = {}
    SIMILARITY_THRESHOLD = 0.7 # Minimum similarity ratio for a game name to be considered a match

    try:
        # Expanded query for more details and images, limit increased
        api_query = (
            f'search "{game_name}"; '
            f"fields name, summary, storyline, total_rating, first_release_date, "
            f"genres.name, cover.image_id, artworks.image_id, screenshots.image_id, "
            f"involved_companies.company.name, involved_companies.developer, involved_companies.publisher, "
            f"game_modes.name, player_perspectives.name; "
            f"limit 5;" # Fetch up to 5 results
        )
        
        json_byte_array_result = wrapper.api_request('games', api_query)
        games_data = json.loads(json_byte_array_result.decode('utf-8'))

        if not games_data:
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"No IGDB metadata found for {game_name}."})
            print(f"No IGDB metadata found for {game_name}.")
            return None

        # --- Select the best match from the results ---
        best_match_game = None
        highest_similarity_ratio = 0.0

        for igdb_game in games_data:
            if not igdb_game.get("name"):
                continue
            
            current_igdb_name = igdb_game["name"]
            
            # 1. Check for exact case-insensitive match
            if current_igdb_name.lower() == game_name.lower():
                best_match_game = igdb_game
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"IGDB: Exact match found - {current_igdb_name}"})
                break # Found exact match, no need to check further
            
            # 2. Calculate similarity for non-exact matches
            similarity = difflib.SequenceMatcher(None, game_name.lower(), current_igdb_name.lower()).ratio()
            if similarity > highest_similarity_ratio:
                highest_similarity_ratio = similarity
                best_match_game = igdb_game
        
        if not best_match_game:
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"IGDB: No suitable match found after checking {len(games_data)} results."})
            print(f"No suitable IGDB match found for {game_name} from {len(games_data)} results.")
            return None
        
        if highest_similarity_ratio < SIMILARITY_THRESHOLD and best_match_game["name"].lower() != game_name.lower():
            # This case applies if we didn't get an exact match and the best similarity is below threshold
            results_queue.put({"status": "asset_update", "game_name": game_name, 
                               "asset_info": f"IGDB: Best match '{best_match_game['name']}' ({highest_similarity_ratio:.2f}) below threshold for {game_name}."})
            print(f"IGDB: Best match for {game_name} was '{best_match_game['name']}' with similarity {highest_similarity_ratio:.2f}, which is below threshold {SIMILARITY_THRESHOLD}. Skipping.")
            return None
        
        game_info = best_match_game
        results_queue.put({"status": "asset_update", "game_name": game_name, 
                           "asset_info": f"IGDB: Selected match '{game_info['name']}' (Similarity: {highest_similarity_ratio if highest_similarity_ratio > 0 else 'Exact'})."})

        # --- Populate Textual Metadata for Pegasus ---
        if game_info.get("name"):
            pegasus_metadata["game"] = game_info["name"] # Pegasus uses 'game' for title

        if game_info.get("summary"): # IGDB summary for Pegasus summary (shorter)
            pegasus_metadata["summary"] = game_info["summary"]
        if game_info.get("storyline"): # IGDB storyline for Pegasus description (longer)
            pegasus_metadata["description"] = game_info["storyline"]
        
        if game_info.get("total_rating") is not None:
            pegasus_metadata["rating"] = f"{int(round(game_info['total_rating']))}%"

        if game_info.get("first_release_date"):
            try:
                # IGDB returns epoch timestamp
                release_timestamp = int(game_info["first_release_date"])
                # Use timezone-aware datetime object as per deprecation warning
                pegasus_metadata["release"] = datetime.fromtimestamp(release_timestamp, timezone.utc).strftime('%Y-%m-%d')
            except ValueError:
                print(f"Could not parse release date for {game_name}")
        
        if game_info.get("genres"):
            pegasus_metadata["genre"] = ", ".join([genre["name"] for genre in game_info["genres"] if genre.get("name")])

        developers = []
        publishers = []
        if game_info.get("involved_companies"):
            for company_info in game_info["involved_companies"]:
                comp_name = company_info.get("company", {}).get("name")
                if not comp_name:
                    continue
                if company_info.get("developer"):
                    developers.append(comp_name)
                if company_info.get("publisher"):
                    publishers.append(comp_name)
        if developers:
            pegasus_metadata["developer"] = ", ".join(developers)
        if publishers:
            pegasus_metadata["publisher"] = ", ".join(publishers)

        tags = []
        if game_info.get("game_modes"):
            tags.extend([mode["name"] for mode in game_info["game_modes"] if mode.get("name")])
        if game_info.get("player_perspectives"):
            tags.extend([pp["name"] for pp in game_info["player_perspectives"] if pp.get("name")])
        if tags:
            pegasus_metadata["tags"] = ", ".join(list(set(tags))) # Use set to avoid duplicates then join

        # --- Download Images (prioritizing SteamGridDB) ---
        media_game_dir.mkdir(parents=True, exist_ok=True)
        downloaded_any_igdb_image = False

        # 1. Cover -> boxFront.jpg (from IGDB)
        # Only download if a primary SteamGridDB box art (like 'steam.png' or 'boxFront.png') doesn't already exist.
        # Common SteamGridDB keys that might serve as box front: "steam", "boxFront" (less common in current script but good to consider)
        # We also check if SteamGridDB might have provided an explicit "boxFront.png"
        has_steamgriddb_boxfront = False
        steamgriddb_boxfront_keys = ["steam", "boxFront"] # Add more if SteamGridDB provides other relevant keys
        for sgdb_key in steamgriddb_boxfront_keys:
            if sgdb_key in steamgriddb_fetched_assets and (media_game_dir / steamgriddb_fetched_assets[sgdb_key]).exists():
                has_steamgriddb_boxfront = True
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"IGDB: Skipping boxFront.jpg download, {steamgriddb_fetched_assets[sgdb_key]} from SteamGridDB exists."})
                break
        
        if not has_steamgriddb_boxfront and game_info.get("cover") and game_info["cover"].get("image_id"):
            cover_url = format_igdb_image_url(game_info["cover"]["image_id"], "t_cover_big")
            target_cover_path = media_game_dir / "boxFront.jpg"
            if target_cover_path.exists():
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "boxFront.jpg already exists. Skipped IGDB download."})
            elif download_image(cover_url, target_cover_path):
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "boxFront.jpg (IGDB) downloaded."})
                downloaded_any_igdb_image = True
            else:
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "Failed to download boxFront.jpg (IGDB)."})
        
        # 2. First Screenshot -> screenshot.jpg (from IGDB)
        if game_info.get("screenshots") and game_info["screenshots"][0].get("image_id"):
            ss_url = format_igdb_image_url(game_info["screenshots"][0]["image_id"], "t_screenshot_big") # or t_720p
            target_ss_path = media_game_dir / "screenshot.jpg"
            if target_ss_path.exists():
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "screenshot.jpg already exists. Skipped IGDB download."})
            elif download_image(ss_url, target_ss_path):
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "screenshot.jpg (IGDB) downloaded."})
                downloaded_any_igdb_image = True
            else:
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "Failed to download screenshot.jpg (IGDB)."})

        # 3. First Artwork (if not a screenshot, though IGDB artworks are usually distinct) -> background.jpg (from IGDB)
        if game_info.get("artworks") and game_info["artworks"][0].get("image_id"):
            art_url = format_igdb_image_url(game_info["artworks"][0]["image_id"], "t_1080p") # or t_720p
            target_art_path = media_game_dir / "background.jpg"
            if target_art_path.exists():
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "background.jpg already exists. Skipped IGDB download."})
            elif download_image(art_url, target_art_path):
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "background.jpg (IGDB) downloaded."})
                downloaded_any_igdb_image = True
            else:
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "Failed to download background.jpg (IGDB)."})
        
        if not pegasus_metadata and not downloaded_any_igdb_image: # Nothing useful fetched
             results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"No useful metadata or images from IGDB for {game_name}."})
             return None

        results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"IGDB metadata processed for {game_name}."})
        return pegasus_metadata

    except requests.exceptions.RequestException as e:
        error_msg = f"IGDB API request error for {game_name}: {e}"
        results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": error_msg})
        print(error_msg)
        return None
    except json.JSONDecodeError as e:
        error_msg = f"Error decoding IGDB JSON response for {game_name}: {e}"
        results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": error_msg})
        print(error_msg)
        return None
    except (IndexError, KeyError) as e:
        error_msg = f"Could not parse IGDB data for {game_name} (IndexError/KeyError): {e}"
        results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": error_msg})
        print(error_msg)
        return None
    except Exception as e: # Catch any other unexpected errors
        error_msg = f"An unexpected error occurred fetching IGDB data for {game_name}: {e}"
        results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": error_msg})
        print(error_msg)
        return None

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

def asset_fetching_worker(app_map, steamgriddb_api_key, out_dir_media_base, results_queue, cancel_event, 
                          fetch_igdb_enabled, igdb_client_id, igdb_app_access_token):
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

            if cancel_event.is_set():
                print(f"[Thread] Cancellation detected after SteamGridDB fetch for {name}.")
                break

            if fetch_igdb_enabled:
                if igdb_client_id and igdb_app_access_token and IGDBWrapper:
                    igdb_text_data = fetch_igdb_metadata_for_game(name, igdb_client_id, igdb_app_access_token, 
                                                 current_game_media_dir, results_queue, cancel_event, fetched_assets_info)
                    if igdb_text_data: # If data was actually fetched
                        results_queue.put({
                            "status": "igdb_text_data_ready",
                            "game_uuid": uuid, # Send UUID for reliable mapping
                            "game_name": name, # Keep for display/logging if needed
                            "data": igdb_text_data
                        })
                else:
                    results_queue.put({"status": "asset_update", "game_name": name, "asset_info": "Skipping IGDB: Not configured or library missing."})
                    print(f"[Thread] Skipping IGDB metadata for {name}: Not configured or library missing.")

        except Exception as e:
            error_msg = f"[Thread] Error processing assets/metadata for {name}: {e}"
            results_queue.put({"status": "asset_update", "game_name": name, "asset_info": error_msg})
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


def generate_pegasus(root, app_map, host_uuid, host_name, out_dir, config_path, use_steamgriddb, steamgriddb_api_key, 
                     fetch_igdb_enabled, igdb_client_id, igdb_app_access_token):
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
        
        # Pass the explicit IGDB parameters to the worker
        fetch_thread = threading.Thread(target=asset_fetching_worker, 
                                        args=(app_map, 
                                              steamgriddb_api_key if use_steamgriddb else None, # Pass key only if use_steamgriddb
                                              media_base_dir, 
                                              results_q, 
                                              cancel_event,
                                              fetch_igdb_enabled, # Use the parameter passed to generate_pegasus
                                              igdb_client_id,    # Use the parameter
                                              igdb_app_access_token # Use the parameter
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
            nonlocal errors_during_fetch, was_cancelled
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
                elif message["status"] == "complete":
                    errors_during_fetch = message.get("errors_occurred", False)
                    execute_final_steps()
                elif message["status"] == "cancelled":
                    was_cancelled = True
                    execute_final_steps()
            except queue.Empty:
                pass 
            finally:
                if not final_steps_executed:
                    if fetch_thread.is_alive() or not results_q.empty():
                        root.after(100, check_queue)
                    else: 
                        print("[Queue] Thread dead, queue empty, no final signal. Forcing final steps.")
                        execute_final_steps()
        
        root.after(100, check_queue)
    else: 
        print("Skipping online asset/metadata fetching (SteamGridDB/IGDB not enabled or prerequisites missing).")
        _generate_pegasus_metadata_file(app_map, host_uuid, host_name, out_dir, igdb_metadata_cache) # Final metadata with empty cache
        messagebox.showinfo("Done", f"Pegasus Frontend files created in '{out_dir.name}'! (No assets/metadata fetched online)")
        open_directory(out_dir)


# ─── GUI ────────────────────────────────────────────────────────────────────
def choose_and_run(root, mode: str, api_key_label_widget=None, apollo_conf_label_widget=None, igdb_label_widget=None):
    apollo_conf_path_str = app_config.get("apollo_conf_path")
    config_file_path_obj = None

    # 1. Validate/Get Apollo Config Path
    if apollo_conf_path_str:
        temp_path = Path(apollo_conf_path_str)
        if temp_path.exists() and temp_path.is_file():
            config_file_path_obj = temp_path
        else:
            messagebox.showwarning("Invalid Apollo Config", f"Saved path {apollo_conf_path_str} is invalid. Please select a new one.")
    
    if not config_file_path_obj:
        if not apollo_conf_label_widget: # Should not happen if UI is set up correctly
            messagebox.showerror("Error", "Apollo config UI element missing.")
            return
        prompt_and_save_apollo_conf_path(apollo_conf_label_widget) # This updates app_config and UI
        apollo_conf_path_str = app_config.get("apollo_conf_path")
        if apollo_conf_path_str and Path(apollo_conf_path_str).exists():
            config_file_path_obj = Path(apollo_conf_path_str)
        else:
            messagebox.showerror("Operation Cancelled", "Apollo config file not set. Cannot proceed.")
            return

    # Proceed with the validated config_file_path_obj
    apps_json, state_json, host_name = parse_conf(config_file_path_obj)
    app_map, host_uuid = collect_data(apps_json, state_json)
    if not app_map:
        messagebox.showerror("No games", "No apps with UUID found in apps.json")
        return

    out_dir = BASE_DIR / mode / host_name
    ensure_out_dir(out_dir) # Call ensure_out_dir before any generation logic

    use_steamgriddb = False
    current_steamgriddb_api_key = app_config.get("steamgriddb_api_key")

    fetch_igdb_enabled_for_run = False
    current_igdb_client_id = app_config.get("igdb_client_id")
    current_igdb_app_access_token = app_config.get("igdb_app_access_token")

    if mode == "Pegasus":
        if not requests:
            messagebox.showwarning("Missing Library", "The 'requests' library is not installed. SteamGridDB and IGDB features are disabled.")
        else:
            # SteamGridDB Setup
            if messagebox.askyesno("Download Game Assets?", 
                                   "Do you want to attempt to download game assets (logos, etc.) from SteamGridDB?"):
                if current_steamgriddb_api_key and check_steamgriddb_key_validity(current_steamgriddb_api_key):
                    use_steamgriddb = True
                    print("Using existing valid SteamGridDB API key.")
                else:
                    if current_steamgriddb_api_key: # Key exists but is invalid
                        messagebox.showwarning("SteamGridDB API Key Invalid", 
                                               "Your configured SteamGridDB API key is invalid. Please set a new one.")
                    else: # Key not set
                        messagebox.showinfo("SteamGridDB API Key Needed", 
                                            "SteamGridDB API key is not configured. Please set it to enable asset fetching.")
                    
                    if api_key_label_widget:
                        prompt_and_save_api_key(root, api_key_label_widget) # This prompts, validates, and saves
                        current_steamgriddb_api_key = app_config.get("steamgriddb_api_key")
                        if current_steamgriddb_api_key and check_steamgriddb_key_validity(current_steamgriddb_api_key):
                            use_steamgriddb = True
                            print("Using newly set and validated SteamGridDB API key.")
                        else:
                            print("SteamGridDB API key not set or invalid after prompt. Fetching disabled.")
                    else:
                        print("SteamGridDB UI element missing. Cannot prompt for key.")
            else:
                print("User opted out of SteamGridDB asset fetching.")

            # IGDB Setup (only if requests is available)
            if IGDBWrapper:
                if messagebox.askyesno("Fetch IGDB Metadata?", 
                                       "Do you also want to fetch game metadata (summary, genre, etc.) from IGDB.com?"):
                    valid_igdb_creds = False
                    if current_igdb_client_id and current_igdb_app_access_token:
                        if check_igdb_token_validity(current_igdb_client_id, current_igdb_app_access_token):
                            fetch_igdb_enabled_for_run = True
                            valid_igdb_creds = True
                            print("Using existing valid IGDB credentials.")
                        else:
                            messagebox.showwarning("IGDB Credentials Invalid", 
                                                   "Your configured IGDB Client ID or App Access Token is invalid. Please set them again.")
                    else:
                        messagebox.showinfo("IGDB Credentials Needed", 
                                            "IGDB Client ID and/or App Access Token are not configured. Please set them to enable metadata fetching.")
                    
                    if not valid_igdb_creds and igdb_label_widget:
                        prompt_and_set_igdb_credentials(root, igdb_label_widget) # Prompts, fetches token, validates, saves
                        current_igdb_client_id = app_config.get("igdb_client_id")
                        current_igdb_app_access_token = app_config.get("igdb_app_access_token")
                        if current_igdb_client_id and current_igdb_app_access_token and \
                           check_igdb_token_validity(current_igdb_client_id, current_igdb_app_access_token):
                            fetch_igdb_enabled_for_run = True
                            print("Using newly set and validated IGDB credentials.")
                        else:
                            print("IGDB credentials not set or invalid after prompt. Fetching disabled.")
                    elif not valid_igdb_creds:
                        print("IGDB UI element missing or initial creds invalid and no UI to prompt. Cannot set IGDB credentials.")
                else:
                    print("User opted out of IGDB metadata fetching.")
            elif requests: # requests is there, but IGDBWrapper is not
                 if messagebox.askyesno("Fetch IGDB Metadata?", 
                                       "Do you also want to fetch game metadata (summary, genre, etc.) from IGDB.com?\n\n(Note: The 'igdb-api-python' library is not installed. This step will be skipped unless you install it.)"):
                    print("IGDB fetching desired but 'igdb-api-python' is missing. Skipping.")

        generate_pegasus(root, app_map, host_uuid, host_name, out_dir, config_file_path_obj, 
                         use_steamgriddb, current_steamgriddb_api_key, 
                         fetch_igdb_enabled_for_run, current_igdb_client_id, current_igdb_app_access_token)
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
    lbl_apollo_conf_path_val = Label(apollo_path_frame, text="Not Set", fg="blue", width=40, anchor="w") # Increased width
    lbl_apollo_conf_path_val.pack(side="left", expand=True, fill="x")
    btn_set_apollo_path = Button(apollo_path_frame, text="Set/Change", 
                                 command=lambda: prompt_and_save_apollo_conf_path(lbl_apollo_conf_path_val))
    btn_set_apollo_path.pack(side="left")

    # SteamGridDB API Key Management
    api_key_frame = Frame(config_frame)
    api_key_frame.pack(fill="x", pady=5)
    lbl_api_key_text = Label(api_key_frame, text="SteamGridDB API Key: ")
    lbl_api_key_text.pack(side="left")
    lbl_api_key_val = Label(api_key_frame, text="Not Set", fg="blue", width=40, anchor="w") # Increased width
    lbl_api_key_val.pack(side="left", expand=True, fill="x")
    btn_set_api_key = Button(api_key_frame, text="Set/Change", 
                             command=lambda: prompt_and_save_api_key(root, lbl_api_key_val))
    btn_set_api_key.pack(side="left")

    # IGDB Credentials Management (Combined)
    igdb_creds_frame = Frame(config_frame)
    igdb_creds_frame.pack(fill="x", pady=5)
    lbl_igdb_creds_text = Label(igdb_creds_frame, text="IGDB Credentials: ")
    lbl_igdb_creds_text.pack(side="left")
    lbl_igdb_creds_val = Label(igdb_creds_frame, text="Client ID: Not Set | Token: Not Set", fg="blue", width=40, anchor="w") # Increased width
    lbl_igdb_creds_val.pack(side="left", expand=True, fill="x")
    btn_set_igdb_creds = Button(igdb_creds_frame, text="Set/Change",
                                command=lambda: prompt_and_set_igdb_credentials(root, lbl_igdb_creds_val))
    btn_set_igdb_creds.pack(side="left")

    # --- Action Buttons ---
    Button(root, text="Pegasus", width=28,
           command=lambda: choose_and_run(root, "Pegasus", lbl_api_key_val, lbl_apollo_conf_path_val, lbl_igdb_creds_val)).pack(pady=4) # Pass root & labels
    Button(root, text="ES-DE",   width=28,
           command=lambda: choose_and_run(root, "ES-DE", api_key_label_widget=None, apollo_conf_label_widget=lbl_apollo_conf_path_val, igdb_label_widget=None)).pack(pady=4) # Pass root & apollo label
    Button(root, text="Daijishō", width=28,
           command=lambda: choose_and_run(root, "Daijishō", api_key_label_widget=None, apollo_conf_label_widget=lbl_apollo_conf_path_val, igdb_label_widget=None)).pack(pady=4) # Pass root & apollo label

    # Load initial config and update UI
    load_config() # Load existing config
    update_apollo_path_label(lbl_apollo_conf_path_val)
    update_api_key_label(lbl_api_key_val)
    update_igdb_credentials_label(lbl_igdb_creds_val) # Use the new combined label updater

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

def prompt_and_save_api_key(root, label_widget):
    """Prompts user for SteamGridDB API key and saves it."""
    current_key = app_config.get("steamgriddb_api_key", "")
    dialog = SteamGridDBKeyDialog(root, "SteamGridDB API Key", initial_value=current_key)
    new_key = dialog.result

    if new_key is not None: # User clicked OK (new_key can be empty string if they clear it)
        is_valid = False
        if new_key:
            is_valid = check_steamgriddb_key_validity(new_key)
            if is_valid:
                app_config["steamgriddb_api_key"] = new_key
                messagebox.showinfo("API Key Saved", "SteamGridDB API Key has been updated and validated.")
            else:
                messagebox.showwarning("API Key Invalid", "The new SteamGridDB API Key appears to be invalid. It has not been saved.")
                # Do not save the invalid key, keep the old one or keep it empty if it was empty
                # If we want to allow saving an invalid key, remove this conditional saving
        else: # Key is cleared
            app_config["steamgriddb_api_key"] = "" # Save empty string
            messagebox.showinfo("API Key Cleared", "SteamGridDB API Key has been cleared.")
        
        # Only save config if key was validated or cleared, not if invalid new key was entered
        if is_valid or not new_key:
             save_config()
        update_api_key_label(label_widget)
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
             key_to_display = "Set (Short)" # Changed for clarity
        else: # Key is an empty string
            key_to_display = "Set (but empty)"
    label_widget.config(text=key_to_display)

def prompt_and_set_igdb_credentials(root, label_widget):
    """Prompts for IGDB Client ID & Secret, fetches token, saves ID & token."""
    dialog = IGDBCredentialsDialog(root, "Set IGDB Credentials")
    if dialog.result:
        client_id, client_secret = dialog.result
        if client_id and client_secret:
            new_token = fetch_igdb_app_access_token(client_id, client_secret)
            if new_token:
                if check_igdb_token_validity(client_id, new_token):
                    app_config["igdb_client_id"] = client_id
                    app_config["igdb_app_access_token"] = new_token
                    messagebox.showinfo("IGDB Credentials Set", "IGDB Client ID and App Access Token set and validated.")
                else:
                    app_config["igdb_client_id"] = client_id # Save client_id even if token is bad
                    app_config["igdb_app_access_token"] = None # Clear invalid token
                    messagebox.showwarning("IGDB Token Invalid", "Fetched token is invalid. Client ID saved, Token cleared.")
            else: # Token fetch failed
                app_config["igdb_client_id"] = client_id # Save client_id attempt
                app_config["igdb_app_access_token"] = None
                messagebox.showwarning("IGDB Token Not Set", "Could not fetch token. Client ID (if entered) saved, Token cleared.")
        elif client_id and not client_secret: # ID but no secret
            app_config["igdb_client_id"] = client_id
            app_config["igdb_app_access_token"] = None
            messagebox.showwarning("IGDB Secret Missing", "Client Secret not provided. Client ID saved, Token cleared.")
        elif not client_id : # Cleared client ID
            app_config["igdb_client_id"] = None
            app_config["igdb_app_access_token"] = None
            messagebox.showinfo("IGDB Credentials Cleared", "IGDB Client ID and Token cleared.")
        save_config()
        update_igdb_credentials_label(label_widget)
    # Else: User cancelled the dialog

def update_igdb_credentials_label(label_widget):
    """Updates the IGDB credentials display label (Client ID masked, Token status)."""
    client_id_display = "Client ID: Not Set"
    token_display = "Token: Not Set"
    if app_config.get("igdb_client_id"):
        client_id = app_config["igdb_client_id"]
        client_id_display = f"Client ID: {client_id[:4]}...{client_id[-3:]}" if len(client_id) > 7 else (f"Client ID: {client_id}" if client_id else "Client ID: Cleared")
    if app_config.get("igdb_app_access_token"):
        # We don't display the token itself, just its status and if client_id is also set
        if app_config.get("igdb_client_id"):
             token_display = "Token: Set & Saved (Validated on use)"
        else:
             token_display = "Token: Set (but Client ID missing)" # Should not happen if logic is correct
    label_widget.config(text=f"{client_id_display} | {token_display}")


# Class for SteamGridDBKeyDialog (ensure this is present)
class SteamGridDBKeyDialog(simpledialog.Dialog):
    def __init__(self, parent, title=None, initial_value=""):
        self.key_var = None
        self.initial_value = initial_value
        super().__init__(parent, title)

    def body(self, master):
        Label(master, text="Enter your SteamGridDB API Key.").pack(pady=5)
        self.key_var = simpledialog.Entry(master, width=40)
        self.key_var.pack()
        if self.initial_value:
            self.key_var.insert(0, self.initial_value)

        link_frame = Frame(master)
        link_frame.pack(pady=10)
        Label(link_frame, text="How to get a SteamGridDB API Key:").pack(side="left")
        link = Label(link_frame, text="SteamGridDB Preferences", fg="blue", cursor="hand2")
        link.pack(side="left", padx=5)
        link.bind("<Button-1>", lambda e: webbrowser.open_new("https://www.steamgriddb.com/profile/preferences/api"))
        return self.key_var

    def apply(self):
        self.result = self.key_var.get().strip()


# ────────────────────────────────────────────────────────────────────────────
# API Key/Token Validation
# ────────────────────────────────────────────────────────────────────────────
def check_steamgriddb_key_validity(api_key: str) -> bool:
    """Checks if the SteamGridDB API key is valid by making a test call."""
    if not requests or not api_key:
        return False
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = requests.get(f"{STEAMGRIDDB_API_URL}/search/autocomplete/thisgameprobablydoesnotexist", headers=headers, timeout=5)
        if response.status_code == 200: # OK
            print("SteamGridDB API Key appears valid.")
            return True
        elif response.status_code == 401: # Unauthorized
            print("SteamGridDB API Key is invalid (Unauthorized).")
            return False
        else:
            print(f"SteamGridDB API Key validation failed with status: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Error during SteamGridDB API Key validation: {e}")
        return False

def check_igdb_token_validity(client_id: str, token: str) -> bool:
    """Checks if the IGDB App Access Token is valid by making a test call."""
    if not requests or not client_id or not token or not IGDBWrapper:
        print("Skipping IGDB token validation: prerequisites missing.")
        return False
    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {token}",
    }
    try:
        response = requests.post(f"{IGDB_API_URL}/games/count", headers=headers, data="fields id;", timeout=5)
        if response.status_code == 200:
            print("IGDB App Access Token appears valid.")
            return True
        elif response.status_code == 401 or response.status_code == 403:
            print(f"IGDB App Access Token is invalid (Status: {response.status_code}).")
            return False
        else:
            print(f"IGDB Token validation failed. Status: {response.status_code}, Response: {response.text[:200]}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Error during IGDB token validation: {e}")
        return False

def fetch_igdb_app_access_token(client_id: str, client_secret: str):
    if not requests:
        messagebox.showerror("Error", "The \'requests\' library is required.")
        return None
    if not client_id or not client_secret:
        messagebox.showerror("Input Error", "Client ID and Client Secret are required.")
        return None
    token_url = "https://id.twitch.tv/oauth2/token"
    params = {"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}
    try:
        response = requests.post(token_url, params=params, timeout=10)
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data.get("access_token")
        if access_token:
            print("Successfully fetched IGDB App Access Token.")
            return access_token
        else:
            messagebox.showerror("Token Fetch Error", f"Could not retrieve access token: {token_data.get('message', 'Unknown error')}")
            return None
    except requests.exceptions.HTTPError as e:
        error_details = "Unknown error."
        try: error_details = e.response.json().get('message', e.response.text)
        except json.JSONDecodeError: error_details = e.response.text
        messagebox.showerror("Token Fetch Error", f"HTTP {e.response.status_code}: {error_details}")
        return None
    except requests.exceptions.RequestException as e:
        messagebox.showerror("Token Fetch Error", f"Request error: {e}")
        return None

# ────────────────────────────────────────────────────────────────────────────
# IGDB Credentials Dialog & Token Fetching
# ────────────────────────────────────────────────────────────────────────────
class IGDBCredentialsDialog(simpledialog.Dialog):
    def __init__(self, parent, title=None):
        self.client_id_var = None
        self.client_secret_var = None
        super().__init__(parent, title)

    def body(self, master):
        Label(master, text="Enter your IGDB Client ID and Client Secret.").pack(pady=5)
        Label(master, text="Client ID:").pack()
        self.client_id_var = simpledialog.Entry(master, width=40)
        self.client_id_var.pack()
        Label(master, text="Client Secret:").pack()
        self.client_secret_var = simpledialog.Entry(master, width=40, show='*')
        self.client_secret_var.pack()

        link_frame = Frame(master)
        link_frame.pack(pady=10)
        Label(link_frame, text="How to get IGDB credentials:").pack(side="left")
        link = Label(link_frame, text="API Docs", fg="blue", cursor="hand2")
        link.pack(side="left", padx=5)
        link.bind("<Button-1>", lambda e: webbrowser.open_new("https://api-docs.igdb.com/#account-creation"))
        
        if app_config.get("igdb_client_id"):
            self.client_id_var.insert(0, app_config["igdb_client_id"])
        return self.client_id_var

    def apply(self):
        self.result = (self.client_id_var.get().strip(), self.client_secret_var.get().strip())

if __name__ == "__main__":
    main()
