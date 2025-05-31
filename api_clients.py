import json
from datetime import datetime, timezone
import difflib
from tkinter import messagebox # For fetch_igdb_app_access_token

from utils import download_image # Replaced local download_image

# Attempt to import requests and IGDBWrapper, handling missing ones
try:
    import requests
except ImportError:
    print("Warning: 'requests' library not installed. API functionality will be limited.")
    requests = None

try:
    from igdb.wrapper import IGDBWrapper
    if not requests:
        raise ImportError("IGDBWrapper also needs 'requests' library.")
except ImportError:
    print("Warning: 'igdb-api-python' library not installed or 'requests' is missing. IGDB functionality will require setup.")
    IGDBWrapper = None

STEAMGRIDDB_API_URL = "https://www.steamgriddb.com/api/v2"
IGDB_API_URL = "https://api.igdb.com/v4" # Base URL for IGDB API v4

def fetch_steamgriddb_assets_for_game(game_name: str, api_key: str, results_queue, cancel_event) -> dict:
    """
    Fetches asset URLs for a game from SteamGridDB.
    Returns a dictionary with asset types and their download URLs and metadata.
    e.g., {"logo": {"url": "https://...", "filename": "logo.png", "headers": {...}}, ...}
    """
    if not requests or not api_key:
        if not requests:
            print("Skipping SteamGridDB fetch: 'requests' library not available.")
        if not api_key:
            print("Skipping SteamGridDB fetch: API key not provided to fetch_steamgriddb_assets_for_game.")
        return {}

    headers = {"Authorization": f"Bearer {api_key}"}
    fetched_assets_info = {} # To track what was fetched

    # 1. Search for game ID
    try:
        search_response = requests.get(f"{STEAMGRIDDB_API_URL}/search/autocomplete/{requests.utils.quote(game_name)}", headers=headers, timeout=10)
        search_response.raise_for_status()
        search_data = search_response.json()
        if not search_data.get("success") or not search_data.get("data"):
            print(f"Game not found on SteamGridDB: {game_name}")
            return {}
        game_id = search_data["data"][0]["id"] # Take the first result
    except requests.exceptions.RequestException as e:
        print(f"Error searching for game {game_name} on SteamGridDB: {e}")
        return {}
    except (IndexError, KeyError):
        print(f"No valid game ID found for {game_name} on SteamGridDB.")
        return {}

    asset_map = {
        "logo":   {"endpoint": f"/logos/game/{game_id}",  "filename": "logo.png",   "params": {}},
        "steam":  {"endpoint": f"/grids/game/{game_id}",  "filename": "steam.png",  "params": {"dimensions": "460x215,920x430,600x900,342x482,660x930", "types": "static", "mimes": "image/png"}},
        "marqee": {"endpoint": f"/heroes/game/{game_id}", "filename": "marqee.png", "params": {"types": "static", "mimes": "image/png"}},
        "tile":   {"endpoint": f"/grids/game/{game_id}",  "filename": "tile.png",   "params": {"dimensions": "512x512,1024x1024", "types": "static", "mimes": "image/png"}},
    }

    for asset_type_pegasus, details in asset_map.items():
        if cancel_event.is_set():
            print(f"[Thread] Cancellation detected before fetching {asset_type_pegasus} for {game_name}.")
            return fetched_assets_info

        results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"Fetching {asset_type_pegasus} URL..."})

        try:
            asset_response = requests.get(
                f"{STEAMGRIDDB_API_URL}{details['endpoint']}", 
                headers=headers, 
                params=details.get("params"),
                timeout=10
            )
            asset_response.raise_for_status()
            asset_data = asset_response.json()

            if asset_data.get("success") and asset_data.get("data"):
                asset_url = asset_data["data"][0]["url"]
                # Store URL and metadata for later download by generator
                fetched_assets_info[asset_type_pegasus] = {
                    "url": asset_url,
                    "filename": details["filename"],
                    "headers": headers  # Include headers for download
                }
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"{asset_type_pegasus} URL found."})
            else:
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"No {asset_type_pegasus} found."})
                print(f"No {asset_type_pegasus} found for {game_name} (ID: {game_id})")

        except requests.exceptions.RequestException as e:
            error_msg = f"Error fetching {asset_type_pegasus} for {game_name}: {e}"
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": error_msg})
            print(error_msg)
        except (IndexError, KeyError):
            error_msg = f"Could not parse {asset_type_pegasus} data for {game_name}."
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": error_msg})
            print(error_msg)
            
    return fetched_assets_info

