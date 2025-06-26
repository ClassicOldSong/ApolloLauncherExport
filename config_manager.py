from configparser import ConfigParser
from pathlib import Path
from tkinter import messagebox
from utils import SCRIPT_DIR # Assuming utils.py is in the same directory or accessible in PYTHONPATH

CONFIG_FILE_PATH = SCRIPT_DIR / "config.ini"

# Global store for loaded configuration
app_config = {
    "apollo_conf_path": None,
    "steamgriddb_api_key": None,
    "igdb_client_id": None,
    "igdb_app_access_token": None
}

def load_config():
    """Loads configuration from config.ini."""
    config = ConfigParser()
    if not CONFIG_FILE_PATH.exists():
        print(f"Config file not found: {CONFIG_FILE_PATH}. Using defaults or prompting.")
        return # No config file yet, will use defaults or prompt

    try:
        config.read(CONFIG_FILE_PATH, encoding='utf-8-sig')
        if 'settings' in config:
            app_config["apollo_conf_path"] = config['settings'].get("apollo_conf_path")
            app_config["steamgriddb_api_key"] = config['settings'].get("steamgriddb_api_key")
            app_config["igdb_client_id"] = config['settings'].get("igdb_client_id")
            app_config["igdb_app_access_token"] = config['settings'].get("igdb_app_access_token")
            # Validate path exists if loaded
            if app_config["apollo_conf_path"] and not Path(app_config["apollo_conf_path"]).exists():
                print(f"Warning: Apollo config path from settings does not exist: {app_config['apollo_conf_path']}")
                # app_config["apollo_conf_path"] = None # Optionally invalidate here or let user fix
        else:
            print(f"No [settings] section in {CONFIG_FILE_PATH}")

    except Exception as e:
        print(f"Error loading config from {CONFIG_FILE_PATH}: {e}")
        # Reset to defaults if loading fails critically
        app_config["apollo_conf_path"] = None
        app_config["steamgriddb_api_key"] = None
        app_config["igdb_client_id"] = None
        app_config["igdb_app_access_token"] = None

def save_config():
    """Saves current app_config to config.ini."""
    config = ConfigParser()
    config['settings'] = {}
    if app_config.get("apollo_conf_path"): # Use .get() for safety
        config['settings']["apollo_conf_path"] = str(app_config["apollo_conf_path"]) # Ensure string
    if app_config.get("steamgriddb_api_key"):
        config['settings']["steamgriddb_api_key"] = app_config["steamgriddb_api_key"]
    if app_config.get("igdb_client_id"):
        config['settings']["igdb_client_id"] = app_config["igdb_client_id"]
    if app_config.get("igdb_app_access_token"):
        config['settings']["igdb_app_access_token"] = app_config["igdb_app_access_token"]
    
    try:
        with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as configfile:
            config.write(configfile)
        print(f"Configuration saved to {CONFIG_FILE_PATH}")
    except Exception as e:
        messagebox.showerror("Config Save Error", f"Could not save configuration to {CONFIG_FILE_PATH}: {e}")

if __name__ == '__main__':
    # Example usage/test
    print(f"Config file path: {CONFIG_FILE_PATH}")
    load_config()
    print(f"Loaded config: {app_config}")
    # app_config["steamgriddb_api_key"] = "test_key_123"
    # save_config()
    # load_config()
    # print(f"Reloaded config: {app_config}") 