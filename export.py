#!/usr/bin/env python3
# ApolloLauncherExport.py
#
# Derived from:
# https://github.com/Jetup13/Retroid-Pocket-3-Plus-Wiki/blob/main/Files/Backup/MoonlightFileGenerator.py
#
# Generate Daijishō (.art) / ES-DE launcher files (.artes) for Apollo–Artemis.
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
    """Return {game_name: uuid} (skip missing UUID) and host_uuid."""
    with state_json.open(encoding="utf-8") as f:
        host_uuid = json.load(f)["root"]["uniqueid"]

    app_map = {}
    with apps_json.open(encoding="utf-8") as f:
        for app in json.load(f)["apps"]:
            name  = app.get("name")
            uuid  = app.get("uuid")
            if name and uuid:            # skip orphan entries
                app_map[name.lstrip()] = uuid

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
    for name, uuid in app_map.items():
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
    for name, uuid in app_map.items():
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

    if mode == "daijishou":
        generate_daijishou(app_map, host_uuid, host_name, out_dir)
    else:
        generate_esde(app_map, host_uuid, host_name, out_dir)


def main():
    root = Tk(); root.title("Apollo Launcher Export")
    Label(root, text="Generate launcher files for:").pack(pady=10)

    Button(root, text="Daijishō", width=28,
           command=lambda: choose_and_run("daijishou")).pack(pady=4)
    Button(root, text="ES-DE",   width=28,
           command=lambda: choose_and_run("esde")).pack(pady=4)

    root.mainloop()


if __name__ == "__main__":
    main()