def format_igdb_image_url(image_id: str, size_suffix: str = "t_cover_big") -> str:
    """Formats an IGDB image URL."""
    if not image_id:
        return ""
    return f"https://images.igdb.com/igdb/image/upload/{size_suffix}/{image_id}.jpg"

def fetch_igdb_metadata_for_game(game_name: str, client_id: str, app_access_token: str, 
                               results_queue, cancel_event, steamgriddb_fetched_assets: dict) -> dict | None:
    """
    Fetches detailed metadata for a game from IGDB.com.
    Returns a dictionary containing both textual metadata and image URLs for Pegasus, or None on failure.
    Image URLs are stored under an 'image_urls' key.
    """
    if not IGDBWrapper or not requests:
        print("Skipping IGDB fetch: 'igdb-api-python' or 'requests' library not available.")
        return None
    if not client_id or not app_access_token:
        print("Skipping IGDB fetch: Client ID or App Access Token not provided.")
        return None

    # Check for cancellation before starting
    if cancel_event.is_set():
        print(f"[Thread] Cancellation detected before starting IGDB fetch for {game_name}.")
        return None

    results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"Fetching IGDB metadata for {game_name}..."})
    
    wrapper = IGDBWrapper(client_id, app_access_token)
    pegasus_metadata = {}
    SIMILARITY_THRESHOLD = 0.7

    try:
        # Check for cancellation before API request
        if cancel_event.is_set():
            print(f"[Thread] Cancellation detected before IGDB API request for {game_name}.")
            return None

        api_query = (
            f'search "{game_name}"; '
            f"fields name, summary, storyline, total_rating, first_release_date, "
            f"genres.name, cover.image_id, artworks.image_id, screenshots.image_id, "
            f"involved_companies.company.name, involved_companies.developer, involved_companies.publisher, "
            f"game_modes.name, player_perspectives.name; "
            f"limit 5;"
        )
        
        json_byte_array_result = wrapper.api_request('games', api_query)
        games_data = json.loads(json_byte_array_result.decode('utf-8'))

        if not games_data:
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"No IGDB metadata found for {game_name}."})
            print(f"No IGDB metadata found for {game_name}.")
            return None

        # Check for cancellation after API request
        if cancel_event.is_set():
            print(f"[Thread] Cancellation detected after IGDB API request for {game_name}.")
            return None

        best_match_game = None
        highest_similarity_ratio = 0.0
        for igdb_game in games_data:
            if not igdb_game.get("name"):
                continue
            current_igdb_name = igdb_game["name"]
            if current_igdb_name.lower() == game_name.lower():
                best_match_game = igdb_game
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"IGDB: Exact match found - {current_igdb_name}"})
                break
            similarity = difflib.SequenceMatcher(None, game_name.lower(), current_igdb_name.lower()).ratio()
            if similarity > highest_similarity_ratio:
                highest_similarity_ratio = similarity
                best_match_game = igdb_game
        
        if not best_match_game:
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"IGDB: No suitable match found after checking {len(games_data)} results."})
            print(f"No suitable IGDB match found for {game_name} from {len(games_data)} results.")
            return None
        
        if highest_similarity_ratio < SIMILARITY_THRESHOLD and best_match_game["name"].lower() != game_name.lower():
            results_queue.put({"status": "asset_update", "game_name": game_name, 
                               "asset_info": f"IGDB: Best match '{best_match_game['name']}' ({highest_similarity_ratio:.2f}) below threshold for {game_name}."})
            print(f"IGDB: Best match for {game_name} was '{best_match_game['name']}' with similarity {highest_similarity_ratio:.2f}, which is below threshold {SIMILARITY_THRESHOLD}. Skipping.")
            return None
        
        # Check for cancellation before processing metadata
        if cancel_event.is_set():
            print(f"[Thread] Cancellation detected before processing IGDB metadata for {game_name}.")
            return None
        
        game_info = best_match_game
        results_queue.put({"status": "asset_update", "game_name": game_name, 
                           "asset_info": f"IGDB: Selected match '{game_info['name']}' (Similarity: {highest_similarity_ratio if highest_similarity_ratio > 0 else 'Exact'})."})

        if game_info.get("name"):
            pegasus_metadata["game"] = game_info["name"]
        if game_info.get("summary"):
            pegasus_metadata["summary"] = game_info["summary"]
        if game_info.get("storyline"):
            pegasus_metadata["description"] = game_info["storyline"]
        if game_info.get("total_rating") is not None:
            pegasus_metadata["rating"] = f"{int(round(game_info['total_rating']))}%"
        if game_info.get("first_release_date"):
            try:
                release_timestamp = int(game_info["first_release_date"])
                pegasus_metadata["release"] = datetime.fromtimestamp(release_timestamp, timezone.utc).strftime('%Y-%m-%d')
            except ValueError:
                print(f"Could not parse release date for {game_name}")
        if game_info.get("genres"):
            pegasus_metadata["genre"] = ", ".join([genre["name"] for genre in game_info["genres"] if genre.get("name")])

        developers = []
        publishers = []
        if game_info.get("involved_companies"):
            for company_info in game_info["involved_companies"]:
                comp_name = company_info.get("company", {}).get("name")
                if not comp_name: continue
                if company_info.get("developer"): developers.append(comp_name)
                if company_info.get("publisher"): publishers.append(comp_name)
        if developers: pegasus_metadata["developer"] = ", ".join(developers)
        if publishers: pegasus_metadata["publisher"] = ", ".join(publishers)

        tags = []
        if game_info.get("game_modes"):
            tags.extend([mode["name"] for mode in game_info["game_modes"] if mode.get("name")])
        if game_info.get("player_perspectives"):
            tags.extend([pp["name"] for pp in game_info["player_perspectives"] if pp.get("name")])
        if tags: pegasus_metadata["tags"] = ", ".join(list(set(tags)))

        # Check for cancellation before gathering image URLs
        if cancel_event.is_set():
            print(f"[Thread] Cancellation detected before gathering IGDB image URLs for {game_name}.")
            return pegasus_metadata  # Return metadata even if we can't get image URLs

        # Store image URLs for later download by generator
        image_urls = {}
        
        # Check if we should skip image fetching entirely
        if "_skip_images" in steamgriddb_fetched_assets:
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "IGDB: Skipping image fetching for existing ROM file."})
            # Return only textual metadata, no image URLs
            return pegasus_metadata
        
        # Check if SteamGridDB already has cover-like assets
        has_steamgriddb_boxfront = False
        steamgriddb_boxfront_keys = ["steam", "boxFront"]
        for sgdb_key in steamgriddb_boxfront_keys:
            if sgdb_key in steamgriddb_fetched_assets:
                has_steamgriddb_boxfront = True
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"IGDB: Skipping boxFront URL, SteamGridDB {sgdb_key} available."})
                break
        
        if not has_steamgriddb_boxfront and game_info.get("cover") and game_info["cover"].get("image_id"):
            cover_url = format_igdb_image_url(game_info["cover"]["image_id"], "t_cover_big")
            image_urls["boxFront"] = {"url": cover_url, "filename": "boxFront.jpg"}
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "IGDB: boxFront URL found."})
        
        if game_info.get("screenshots") and game_info["screenshots"][0].get("image_id"):
            ss_url = format_igdb_image_url(game_info["screenshots"][0]["image_id"], "t_screenshot_big")
            image_urls["screenshot"] = {"url": ss_url, "filename": "screenshot.jpg"}
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "IGDB: screenshot URL found."})

        if game_info.get("artworks") and game_info["artworks"][0].get("image_id"):
            art_url = format_igdb_image_url(game_info["artworks"][0]["image_id"], "t_1080p")
            image_urls["background"] = {"url": art_url, "filename": "background.jpg"}
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "IGDB: background URL found."})
        
        if image_urls:
            pegasus_metadata["image_urls"] = image_urls
        
        if not pegasus_metadata:
             results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"No useful metadata from IGDB for {game_name}."})
             return None

        results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"IGDB metadata processed for {game_name}."})
        return pegasus_metadata

    except requests.exceptions.RequestException as e:
        error_msg = f"IGDB API request error for {game_name}: {e}"
        results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": error_msg})
        print(error_msg)
        return None
    except json.JSONDecodeError as e:
        error_msg = f"Error decoding IGDB JSON response for {game_name}: {e}"
        results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": error_msg})
        print(error_msg)
        return None
    except (IndexError, KeyError) as e:
        error_msg = f"Could not parse IGDB data for {game_name} (IndexError/KeyError): {e}"
        results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": error_msg})
        print(error_msg)
        return None
    except Exception as e:
        error_msg = f"An unexpected error occurred fetching IGDB data for {game_name}: {e}"
        results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": error_msg})
        print(error_msg)
        return None

