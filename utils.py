#!/usr/bin/env python3
import json
import re
import sys
import shutil
import os
import subprocess
from pathlib import Path
from configparser import ConfigParser
from tkinter import messagebox

try:
    import requests
except ImportError:
    # requests is optional, functions using it should handle its absence.
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
BASE_DIR = SCRIPT_DIR / "export" # This was SCRIPT_DIR / "export" in the original main file.
                                # If utils.py is in the root, SCRIPT_DIR is the root.
                                # If export.py moves to a subfolder, this might need adjustment
                                # For now, assuming utils.py is at the same level as the original export.py or its replacement.

def download_image(url: str, save_path: Path, headers: dict = None):
    """Downloads an image from a URL and saves it."""
    if not requests:
        print("Skipping download: 'requests' library not available.")
        # Consider if messagebox is appropriate here or if it should return a status
        # messagebox.showwarning("Missing Dependency", "The 'requests' library is not installed. Image download aborted.")
        return False
    try:
        # For CDN URLs, we generally don't want to pass the API auth headers.
        # Create a new session or use default headers for CDN downloads.
        cdn_request_headers = {}
        if headers and 'Authorization' in headers and not url.startswith("https://www.steamgriddb.com/api/v2"):
             # If custom headers were provided, but it's a CDN URL, don't use Auth header.
             pass # Effectively using default headers for CDN
        elif url.startswith("https://www.steamgriddb.com/api/v2"):
            cdn_request_headers = headers # Use provided headers (with Auth) for direct API image links if any

        response = requests.get(url, stream=True, headers=cdn_request_headers, timeout=15)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            shutil.copyfileobj(response.raw, f)
        print(f"Successfully downloaded {save_path.name} to {save_path.parent}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error downloading {url}: {e}")
        return False

def sanitize(name: str) -> str:
    """Remove filename-hostile characters."""
    name = name.replace(":", " - ")
    return re.sub(r'[<>:"/\\|?*]', "", name)

def parse_conf(conf_path: Path):
    """
    Return absolute paths to apps.json & sunshine_state.json.
    If not set, defaults are relative to the .conf location.
    """
    raw = conf_path.read_text(encoding="utf-8", errors="ignore")
    cfg = ConfigParser(delimiters=("="))
    try:
        cfg.read_string("[root]\n" + raw) # Keep [root] as in original
    except Exception as e:
        print(f"Error reading conf string: {e}. Raw content was: {raw[:200]}") # Log part of raw content for debug
        raise # Re-raise after logging or handle more gracefully

    base = conf_path.parent
    apps_file  = cfg["root"].get("file_apps",  "apps.json")
    state_file = cfg["root"].get("file_state", "sunshine_state.json")
    host_name  = cfg["root"].get("sunshine_name", "Apollo Streaming") # Default value as in original

    return (base / apps_file).resolve(), (base / state_file).resolve(), host_name.strip()


def collect_data(apps_json: Path, state_json: Path):
    """Return {game_name: {"uuid": uuid, "app_image": app_image_path}} (skip missing UUID) and host_uuid."""
    if not apps_json.exists():
        raise FileNotFoundError(f"apps.json not found at {apps_json}")
    if not state_json.exists():
        raise FileNotFoundError(f"state.json not found at {state_json}")

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

def ensure_out_dir(out_dir):
    """Ensure output directory exists, with user confirmation if it already exists."""
    if out_dir.exists():
        if not messagebox.askyesno(
            "Output exists",
            f"Folder '{out_dir}' already exists.\nDelete its contents first?"
        ):
            return
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

def open_directory(path: Path):
    """Opens the given directory in the default file explorer."""
    if not path.exists():
        print(f"Cannot open directory, path does not exist: {path}")
        return
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.call(["open", path])
    else:
        subprocess.call(["xdg-open", path]) 