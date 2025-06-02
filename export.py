#!/usr/bin/env python3
# ApolloLauncherExport.py
#
# Derived from:
# https://github.com/Jetup13/Retroid-Pocket-3-Plus-Wiki/blob/main/Files/Backup/MoonlightFileGenerator.py
#
# Generate Pegasus Frontend (.artp) / Daijishō (.art) / ES-DE launcher files (.artes) for Apollo–Artemis.
# Python 3.8+ -- only stdlib (tkinter, configparser, json, shutil, pathlib).

from pathlib import Path
from tkinter import Tk, Button, Label, messagebox, Checkbutton, BooleanVar

# Import from refactored modules
from utils import BASE_DIR, parse_conf, collect_data, ensure_out_dir
from config_manager import app_config, load_config
from gui_components import (
    update_apollo_path_label, update_api_key_label, update_igdb_credentials_label,
    prompt_and_save_apollo_conf_path, prompt_and_save_api_key, prompt_and_set_igdb_credentials
)
from api_clients import MetadataFetcher, check_steamgriddb_key_validity, check_igdb_token_validity
from generators import generate_daijishou, generate_esde, generate_pegasus, generate_generic

try:
    import requests
except ImportError:
    messagebox.showwarning("Missing Dependency", "The 'requests' library is not installed. SteamGridDB and IGDB functionality will be disabled. Please install it using: pip install requests")
    requests = None

try:
    from igdb.wrapper import IGDBWrapper
    if not requests:
        raise ImportError("IGDBWrapper also needs 'requests' library.")
except ImportError:
    print("Warning: 'igdb-api-python' library not installed or 'requests' is missing. IGDB functionality will require setup.")
    IGDBWrapper = None

def choose_and_run(root, mode: str, api_key_label_widget=None, apollo_conf_label_widget=None, igdb_label_widget=None, steamgriddb_var=None, igdb_var=None, skip_existing_var=None):
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
        if not apollo_conf_label_widget:
            messagebox.showerror("Error", "Apollo config UI element missing.")
            return
        prompt_and_save_apollo_conf_path(apollo_conf_label_widget)
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
    ensure_out_dir(out_dir)

    use_steamgriddb = False
    current_steamgriddb_api_key = app_config.get("steamgriddb_api_key")

    fetch_igdb_enabled_for_run = False
    current_igdb_client_id = app_config.get("igdb_client_id")
    current_igdb_app_access_token = app_config.get("igdb_app_access_token")

    metadata_fetcher = None # Initialize metadata_fetcher

    if mode == "Pegasus":
        if not requests:
            messagebox.showwarning("Missing Library", "The 'requests' library is not installed. SteamGridDB and IGDB features are disabled.")
        else:
            # SteamGridDB Setup - check if checkbox is enabled
            if steamgriddb_var and steamgriddb_var.get():
                if current_steamgriddb_api_key and check_steamgriddb_key_validity(current_steamgriddb_api_key):
                    use_steamgriddb = True
                    print("Using existing valid SteamGridDB API key.")
                else:
                    if current_steamgriddb_api_key:
                        messagebox.showwarning("SteamGridDB API Key Invalid", 
                                               "Your configured SteamGridDB API key is invalid. Please set a new one.")
                    else:
                        messagebox.showinfo("SteamGridDB API Key Needed", 
                                            "SteamGridDB API key is not configured. Please set it to enable asset fetching.")
                    
                    if api_key_label_widget:
                        prompt_and_save_api_key(root, api_key_label_widget)
                        current_steamgriddb_api_key = app_config.get("steamgriddb_api_key")
                        if current_steamgriddb_api_key and check_steamgriddb_key_validity(current_steamgriddb_api_key):
                            use_steamgriddb = True
                            print("Using newly set and validated SteamGridDB API key.")
                        else:
                            print("SteamGridDB API key not set or invalid after prompt. Fetching disabled.")
                    else:
                        print("SteamGridDB UI element missing. Cannot prompt for key.")
            else:
                print("SteamGridDB asset fetching disabled (checkbox unchecked).")

            # IGDB Setup - check if checkbox is enabled (independent of SteamGridDB)
            if igdb_var and igdb_var.get():
                if IGDBWrapper:
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
                        prompt_and_set_igdb_credentials(root, igdb_label_widget)
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
                    messagebox.showwarning("Missing Dependency", 
                                         "IGDB metadata fetching is enabled, but the 'igdb-api-python' library is not installed. Please install it using: pip install igdb-api-python")
                    print("IGDB fetching desired but 'igdb-api-python' is missing. Skipping.")
            else:
                print("IGDB metadata fetching disabled (checkbox unchecked).")

            # Create MetadataFetcher instance if any fetching is enabled
            if use_steamgriddb or fetch_igdb_enabled_for_run:
                metadata_fetcher = MetadataFetcher(
                    steamgriddb_api_key=current_steamgriddb_api_key if use_steamgriddb else None,
                    igdb_client_id=current_igdb_client_id if fetch_igdb_enabled_for_run else None,
                    igdb_app_access_token=current_igdb_app_access_token if fetch_igdb_enabled_for_run else None
                )

        generate_pegasus(root, app_map, host_uuid, host_name, out_dir, config_file_path_obj,
                         metadata_fetcher, # Pass the instance
                         skip_existing_var.get() if skip_existing_var else False)
    elif mode == "ES-DE":
        generate_esde(app_map, host_uuid, host_name, out_dir)
    elif mode == "Daijishō":
        generate_daijishou(app_map, host_uuid, host_name, out_dir)
    elif mode == "Generic":
        generate_generic(app_map, host_uuid, host_name, out_dir)