def check_steamgriddb_key_validity(api_key: str) -> bool:
    """Checks if the SteamGridDB API key is valid by making a test call."""
    if not requests or not api_key:
        return False
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        # Use a simple, non-existent game search to check auth without hitting rate limits on real searches.
        response = requests.get(f"{STEAMGRIDDB_API_URL}/search/autocomplete/thisgameprobablydoesnotexist", headers=headers, timeout=5)
        if response.status_code == 200: # OK
            print("SteamGridDB API Key appears valid.")
            return True
        elif response.status_code == 401: # Unauthorized
            print("SteamGridDB API Key is invalid (Unauthorized).")
            return False
        else:
            print(f"SteamGridDB API Key validation failed with status: {response.status_code}")
            return False # Or True depending on how strict we want to be for other errors
    except requests.exceptions.RequestException as e:
        print(f"Error during SteamGridDB API Key validation: {e}")
        return False

def check_igdb_token_validity(client_id: str, token: str) -> bool:
    """Checks if the IGDB App Access Token is valid by making a test call."""
    if not requests or not client_id or not token or not IGDBWrapper:
        print("Skipping IGDB token validation: prerequisites missing.")
        return False
    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {token}",
    }
    try:
        # A simple count query to test the token without fetching large data
        response = requests.post(f"{IGDB_API_URL}/games/count", headers=headers, data="fields id;", timeout=5)
        if response.status_code == 200:
            print("IGDB App Access Token appears valid.")
            return True
        elif response.status_code == 401 or response.status_code == 403: # Unauthorized or Forbidden
            print(f"IGDB App Access Token is invalid (Status: {response.status_code}).")
            return False
        else:
            # Log other status codes for debugging, treat as failure for token validity
            print(f"IGDB Token validation failed. Status: {response.status_code}, Response: {response.text[:200]}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Error during IGDB token validation: {e}")
        return False

