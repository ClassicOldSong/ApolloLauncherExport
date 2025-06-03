#!/usr/bin/env python3
from tkinter import messagebox
from utils import sanitize_filename, open_directory

def generate_generic_art_files(app_map, host_uuid, host_name, out_dir):
    """Generate Generic Artemis app entries."""
    for name, game_data in app_map.items():
        uuid = game_data["uuid"]
        (out_dir / f"{sanitize_filename(name)}.art").write_text(
            f"""# Artemis app entry
[host_uuid] {host_uuid}
[host_name] {host_name}
[app_uuid] {uuid}
[app_name] {name}
""", encoding="utf-8"
        )

def generate_generic(app_map, host_uuid, host_name, out_dir):
    generate_generic_art_files(app_map, host_uuid, host_name, out_dir)
    messagebox.showinfo("Done", "Generic Artemis app entries created!")
    open_directory(out_dir) 