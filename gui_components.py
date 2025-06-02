from tkinter import (Button, Label, filedialog, messagebox, Frame, simpledialog, Toplevel, Entry)
import webbrowser
from pathlib import Path

# Import functions and variables from other refactored modules
from config_manager import app_config, save_config # For accessing and saving config
from api_clients import check_steamgriddb_key_validity, fetch_igdb_app_access_token, check_igdb_token_validity # For validation

# --- Custom Dialogs --- 
class SteamGridDBKeyDialog(simpledialog.Dialog):
    def __init__(self, parent, title=None, initial_value=""):
        self.key_var = None # Changed from simpledialog.Entry to Entry
        self.initial_value = initial_value
        super().__init__(parent, title)

    def body(self, master):
        Label(master, text="Enter your SteamGridDB API Key.").pack(pady=5)
        self.key_var = Entry(master, width=40) # Use tkinter.Entry
        self.key_var.pack()
        if self.initial_value:
            self.key_var.insert(0, self.initial_value)

        link_frame = Frame(master)
        link_frame.pack(pady=10)
        Label(link_frame, text="How to get a SteamGridDB API Key:").pack(side="left")
        link = Label(link_frame, text="SteamGridDB Preferences", fg="blue", cursor="hand2")
        link.pack(side="left", padx=5)
        link.bind("<Button-1>", lambda e: webbrowser.open_new("https://www.steamgriddb.com/profile/preferences/api"))
        return self.key_var # Focus on this widget

    def apply(self):
        self.result = self.key_var.get().strip()

class IGDBCredentialsDialog(simpledialog.Dialog):
    def __init__(self, parent, title=None):
        self.client_id_var = None # Changed from simpledialog.Entry to Entry
        self.client_secret_var = None # Changed from simpledialog.Entry to Entry
        super().__init__(parent, title)

    def body(self, master):
        Label(master, text="Enter your IGDB Client ID and Client Secret.").pack(pady=5)
        Label(master, text="Client ID:").pack()
        self.client_id_var = Entry(master, width=40) # Use tkinter.Entry
        self.client_id_var.pack()
        Label(master, text="Client Secret:").pack()
        self.client_secret_var = Entry(master, width=40, show='*') # Use tkinter.Entry
        self.client_secret_var.pack()

        link_frame = Frame(master)
        link_frame.pack(pady=10)
        Label(link_frame, text="How to get IGDB credentials:").pack(side="left")
        link = Label(link_frame, text="API Docs", fg="blue", cursor="hand2")
        link.pack(side="left", padx=5)
        link.bind("<Button-1>", lambda e: webbrowser.open_new("https://api-docs.igdb.com/#account-creation"))
        
        # Pre-fill Client ID if it exists in app_config
        if app_config.get("igdb_client_id"):
            self.client_id_var.insert(0, app_config["igdb_client_id"])
        # Client Secret is typically not pre-filled for security.

        return self.client_id_var # Focus on this widget

    def apply(self):
        self.result = (self.client_id_var.get().strip(), self.client_secret_var.get().strip())

# --- Progress Dialog --- 
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

    def do_cancel(): # Keep do_cancel here as it's tied to this dialog
        print("[Dialog] Cancel button clicked.")
        cancel_event.set()

    btn_cancel = Button(dialog, text="Cancel", command=do_cancel)
    btn_cancel.pack(pady=10, side="bottom")

    root.update_idletasks()
    return dialog, lbl_game_status, lbl_asset_status

# --- UI Update Functions (for labels) --- 
def update_apollo_path_label(label_widget):
    """Updates the Apollo config path display label."""
    path_to_display = "Not Set"
    apollo_path_str = app_config.get("apollo_conf_path")
    if apollo_path_str:
        try:
            p = Path(apollo_path_str)
            # Display a shortened version for readability, e.g., last 2 components
            if p.name and p.parent and p.parent.name:
                 path_to_display = f".../{p.parent.name}/{p.name}" if len(p.parts) > 2 else str(p)
            else:
                path_to_display = str(p) # Fallback if parent or name is missing (e.g. root path)
        except Exception as e:
            print(f"Error creating path object for display: {e}")
            path_to_display = "Invalid Path"
    label_widget.config(text=path_to_display)