def fetch_igdb_app_access_token(client_id: str, client_secret: str):
    """Fetches an IGDB App Access Token from Twitch."""
    if not requests:
        messagebox.showerror("Error", "The 'requests' library is required to fetch IGDB token.")
        return None
    if not client_id or not client_secret:
        messagebox.showerror("Input Error", "Client ID and Client Secret are required to fetch IGDB token.")
        return None
    
    token_url = "https://id.twitch.tv/oauth2/token"
    params = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials"
    }
    try:
        response = requests.post(token_url, params=params, timeout=10)
        response.raise_for_status() # Raises HTTPError for bad responses (4XX or 5XX)
        token_data = response.json()
        access_token = token_data.get("access_token")
        if access_token:
            print("Successfully fetched IGDB App Access Token.")
            return access_token
        else:
            # This case might be covered by raise_for_status if the error is an HTTP error code
            # but good to have if the response is 200 but token is missing for some reason.
            error_message = token_data.get('message', 'Unknown error: Access token not in response.')
            messagebox.showerror("Token Fetch Error", f"Could not retrieve access token: {error_message}")
            return None
    except requests.exceptions.HTTPError as e:
        error_details = "Unknown error."
        try:
            # Attempt to parse JSON error response from Twitch
            error_details = e.response.json().get('message', e.response.text) 
        except json.JSONDecodeError:
            error_details = e.response.text # Fallback to raw text if not JSON
        messagebox.showerror("Token Fetch Error", f"HTTP {e.response.status_code}: {error_details}")
        return None
    except requests.exceptions.RequestException as e:
        # Covers network errors, timeouts, etc.
        messagebox.showerror("Token Fetch Error", f"Request error while fetching IGDB token: {e}")
        return None