def main():
    root = Tk()
    root.title("Apollo Launcher Export")

    # --- Configuration Management UI ---
    from tkinter import Frame
    config_frame = Frame(root, pady=10)
    config_frame.pack(fill="x", padx=10)

    # Apollo Config Path Management
    apollo_path_frame = Frame(config_frame)
    apollo_path_frame.pack(fill="x")
    lbl_apollo_conf_text = Label(apollo_path_frame, text="Apollo Config (.conf): ")
    lbl_apollo_conf_text.pack(side="left")
    lbl_apollo_conf_path_val = Label(apollo_path_frame, text="Not Set", fg="blue", width=40, anchor="w")
    lbl_apollo_conf_path_val.pack(side="left", expand=True, fill="x")
    btn_set_apollo_path = Button(apollo_path_frame, text="Set", 
                                 command=lambda: prompt_and_save_apollo_conf_path(lbl_apollo_conf_path_val))
    btn_set_apollo_path.pack(side="left")

    # SteamGridDB API Key Management
    api_key_frame = Frame(config_frame)
    api_key_frame.pack(fill="x", pady=5)
    lbl_api_key_text = Label(api_key_frame, text="SteamGridDB API Key: ")
    lbl_api_key_text.pack(side="left")
    lbl_api_key_val = Label(api_key_frame, text="Not Set", fg="blue", width=40, anchor="w")
    lbl_api_key_val.pack(side="left", expand=True, fill="x")
    btn_set_api_key = Button(api_key_frame, text="Set", 
                             command=lambda: prompt_and_save_api_key(root, lbl_api_key_val))
    btn_set_api_key.pack(side="left")

    # IGDB Credentials Management (Combined)
    igdb_creds_frame = Frame(config_frame)
    igdb_creds_frame.pack(fill="x", pady=5)
    lbl_igdb_creds_text = Label(igdb_creds_frame, text="IGDB Credentials: ")
    lbl_igdb_creds_text.pack(side="left")
    lbl_igdb_creds_val = Label(igdb_creds_frame, text="Client ID: Not Set | Token: Not Set", fg="blue", width=40, anchor="w")
    lbl_igdb_creds_val.pack(side="left", expand=True, fill="x")
    btn_set_igdb_creds = Button(igdb_creds_frame, text="Set",
                                command=lambda: prompt_and_set_igdb_credentials(root, lbl_igdb_creds_val))
    btn_set_igdb_creds.pack(side="left")

    # --- Feature Options (Checkboxes) ---
    options_frame = Frame(root, pady=10)
    options_frame.pack(fill="x", padx=10)
    
    Label(options_frame, text="Pegasus Frontend Options:").pack(anchor="w")
    
    # SteamGridDB checkbox
    steamgriddb_var = BooleanVar()
    steamgriddb_checkbox = Checkbutton(options_frame, text="Download game assets from SteamGridDB", 
                                       variable=steamgriddb_var)
    steamgriddb_checkbox.pack(anchor="w", padx=20)
    
    # IGDB checkbox
    igdb_var = BooleanVar()
    igdb_checkbox = Checkbutton(options_frame, text="Fetch game metadata from IGDB.com", 
                                variable=igdb_var)
    igdb_checkbox.pack(anchor="w", padx=20)

    # Skip existing checkbox
    skip_existing_var = BooleanVar()
    skip_existing_checkbox = Checkbutton(options_frame, text="Skip image fetching for existing ROM files (still update metadata)", 
                                        variable=skip_existing_var)
    skip_existing_checkbox.pack(anchor="w", padx=20)

    Label(root, text="Generate launcher files for:").pack(pady=10)

    # --- Action Buttons ---
    Button(root, text="Pegasus", width=28,
           command=lambda: choose_and_run(root, "Pegasus", lbl_api_key_val, lbl_apollo_conf_path_val, lbl_igdb_creds_val, steamgriddb_var, igdb_var, skip_existing_var)).pack(pady=4)
    Button(root, text="ES-DE", width=28,
           command=lambda: choose_and_run(root, "ES-DE", api_key_label_widget=None, apollo_conf_label_widget=lbl_apollo_conf_path_val, igdb_label_widget=None, skip_existing_var=skip_existing_var)).pack(pady=4)
    Button(root, text="Daijishō", width=28,
           command=lambda: choose_and_run(root, "Daijishō", api_key_label_widget=None, apollo_conf_label_widget=lbl_apollo_conf_path_val, igdb_label_widget=None, skip_existing_var=skip_existing_var)).pack(pady=4)
    Button(root, text="Generic", width=28,
           command=lambda: choose_and_run(root, "Generic", api_key_label_widget=None, apollo_conf_label_widget=lbl_apollo_conf_path_val, igdb_label_widget=None, skip_existing_var=skip_existing_var)).pack(pady=4)
    
    # Load initial config and update UI
    load_config()
    update_apollo_path_label(lbl_apollo_conf_path_val)
    update_api_key_label(lbl_api_key_val)
    update_igdb_credentials_label(lbl_igdb_creds_val)

    root.mainloop()


if __name__ == "__main__":
    main()
