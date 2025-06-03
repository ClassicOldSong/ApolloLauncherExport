# ApolloLauncherExport

A Python script to generate launcher files for [Pegasus Frontend](https://pegasus-frontend.org/), [Daijishō](https://github.com/TapiocaFox/Daijishou) (Android), [ES-DE](https://www.es-de.org/) (EmulationStation Desktop Edition), and generic platforms to stream PC games via [Apollo](https://github.com/ClassicOldSong/Apollo). Artemis is used as the client (referred to as Apollo/Artemis in this script's context for the client-side launchers it generates).

This script reads your Apollo server's application list and host details to create the necessary files for these frontends, enabling a seamless game launching experience. **This script is specifically for Apollo and Artemis and does not support the original Sunshine and Moonlight.**

## Features

*   **Pegasus Frontend**: Generates `.art` files and `metadata.pegasus.txt` with app images and enhanced metadata support.
*   **Daijishō**: Generates `.art` files and an `Artemis.json` platform/player configuration file.
*   **ES-DE**: Generates `.art` files, an `Apollo.uuid` (host UUID file), `es_systems.xml` (system configuration), and `es_find_rules.xml` (emulator configuration).
*   **Generic Platform**: Generates basic launcher files for custom or unsupported frontends.
*   **Enhanced metadata and asset fetching** (available for Pegasus, Daijishō, and ES-DE):
    *   Fetches game assets (logos, grid images, marquees, tiles) from [SteamGridDB](https://www.steamgriddb.com/)
    *   Fetches rich game metadata (summaries, descriptions, ratings, genres, release dates, developers, publishers) from [IGDB.com](https://www.igdb.com/)
    *   Downloads and organizes media assets into appropriate directory structures for each frontend
    *   Enriches metadata files with detailed game information for better frontend presentation
*   Parses Apollo server's `apps.json` and `sunshine_state.json` from `sunshine.conf` file.
*   Provides a graphical user interface (GUI) to select configuration files, choose target frontends, and configure scraping options.
*   **Smart asset management**: Skips image fetching for existing ROM files while still updating metadata when "Skip existing" option is enabled.
*   Outputs organized files into an `export/<frontend_name>/<host_name>/` directory.

## Requirements

* Download from [Releases](https://github.com/ClassicOldSong/ApolloLauncherExport/releases)

or

*   Python 3.8+
*   **Core dependencies** (for basic functionality):
    *   Standard Python libraries only (tkinter, configparser, json, shutil, pathlib). No external packages are needed for basic launcher generation.
*   **Enhanced features dependencies** (optional, for metadata and asset fetching):
    *   `requests` library: `pip install requests`
    *   `igdb-api-v4` library: `pip install igdb-api-v4`
    *   or simply `pip install -r requirements.txt`
*   [Apollo server](https://github.com/ClassicOldSong/Apollo) installed and configured on your host PC.
*   [Artemis](https://github.com/ClassicOldSong/moonlight-android) installed on the device running Daijishō or ES-DE (if ES-DE is on Android).

## API Setup (Optional - For Enhanced Features)

### SteamGridDB API Key

SteamGridDB provides high-quality game assets including logos, grid images, and artwork.

1. **Create a SteamGridDB account**: Visit [steamgriddb.com](https://www.steamgriddb.com/) and sign up for a free account.
2. **Navigate to API preferences**: Go to [SteamGridDB Preferences > API](https://www.steamgriddb.com/profile/preferences/api)
3. **Generate an API key**: Click "Generate API Key" to create your personal API key.
4. **Copy the API key**: Save this key - you'll enter it in the application's GUI.

**Features provided**: Game logos, grid images (steam format), marquees, and tile artwork for better visual presentation in Pegasus Frontend.

### IGDB API Credentials

IGDB (Internet Game Database) provides comprehensive game metadata including descriptions, ratings, and release information.

**Note**: IGDB uses Twitch's API infrastructure, so you'll need to create a Twitch application.

1. **Create a Twitch Developer account**: Visit [dev.twitch.tv](https://dev.twitch.tv/) and log in with your Twitch account (create one if needed).
2. **Navigate to Console**: Go to [Twitch Developer Console](https://dev.twitch.tv/console)
3. **Create a new application**:
   - Click "Register Your Application"
   - **Name**: Choose any name (e.g., "ApolloLauncherExport")
   - **OAuth Redirect URLs**: Enter `http://localhost` (required field, not used by this script)
   - **Category**: Select "Application Integration"
   - Click "Create"
4. **Get your credentials**:
   - **Client ID**: Copy the "Client ID" from your application page
   - **Client Secret**: Click "New Secret" to generate a client secret, then copy it
5. **Important**: The script will automatically fetch and manage the App Access Token using your Client ID and Secret.

**Features provided**: Game summaries, detailed descriptions, ratings, genres, release dates, developer/publisher information, and additional game metadata for richer Pegasus collections.

**API Documentation**: For more details, see [IGDB API Documentation](https://api-docs.igdb.com/#account-creation)

## Setup

### 1. Prepare Apollo Configuration

This script needs to know where your Apollo server's `apps.json` and `sunshine_state.json` files are located. The script will prompt you to choose the `sunshine.conf` file to read the configs automatically.

### 2. Configure API Keys (Optional)

For enhanced metadata and asset fetching:

1. **Run the script**: `python export.py`
2. **Set SteamGridDB API Key**: Click the "Set" button next to "SteamGridDB API Key" and enter your API key from the setup above.
3. **Set IGDB Credentials**: Click the "Set" button next to "IGDB Credentials" and enter your Client ID and Client Secret from the setup above.

**Note**: These steps are optional. The script works without API keys but will only generate basic launcher files without enhanced metadata or downloaded assets.

### 3. Run the Script

1.  Download or clone this project.
2.  Run the script: `python export.py`
    *   If you have a PyInstaller-compiled `.exe` version, simply run the executable.
3.  A GUI window titled "Apollo Launcher Export" will appear with your configured settings.

### 4. Generate Launcher Files

1.  **Choose options** (available for Pegasus, Daijishō, and ES-DE):
    *   Check "Download game assets from SteamGridDB" to fetch high-quality game images
    *   Check "Fetch game metadata from IGDB.com" to enrich your game collections with detailed information
    *   Check "Skip image fetching for existing ROM files" to speed up subsequent runs while still updating metadata
    *   **Note**: Generic platform generation does not support metadata and image fetching
2.  **Select frontend**: Click "Pegasus", "Daijishō", "ES-DE", or "Generic" button, depending on which frontend you want to generate files for.
3.  **Select Apollo config**: A file dialog will prompt you to "Select Apollo config file (sunshine.conf)". Select the helper `.conf` file you created in Step 1.
4.  The script will process your Apollo server data and create the launcher files.
    *   Output directory: `export/<frontend_name>/<your_apollo_host_name>/` (e.g., `export/pegasus/My Gaming PC/` where "My Gaming PC" is your `sunshine_name` from the .conf)
    *   A confirmation message will appear when complete.

## Frontend Configuration

### Pegasus Frontend

*   Run the script and select "Pegasus".
*   Select your `sunshine.conf` file.
*   A new folder will be created under `export/Pegasus/<Your Host Name>/`.
*   This folder contains:
    *   `metadata.pegasus.txt`: The main metadata file for Pegasus. It defines a collection for your streamed games, using your computer's name (from `sunshine.conf`) as the collection title. **Enhanced with rich metadata** from IGDB including game summaries, descriptions, ratings, genres, release dates, and developer information when API access is configured.
    *   A series of `.art` files, one for each game, named with the game's name. Each file contains the game's name and its UUID.
    *   **Media assets** (when SteamGridDB/IGDB is enabled): A `media/` directory containing subdirectories for each game with high-quality images:
        *   `steam` - Grid images from SteamGridDB
        *   `logo` - Game logos from SteamGridDB  
        *   `marqee` - Marquee images from SteamGridDB
        *   `tile` - Tile artwork from SteamGridDB
        *   `boxFront` - Cover art from IGDB (if not available from SteamGridDB)
        *   `screenshot` - Game screenshots from IGDB
        *   `background` - Background artwork from IGDB
*   **Setup in Pegasus Frontend:**
    1.  Copy the generated folder (e.g., `<Your Host Name>`) into one of your Pegasus game directories.
    2.  In Pegasus, go to `Settings` -> `Set game directories` and ensure the path to this folder (or its parent) is added.
    3.  Pegasus should now find your games with rich metadata and artwork. The launch command is configured to use `am start` to launch Moonlight directly with the correct host and game UUIDs.

### Daijishō

The script generates an `Artemis.json` platform file and multiple `*.art` files (one for each game). **Enhanced with metadata and asset fetching support.**

1.  **Transfer Files**:
    *   Copy the generated `Artemis.json` file.
    *   Copy all the `*.art` files from the output directory (e.g., `export/Daijishō/My Gaming PC/`) to a folder on your Android device (e.g., `/sdcard/Roms/Artemis/`).
    *   **If scraping was enabled**: Copy the `media/` directory containing game assets to your device alongside the `.art` files.

2.  **Import Platform in Daijishō**:
    *   Open Daijishō.
    *   Go to `Settings` > `Library` > `Import platform`.
    *   Navigate to and select the `Artemis.json` file you copied to your device.
    *   This step is similar to adding a platform manually as described in the [Daijishō Wiki - Adding Platforms (Manually)](https://github.com/TapiocaFox/Daijishou/wiki/How-to-Use-Daijish%C5%8D#adding-platforms-manually). The `Artemis.json` file *is* your platform definition, pre-configured by the script.

3.  **Sync Games**:
    *   After importing, you need to sync paths for the new "Artemis" (or your `sunshine_name`) platform.
    *   Set the path to the folder where you copied the `*.art` files (e.g., `/sdcard/Roms/Artemis/`).
    *   Sync the platform. Your Apollo server games should now appear under this platform with enhanced metadata and artwork if scraping was enabled.

4.  **Enhanced Features** (when scraping is enabled):
    *   Game assets are organized in a `media/` directory with subdirectories for each game
    *   Daijishō will automatically detect and display game artwork, logos, and screenshots
    *   Rich metadata is embedded in the platform configuration for better game information display

5.  **How it Works**:
    *   The `Artemis.json` file defines a new platform and a "player" that uses the Artemis Android app (`com.limelight.noir`).
    *   The player is configured with arguments to launch specific games using the file provided.

6.  **Ensure Artemis is Installed**: The Artemis client (package `com.limelight.noir`) must be installed on your Android device for the launchers to work.

### ES-DE

The script generates ES-DE configuration files and game launchers. **Enhanced with metadata and asset fetching support.**

1.  **Transfer Files**:
    *   Copy the entire generated folder (e.g., `export/ES-DE/My Gaming PC/`) to your ES-DE system.
    *   The folder contains:
        *   `es_systems.xml` - System configuration file
        *   `es_find_rules.xml` - Emulator configuration file  
        *   `Apollo.uuid` - Host UUID file for Apollo connection
        *   Individual `.artes` files for each game
        *   **If scraping was enabled**: `media/` directory with organized game assets

2.  **ES-DE Configuration**:
    *   Place the configuration files in your ES-DE configuration directory
    *   Set up the ROM directory to point to the folder containing the `.artes` files
    *   ES-DE will recognize the Apollo platform and display your games

3.  **Enhanced Features** (when scraping is enabled):
    *   Game assets are organized according to ES-DE's media structure
    *   Rich metadata is available for each game including descriptions, ratings, and release information
    *   High-quality artwork enhances the visual presentation in ES-DE

**Note**: ES-DE support is currently untested but follows the standard ES-DE configuration patterns.

### Generic Platform

The Generic option creates basic launcher files without frontend-specific formatting, suitable for custom integrations or unsupported frontends.

1.  **Generated Files**:
    *   Individual launcher files for each game (format depends on implementation)
    *   Basic game information without enhanced metadata or assets
    *   Host configuration details

2.  **Usage**:
    *   Use these files as a foundation for custom frontend integrations
    *   Adapt the launcher format to match your specific frontend requirements
    *   **Note**: Generic generation does not support metadata and image fetching

## License

This project is licensed under the MIT License.