if __name__ == '__main__':
    # Example usage (requires requests and valid API keys/credentials to test fully)
    print("api_clients.py executed as main script - for testing purposes.")
    
    # Test SteamGridDB Key Check (replace with a real key to test)
    # if requests:
    #     test_sgdb_key = "YOUR_STEAMGRIDDB_API_KEY"
    #     if test_sgdb_key != "YOUR_STEAMGRIDDB_API_KEY":
    #         print(f"Testing SteamGridDB Key Validity for: {test_sgdb_key[:4]}...{test_sgdb_key[-4:] if len(test_sgdb_key) > 8 else ''}")
    #         is_valid_sgdb = check_steamgriddb_key_validity(test_sgdb_key)
    #         print(f"SteamGridDB Key Valid: {is_valid_sgdb}")
    #     else:
    #         print("Please replace YOUR_STEAMGRIDDB_API_KEY with an actual key to test.")
    # else:
    #     print("'requests' library not found, skipping SteamGridDB key check test.")

    # Test IGDB Token Fetch & Check (replace with real credentials to test)
    # if requests and IGDBWrapper:
    #     test_igdb_client_id = "YOUR_IGDB_CLIENT_ID"
    #     test_igdb_client_secret = "YOUR_IGDB_CLIENT_SECRET"
    #     if test_igdb_client_id != "YOUR_IGDB_CLIENT_ID" and test_igdb_client_secret != "YOUR_IGDB_CLIENT_SECRET":
    #         print(f"Attempting to fetch IGDB token for Client ID: {test_igdb_client_id}")
    #         token = fetch_igdb_app_access_token(test_igdb_client_id, test_igdb_client_secret)
    #         if token:
    #             print(f"Fetched IGDB Token: {token[:10]}...")
    #             print("Testing IGDB Token Validity...")
    #             is_valid_igdb = check_igdb_token_validity(test_igdb_client_id, token)
    #             print(f"IGDB Token Valid: {is_valid_igdb}")
    #         else:
    #             print("Failed to fetch IGDB token.")
    #     else:
    #         print("Please replace YOUR_IGDB_CLIENT_ID and YOUR_IGDB_CLIENT_SECRET with actual credentials to test.")
    # elif not requests:
    #     print("'requests' library not found, skipping IGDB token fetch/check test.")
    # elif not IGDBWrapper:
    #     print("'igdb-api-python' library not found, skipping IGDB token fetch/check test.")

    # Note: `fetch_steamgriddb_assets_for_game` and `fetch_igdb_metadata_for_game` require a running Tkinter loop
    # for their `results_queue` if used as in the original script, or need to be adapted for non-GUI testing.
    pass 