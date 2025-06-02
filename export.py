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
    prompt_and_save_apollo_conf_path, prompt_and_save_api_key, prompt_and_set_igdb_credentials,
    update_host_name_label
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

def choose_and_run(root, mode: str, 
                   # Parsed Apollo data:
                   apps_json, state_json, host_name, config_file_path_obj, 
                   # Other params:
                   api_key_label_widget=None, igdb_label_widget=None, 
                   steamgriddb_var=None, igdb_var=None, skip_existing_var=None):
    # Apollo config is now parsed beforehand and data is passed in.
    # The config_file_path_obj is passed for Pegasus generator.
    # host_name is passed directly.
    # apps_json and state_json are passed directly.

    app_map, host_uuid = collect_data(apps_json, state_json)
    if not app_map:
        messagebox.showerror("No games", "No apps with UUID found in apps.json")
        return

    # Host name label is updated externally now.
    # print(f"Debug: Processing for host: {host_name} in mode: {mode}")

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
        generate_esde(app_map, host_uuid, host_name, out_dir, skip_existing_var.get() if skip_existing_var else False)
    elif mode == "Daijishō":
        generate_daijishou(app_map, host_uuid, host_name, out_dir, skip_existing_var.get() if skip_existing_var else False)
    elif mode == "Generic":
        generate_generic(app_map, host_uuid, host_name, out_dir, skip_existing_var.get() if skip_existing_var else False)