def update_api_key_label(label_widget):
    """Updates the API key display label (masked)."""
    key_to_display = "Not Set"
    api_key = app_config.get("steamgriddb_api_key")
    if api_key:
        if len(api_key) > 7:
            key_to_display = f"{api_key[:4]}...{api_key[-3:]}"
        elif api_key: # Key is short but not empty
             key_to_display = "Set (Short)"
    elif api_key == "": # Explicitly empty string
        key_to_display = "Set (but empty)"
    # If api_key is None (i.e., not in config or set to None), it remains "Not Set"
    label_widget.config(text=key_to_display)

def update_igdb_credentials_label(label_widget):
    """Updates the IGDB credentials display label (Client ID masked, Token status)."""
    client_id_display = "Client ID: Not Set"
    token_display = "Token: Not Set"
    
    client_id = app_config.get("igdb_client_id")
    app_token = app_config.get("igdb_app_access_token")

    if client_id:
        client_id_display = f"Client ID: {client_id[:4]}...{client_id[-3:]}" if len(client_id) > 7 else (f"Client ID: {client_id}" if client_id else "Client ID: Cleared")
    elif client_id == "":
        client_id_display = "Client ID: Set (but empty)"
        
    if app_token:
        if client_id: # Token is only useful if client ID is also set
             token_display = "Token: Set & Saved"
        else:
             token_display = "Token: Set (but Client ID missing)" # Should ideally not happen
    elif app_token == "":
        token_display = "Token: Set (but empty)"

    label_widget.config(text=f"{client_id_display} | {token_display}")

def update_host_name_label(label_widget, host_name_str):
    """Updates the host name display label."""
    if host_name_str:
        display_text = f"Generate launcher files for: {host_name_str}"
    elif host_name_str == "": # Explicitly empty, which shouldn't happen for hostname
        display_text = "Generate launcher files for: <empty>"
    else:
        display_text = "Generate launcher files for: Not Set"
    label_widget.config(text=display_text)

# --- Functions to prompt and save settings (now in GUI or main app logic) ---
# These functions usually involve dialogs (from this file) but also saving (config_manager)
# and validation (api_clients). They are part of the UI interaction flow.

def prompt_and_save_apollo_conf_path(label_widget, initial_dir_suggestion=None):
    """Prompts user for Apollo config path and saves it."""
    initial_dir = initial_dir_suggestion if initial_dir_suggestion else str(Path.home()) # Default to home or a suggestion
    current_apollo_path = app_config.get("apollo_conf_path")
    if current_apollo_path and Path(current_apollo_path).exists():
        initial_dir = str(Path(current_apollo_path).parent)
    elif current_apollo_path: # Path is set but doesn't exist
        pass # Keep initial_dir as is, or try to get parent of non-existing path

    new_path_str = filedialog.askopenfilename(
        title="Select Apollo config file (e.g., sunshine.conf)", 
        filetypes=[("Config files", "*.conf"), ("All files", "*.*")],
        initialdir=initial_dir
    )
    if new_path_str:
        app_config["apollo_conf_path"] = str(Path(new_path_str).resolve())
        save_config()
        update_apollo_path_label(label_widget)
        messagebox.showinfo("Path Saved", f"Apollo config path set to: {app_config['apollo_conf_path']}")
    else:
        # User cancelled, ensure label reflects current state (might be useful if path was cleared)
        update_apollo_path_label(label_widget)

