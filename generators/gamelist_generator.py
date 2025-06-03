import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path
from datetime import datetime
from utils import sanitize_filename

def _generate_gamelist_xml(app_map, all_game_fetch_results, out_dir, file_extension, system_name):
    """
    Generates a gamelist.xml file for EmulationStation-based frontends.

    Args:
        app_map (dict): The map of applications.
        all_game_fetch_results (dict): Cache of all fetch results for each game UUID.
                                       Expected structure: {uuid: {"text_data": {...}, 
                                       "downloaded_steamgriddb_assets": {...}, 
                                       "downloaded_igdb_assets": {...}}}
        out_dir (Path): The output directory to save gamelist.xml.
        file_extension (str): The file extension for game paths (e.g., ".art").
        system_name (str): The name of the system/platform for the gamelist.
    """
    root_el = ET.Element("gameList")

    provider_el = ET.SubElement(root_el, "provider")
    ET.SubElement(provider_el, "System").text = system_name
    ET.SubElement(provider_el, "software").text = "ApolloLauncherExport"
    ET.SubElement(provider_el, "database").text = "IGDB.com / SteamGridDB.com"
    ET.SubElement(provider_el, "web").text = "https://www.igdb.com / https://www.steamgriddb.com"

    for name, game_data_from_app_map in app_map.items():
        uuid = game_data_from_app_map["uuid"]
        game_el = ET.SubElement(root_el, "game")
        
        filename = f"{sanitize_filename(name)}{file_extension}"
        ET.SubElement(game_el, "path").text = f"./{filename}"
        ET.SubElement(game_el, "name").text = name

        # Default empty elements for all fields based on example
        ET.SubElement(game_el, "desc")
        ET.SubElement(game_el, "image")       # For boxart/cover (e.g., ./media/images/gamename.png)
        ET.SubElement(game_el, "thumbnail")   # Often same as image or smaller version
        ET.SubElement(game_el, "video")       # For video previews (e.g., ./media/videos/gamename.mp4)
        ET.SubElement(game_el, "rating")      # Decimal rating (e.g., 0.75)
        ET.SubElement(game_el, "releasedate") # Format YYYYMMDDTHHMMSS
        ET.SubElement(game_el, "developer")
        ET.SubElement(game_el, "publisher")
        ET.SubElement(game_el, "genre")
        ET.SubElement(game_el, "players")
        # Optional: <marquee>, <lastplayed>, <playcount>, <genreid>

        game_fetch_result = all_game_fetch_results.get(uuid)
        text_data = None
        if game_fetch_result and game_fetch_result.get("text_data"):
            text_data = game_fetch_result["text_data"]

        if text_data:
            if text_data.get("summary"):
                game_el.find("desc").text = text_data["summary"]
            
            if text_data.get("rating") is not None:
                try:
                    rating_val = float(text_data["rating"]) / 100.0
                    game_el.find("rating").text = f"{rating_val:.2f}"
                except (ValueError, TypeError):
                    pass 

            if text_data.get("release_date"): # Expected as 'YYYY-MM-DD ...'
                try:
                    release_date_str = str(text_data["release_date"]).split(" ")[0]
                    dt_obj = datetime.strptime(release_date_str, "%Y-%m-%d")
                    game_el.find("releasedate").text = dt_obj.strftime("%Y%m%dT000000")
                except (ValueError, TypeError):
                    pass

            def _get_comma_separated_string(data_list):
                if isinstance(data_list, list):
                    return ", ".join(str(item).strip() for item in data_list if str(item).strip())
                elif isinstance(data_list, str):
                    return data_list.strip()
                return None

            if text_data.get("developer"):
                dev_text = _get_comma_separated_string(text_data["developer"])
                if dev_text: game_el.find("developer").text = dev_text
            
            if text_data.get("publisher"):
                pub_text = _get_comma_separated_string(text_data["publisher"])
                if pub_text: game_el.find("publisher").text = pub_text

            if text_data.get("genre"):
                genre_text = _get_comma_separated_string(text_data["genre"])
                if genre_text: game_el.find("genre").text = genre_text
            
            player_str_list = []
            if text_data.get("game_modes") and isinstance(text_data["game_modes"], list):
                # Simplified player count based on game modes
                if "Single player" in text_data["game_modes"]:
                    player_str_list.append("1")
                if any(m in text_data["game_modes"] for m in ["Multiplayer", "Co-operative", "Split screen"]):
                    player_str_list.append("2+") # General indicator for multiplayer
            
            if player_str_list:
                # Ensure "1" comes before "2+" if both exist, and avoid duplicates like "1, 1"
                unique_players = sorted(list(set(player_str_list)))
                game_el.find("players").text = ", ".join(unique_players)


        # Handle image paths from fetch results
        if game_fetch_result:
            s_g_d_b_assets = game_fetch_result.get("downloaded_steamgriddb_assets", {})
            i_g_d_b_assets = game_fetch_result.get("downloaded_igdb_assets", {})

            # image_path_to_use: relative to gamelist.xml (e.g., ./media/images/filename.png)
            # Assumes assets are saved like: out_dir / "media" / "images" / "sanitized_name.ext"
            
            image_path_str = None
            # Priority: SGDB 'steam' (grid), then IGDB 'boxFront' (cover)
            if s_g_d_b_assets.get("steam"): # Saved to media/images/
                image_path_str = f"./media/images/{Path(s_g_d_b_assets['steam']).name}"
            elif i_g_d_b_assets.get("boxFront"): # Saved to media/images/
                image_path_str = f"./media/images/{Path(i_g_d_b_assets['boxFront']).name}"
            
            if image_path_str:
                game_el.find("image").text = image_path_str
                game_el.find("thumbnail").text = image_path_str # Use main image as thumbnail

            # Video path (if fetched, e.g., from SGDB 'video')
            # if s_g_d_b_assets.get("video"): # Example if videos were fetched to media/videos/
            #    video_path_str = f"./media/videos/{Path(s_g_d_b_assets['video']).name}"
            #    game_el.find("video").text = video_path_str


    xml_str = ET.tostring(root_el, encoding="utf-8", method="xml")
    parsed_xml = minidom.parseString(xml_str)
    pretty_xml_str = parsed_xml.toprettyxml(indent="  ", encoding="utf-8")

    gamelist_path = out_dir / "gamelist.xml"
    gamelist_path.write_bytes(pretty_xml_str)
    print(f"Generated gamelist.xml at {gamelist_path}") 