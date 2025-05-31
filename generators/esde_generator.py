#!/usr/bin/env python3
from tkinter import messagebox
from utils import sanitize, open_directory

def generate_esde(app_map, host_uuid, host_name, out_dir):
    """Generate ES-DE launcher files (.artes format)."""
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