def prompt_and_save_api_key(root_window, label_widget):
    """Prompts user for SteamGridDB API key, validates, and saves it."""
    current_key = app_config.get("steamgriddb_api_key", "")
    dialog = SteamGridDBKeyDialog(root_window, "SteamGridDB API Key", initial_value=current_key)
    new_key = dialog.result # .result is set by simpledialog.Dialog upon closing

    if new_key is not None: # User clicked OK (new_key can be empty string if they clear it)
        is_valid = False
        if new_key: # If key is not empty, validate it
            if check_steamgriddb_key_validity(new_key): # from api_clients
                is_valid = True
                app_config["steamgriddb_api_key"] = new_key
                messagebox.showinfo("API Key Saved", "SteamGridDB API Key has been updated and validated.")
            else:
                messagebox.showwarning("API Key Invalid", "The new SteamGridDB API Key appears to be invalid. It has not been saved.")
                # Do not save the invalid key, keep the old one or keep it empty if it was empty
        else: # Key is empty (cleared by user)
            is_valid = True # Consider an empty key as a valid state to save (cleared)
            app_config["steamgriddb_api_key"] = "" # Save empty string explicitly
            messagebox.showinfo("API Key Cleared", "SteamGridDB API Key has been cleared.")
        
        if is_valid: # Only save config if key was validated or deliberately cleared
             save_config()
        update_api_key_label(label_widget)
    # Else: User clicked Cancel, do nothing to the stored key or label update (label already reflects current)

def prompt_and_set_igdb_credentials(root_window, label_widget):
    """Prompts for IGDB Client ID & Secret, fetches token, validates, and saves ID & token."""
    # Dialog will pre-fill client_id from app_config if available
    dialog = IGDBCredentialsDialog(root_window, "Set IGDB Credentials")
    
    if dialog.result: # User clicked OK
        client_id, client_secret = dialog.result
        
        if not client_id and not client_secret: # Both fields cleared or initially empty
            app_config["igdb_client_id"] = None
            app_config["igdb_app_access_token"] = None
            messagebox.showinfo("IGDB Credentials Cleared", "IGDB Client ID and App Access Token have been cleared.")
        elif client_id and client_secret:
            new_token = fetch_igdb_app_access_token(client_id, client_secret) # from api_clients
            if new_token:
                if check_igdb_token_validity(client_id, new_token): # from api_clients
                    app_config["igdb_client_id"] = client_id
                    app_config["igdb_app_access_token"] = new_token
                    messagebox.showinfo("IGDB Credentials Set", "IGDB Client ID and App Access Token set and validated.")
                else:
                    app_config["igdb_client_id"] = client_id # Save client_id even if token is bad/fails validation
                    app_config["igdb_app_access_token"] = None # Clear invalid token
                    messagebox.showwarning("IGDB Token Invalid", "Fetched IGDB token appears to be invalid. Client ID has been saved, but the token has been cleared.")
            else: # Token fetch failed (e.g., bad credentials, network issue)
                app_config["igdb_client_id"] = client_id # Save client_id attempt
                app_config["igdb_app_access_token"] = None
                messagebox.showwarning("IGDB Token Not Set", "Could not fetch IGDB App Access Token. Please check credentials and network. Client ID (if entered) saved, Token cleared.")
        elif client_id and not client_secret: # Client ID provided, but no secret
            app_config["igdb_client_id"] = client_id
            app_config["igdb_app_access_token"] = None # Cannot get token without secret
            messagebox.showwarning("IGDB Secret Missing", "Client Secret not provided. Cannot fetch token. Client ID saved, Token cleared.")
        elif not client_id and client_secret: # Secret provided, but no client ID (unlikely, but handle)
            app_config["igdb_client_id"] = None
            app_config["igdb_app_access_token"] = None
            messagebox.showwarning("IGDB Client ID Missing", "Client ID not provided. Cannot fetch token. Credentials cleared.")

        save_config()
        update_igdb_credentials_label(label_widget)
    # Else: User cancelled the dialog, do nothing. Label already reflects current state. 