#!/usr/bin/env python3
import json
from tkinter import messagebox
from utils import sanitize, open_directory

def generate_daijishou(app_map, host_uuid, host_name, out_dir):
    """Generate Daijishō launcher files (.art format)."""
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