def main():
    root = Tk()
    root.title("Apollo Launcher Export")

    parsed_apollo_data = {
        "apps_json": None,
        "state_json": None,
        "host_name": None,
        "config_file_path_obj": None,
        "is_valid": False
    }

    # --- Helper function to parse Apollo config and update UI ---
    def _attempt_parse_and_update_ui(apollo_conf_display_label, host_name_display_label, prompt_if_needed: bool):
        nonlocal parsed_apollo_data
        
        # Inner function to perform the parsing and UI update for the current config path
        def _do_parse_and_update():
            nonlocal parsed_apollo_data
            # Reset status before parsing
            parsed_apollo_data["is_valid"] = False
            parsed_apollo_data["apps_json"] = None
            parsed_apollo_data["state_json"] = None
            parsed_apollo_data["host_name"] = None
            parsed_apollo_data["config_file_path_obj"] = None

            apollo_conf_path_str = app_config.get("apollo_conf_path")
            update_apollo_path_label(apollo_conf_display_label) # Ensure label reflects current state from app_config

            if apollo_conf_path_str:
                config_file_path_obj_temp = Path(apollo_conf_path_str)
                if config_file_path_obj_temp.exists() and config_file_path_obj_temp.is_file():
                    try:
                        apps_json, state_json, host_name_parsed = parse_conf(config_file_path_obj_temp)
                        
                        if apps_json is not None and state_json is not None and host_name_parsed is not None:
                            parsed_apollo_data["apps_json"] = apps_json
                            parsed_apollo_data["state_json"] = state_json
                            parsed_apollo_data["host_name"] = host_name_parsed
                            parsed_apollo_data["config_file_path_obj"] = config_file_path_obj_temp
                            parsed_apollo_data["is_valid"] = True
                            
                            update_host_name_label(host_name_display_label, host_name_parsed)
                            print(f"Successfully parsed Apollo config for host: {host_name_parsed}")
                            return True # Parsed successfully
                        else:
                            messagebox.showerror("Apollo Config Error", "Failed to parse critical data from Apollo config file. Check console for details.")
                            update_host_name_label(host_name_display_label, "Error: Could not parse .conf")
                    except Exception as e:
                        messagebox.showerror("Apollo Config Error", f"Error parsing Apollo config file '{config_file_path_obj_temp.name}': {e}")
                        update_host_name_label(host_name_display_label, f"Error parsing: {config_file_path_obj_temp.name}")
                else:
                    # Path in config is invalid (e.g., file deleted or moved)
                    update_host_name_label(host_name_display_label, "Error: .conf path invalid")
                    # update_apollo_path_label called above will show "Not Set" if path is truly gone from config,
                    # or the invalid path if it's still set in config.
            else:
                # No Apollo config path set
                update_host_name_label(host_name_display_label, "N/A - Set Apollo .conf file")
            
            return False # Parsing failed or path not set/invalid

        # --- Main logic for _attempt_parse_and_update_ui ---
        if _do_parse_and_update():
            return True # Initial parse (or parse after "Set" button) successful

        if prompt_if_needed:
            messagebox.showinfo("Apollo Configuration Required", 
                                "Apollo configuration file (.conf) is not set or is invalid. Please select it now.")
            
            prompt_and_save_apollo_conf_path(apollo_conf_display_label) 
            
            if _do_parse_and_update():
                return True # Parse successful after prompt
            
            messagebox.showwarning("Apollo Configuration Failed", 
                                   "Could not set or validate the Apollo configuration file. "\
                                   "Please set it manually via the 'Set' button if needed.")
        return False

    # --- Helper function to dispatch to choose_and_run ---
    def _dispatch_choose_and_run(mode, 
                                 api_key_label=None, igdb_label=None, 
                                 steam_var=None, igdb_fetch_var=None, skip_var=None):
        nonlocal parsed_apollo_data
        if parsed_apollo_data["is_valid"]:
            choose_and_run(
                root, mode,
                parsed_apollo_data["apps_json"],
                parsed_apollo_data["state_json"],
                parsed_apollo_data["host_name"],
                parsed_apollo_data["config_file_path_obj"],
                api_key_label_widget=api_key_label,
                igdb_label_widget=igdb_label,
                steamgriddb_var=steam_var,
                igdb_var=igdb_fetch_var,
                skip_existing_var=skip_var
            )
        else:
            messagebox.showerror("Apollo Config Not Ready", 
                                 "Apollo configuration is not loaded or is invalid. Please set the .conf file and ensure it's correct.")

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
    
    # This label will be updated by _attempt_parse_and_update_ui
    lbl_host_name_val = Label(root, text="N/A", width=60, anchor="w") # Placeholder, defined later

    btn_set_apollo_path = Button(apollo_path_frame, text="Set", 
                                 command=lambda: (
                                     prompt_and_save_apollo_conf_path(lbl_apollo_conf_path_val), 
                                     _attempt_parse_and_update_ui(lbl_apollo_conf_path_val, lbl_host_name_val, prompt_if_needed=False)
                                 ))
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
    
    steamgriddb_var = BooleanVar()
    steamgriddb_checkbox = Checkbutton(options_frame, text="Download game assets from SteamGridDB", 
                                       variable=steamgriddb_var)
    steamgriddb_checkbox.pack(anchor="w", padx=20)
    
    igdb_var = BooleanVar()
    igdb_checkbox = Checkbutton(options_frame, text="Fetch game metadata from IGDB.com", 
                                variable=igdb_var)
    igdb_checkbox.pack(anchor="w", padx=20)

    skip_existing_var = BooleanVar()
    skip_existing_checkbox = Checkbutton(options_frame, text="Skip image fetching for existing ROM files (still update metadata)", 
                                        variable=skip_existing_var)
    skip_existing_checkbox.pack(anchor="w", padx=20)

    # lbl_host_name_val was defined earlier to be available for lambda
    lbl_host_name_val.pack(pady=(0,10), padx=20, anchor="w")

    # --- Action Buttons ---
    Button(root, text="Pegasus", width=28,
           command=lambda: _dispatch_choose_and_run(
               "Pegasus", 
               api_key_label=lbl_api_key_val, 
               igdb_label=lbl_igdb_creds_val, 
               steam_var=steamgriddb_var, 
               igdb_fetch_var=igdb_var, 
               skip_var=skip_existing_var
           )).pack(pady=4)
    Button(root, text="ES-DE", width=28,
           command=lambda: _dispatch_choose_and_run(
               "ES-DE",
               skip_var=skip_existing_var
           )).pack(pady=4) # Pass only skip_var as others are not used by ES-DE mode
    Button(root, text="Daijishō", width=28,
           command=lambda: _dispatch_choose_and_run(
               "Daijishō",
               skip_var=skip_existing_var
           )).pack(pady=4) # Pass only skip_var
    Button(root, text="Generic", width=28,
           command=lambda: _dispatch_choose_and_run(
               "Generic",
               skip_var=skip_existing_var
           )).pack(pady=4) # Pass only skip_var
    
    # Load initial config and update UI
    load_config()
    update_api_key_label(lbl_api_key_val) # Update API key display first
    update_igdb_credentials_label(lbl_igdb_creds_val) # Update IGDB display
    
    # Initial attempt to parse Apollo config and update related UI elements
    _attempt_parse_and_update_ui(lbl_apollo_conf_path_val, lbl_host_name_val, prompt_if_needed=True)

    root.mainloop()


if __name__ == "__main__":
    main()
