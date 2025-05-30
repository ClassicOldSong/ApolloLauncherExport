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
from tkinter import Tk, Button, Label, filedialog, messagebox
from configparser import ConfigParser

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


def generate_pegasus(app_map, host_uuid, host_name, out_dir, config_path: Path):
    """Generates Pegasus Frontend metadata files."""
    covers_dir = config_path.parent / "assets"
    # Create .artp files for each game
    for name, game_data in app_map.items():
        uuid = game_data["uuid"]
        app_image_path_str = game_data.get("app_image")

        (out_dir / f"{uuid}.artp").write_text(f"[metadata]\napp_name={name}\napp_uuid={uuid}\nhost_uuid={host_uuid}\n", encoding="utf-8")

        if app_image_path_str:
            app_image_path = Path(app_image_path_str)
            if not app_image_path.is_absolute():
                app_image_path = covers_dir / app_image_path
            
            if app_image_path.exists() and app_image_path.is_file():
                media_game_dir = out_dir / "media" / uuid
                media_game_dir.mkdir(parents=True, exist_ok=True)
                dest_path = media_game_dir / "boxFront.png"
                try:
                    shutil.copy2(app_image_path, dest_path)
                except Exception as e:
                    print(f"Skipping image copy for {name} due to error: {e}")
            else:
                print(f"Skipping image for {name}: {app_image_path_str} not found or not a file.")


    # Create metadata.pegasus.txt
    metadata_content = []
    metadata_content.append(f"collection: {host_name}")
    metadata_content.append("shortname: artemis") # Consistent with other exports
    metadata_content.append("extension: artp")
    
    # Note: {{file.basename}} is for Pegasus to replace, host_uuid is embedded by Python
    launch_command = f"am start -n com.limelight.noir/com.limelight.ShortcutTrampoline --es UUID {host_uuid} --es AppUUID {{file.basename}}"
    metadata_content.append(f"launch: {launch_command}")
    metadata_content.append("") # Empty line for separation

    for name, game_data in app_map.items():
        uuid = game_data["uuid"]
        metadata_content.append(f"game: {name}")
        metadata_content.append(f"file: {uuid}.artp")
        metadata_content.append("") # Empty line after each game entry
    
    (out_dir / "metadata.pegasus.txt").write_text("\n".join(metadata_content).strip(), encoding="utf-8")

    messagebox.showinfo("Done", f"Pegasus Frontend files (.artp, metadata.pegasus.txt) created in '{out_dir.name}'!")
    open_directory(out_dir)


# ─── GUI ────────────────────────────────────────────────────────────────────
def choose_and_run(mode: str):
    conf_path = filedialog.askopenfilename(
        title="Select Apollo config file (sunshine.conf)", filetypes=[("Apollo conf", "*.conf")]
    )
    if not conf_path:
        return

    apps_json, state_json, host_name = parse_conf(Path(conf_path))
    app_map, host_uuid    = collect_data(apps_json, state_json)
    if not app_map:
        messagebox.showerror("No games", "No apps with UUID found in apps.json")
        return

    out_dir = BASE_DIR / mode / host_name

    ensure_out_dir(out_dir)

    if mode == "Pegasus":
        generate_pegasus(app_map, host_uuid, host_name, out_dir, Path(conf_path).parent)
    elif mode == "ES-DE":
        generate_esde(app_map, host_uuid, host_name, out_dir)
    else: # daijishou
        generate_daijishou(app_map, host_uuid, host_name, out_dir)


def main():
    root = Tk(); root.title("Apollo Launcher Export")
    Label(root, text="Generate launcher files for:").pack(pady=10)

    Button(root, text="Pegasus", width=28,
           command=lambda: choose_and_run("Pegasus")).pack(pady=4)
    Button(root, text="ES-DE",   width=28,
           command=lambda: choose_and_run("ES-DE")).pack(pady=4)
    Button(root, text="Daijishō", width=28,
           command=lambda: choose_and_run("Daijishō")).pack(pady=4)

    root.mainloop()


if __name__ == "__main__":
    main()
