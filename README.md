# ApolloLauncherExport

A Python script to generate launcher files for [Pegasus Frontend](https://pegasus-frontend.org/), [Daijishō](https://github.com/TapiocaFox/Daijishou) (Android) and [ES-DE](https://www.es-de.org/) (EmulationStation Desktop Edition) to stream PC games via [Apollo](https://github.com/ClassicOldSong/Apollo). Artemis is used as the client (referred to as Apollo/Artemis in this script's context for the client-side launchers it generates).

This script reads your Apollo server's application list and host details to create the necessary files for these frontends, enabling a seamless game launching experience. **This script is specifically for Apollo and Artemis and does not support the original Sunshine and Moonlight.**

## Features

*   Generates `.artp` files and `metadata.pegasus.txt` for Pegasus Frontend, together with app image(if defined).
*   Generates `.art` files (per-game launcher files) and an `Artemis.json` platform/player configuration file for Daijishō.
*   Generates `.artes` files (per-game launcher files), an `Apollo.uuid` (host UUID file), `es_systems.xml` (system configuration), and `es_find_rules.xml` (emulator configuration) for ES-DE.
*   Parses Apollo server's `apps.json` and `sunshine_state.json` from `sunshine.conf` file.
*   Provides a basic graphical user interface (GUI) to select the configuration file and choose the target frontend (Daijishō or ES-DE).
*   Outputs organized files into an `export/<frontend_name>/<host_name>/` directory.

## Requirements

* Download from [Releases](https://github.com/ClassicOldSong/ApolloLauncherExport/releases)

or

*   Python 3.8+
*   Standard Python libraries only (tkinter, configparser, json, shutil, pathlib). No external packages are needed.
*   [Apollo server](https://github.com/ClassicOldSong/Apollo) installed and configured on your host PC.
*   [Artemis](https://github.com/ClassicOldSong/moonlight-android) installed on the device running Daijishō or ES-DE (if ES-DE is on Android).

## Setup

### 1. Prepare Apollo Configuration

This script needs to know where your Apollo server's `apps.json` and `sunshine_state.json` files are located. The script will prompt you to choose the `sunshine.conf` file to read the configs automatically.

### 2. Run the Script

1.  Download or clone `export.py`.
2.  Run the script: `python export.py`
    *   If you have a PyInstaller-compiled `.exe` version, simply run the executable.
3.  A small GUI window titled "Apollo Launcher Export" will appear.

### 3. Generate Launcher Files

1.  In the GUI, click either the "Daijishō" or "ES-DE" button, depending on which frontend you want to generate files for.
2.  A file dialog will prompt you to "Select Apollo config file (sunshine.conf)". Select the helper `.conf` file you created in Step 1 (e.g., `myapollo.conf`).
3.  The script will process your Apollo server data and create the launcher files.
    *   Output directory: `export/<frontend_name>/<your_apollo_host_name>/` (e.g., `export/daijishou/My Gaming PC/` where "My Gaming PC" is your `sunshine_name` from the .conf)
    *   A confirmation message ("Done! Daijishō files (.art) created!" or "Done! ES-DE files (.artes) created!") will appear.

## Frontend Configuration

### Pegasus Frontend

*   Run the script and select "Pegasus".
*   Select your `sunshine.conf` file.
*   A new folder will be created under `export/pegasus/<Your Host Name>/`.
*   This folder contains:
    *   `metadata.pegasus.txt`: This is the main metadata file for Pegasus. It defines a collection for your streamed games, using your computer's name (from `sunshine.conf`) as the collection title. It also lists all your games and links them to their respective `.artp` files.
    *   A series of `.artp` files, one for each game, named with the game's UUID (e.g., `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.artp`). Each file contains the game's name and its UUID. Pegasus uses the UUID from the filename (`{file.basename}`) to launch the game via Moonlight.
*   **Setup in Pegasus Frontend:**
    1.  Copy the generated folder (e.g., `<Your Host Name>`) into one of your Pegasus game directories.
    2.  In Pegasus, go to `Settings` -> `Set game directories` and ensure the path to this folder (or its parent) is added.
    3.  Pegasus should now find your games. The launch command is configured to use `am start` to launch Moonlight directly with the correct host and game UUIDs.

### Daijishō

The script generates an `Artemis.json` platform file and multiple `*.art` files (one for each game).

1.  **Transfer Files**:
    *   Copy the generated `Artemis.json` file.
    *   Copy all the `*.art` files from the output directory (e.g., `export/daijishou/My Gaming PC/`) to a folder on your Android device (e.g., `/sdcard/Roms/Artemis/`).

2.  **Import Platform in Daijishō**:
    *   Open Daijishō.
    *   Go to `Settings` > `Library` > `Import platform`.
    *   Navigate to and select the `Artemis.json` file you copied to your device.
    *   This step is similar to adding a platform manually as described in the [Daijishō Wiki - Adding Platforms (Manually)](https://github.com/TapiocaFox/Daijishou/wiki/How-to-Use-Daijish%C5%8D#adding-platforms-manually). The `Artemis.json` file *is* your platform definition, pre-configured by the script.

3.  **Sync Games**:
    *   After importing, you need to sync paths for the new "Artemis" (or your `sunshine_name`) platform.
    *   Set the path to the folder where you copied the `*.art` files (e.g., `/sdcard/Roms/Artemis/`).
    *   Sync the platform. Your Apollo server games should now appear under this platform.

4.  **How it Works**:
    *   The `Artemis.json` file defines a new platform and a "player" that uses the Artemis Android app (`com.limelight.noir`).
    *   The player is configured with arguments to launch specific games using the host UUID (from your Apollo server's `sunshine_state.json`) and an application UUID.
    *   Each `.art` file is a simple text file containing:
        ```
        # Daijishou Player Template
        [app_uuid] YOUR_GAME_APP_UUID
        ```
        Daijishō reads the `app_uuid` tag from these files and passes it to the Moonlight client, similar to how `.moonlight` files work for direct Moonlight game streaming as described in the [Daijishō Wiki - Moonlight](https://github.com/TapiocaFox/Daijishou/wiki/How-to-Use-Daijish%C5%8D#adding-moonlight-platform) section. This script automates the creation of these files based on your Apollo server setup.

5.  **Ensure Artemis is Installed**: The Artemis client (package `com.limelight.noir`) must be installed on your Android device for the launchers to work.

### ES-DE

Untested

## License

This project is licensed under the MIT License.
