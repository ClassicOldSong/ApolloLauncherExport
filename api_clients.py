import json
from datetime import datetime, timezone
import difflib
from tkinter import messagebox # For fetch_igdb_app_access_token
from pathlib import Path # Added
from dataclasses import dataclass, field # Added
import threading # Added for execute_fetch_plan
import queue # Added for execute_fetch_plan

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

@dataclass
class FetchJob:
    game_name: str
    game_uuid: str # Will be used as the primary key for results
    steamgriddb_assets: dict[str, Path] = field(default_factory=dict) # e.g., {"logo": Path("media/logo/MyGame")}
    fetch_igdb_text_metadata: bool = True
    igdb_assets: dict[str, Path] = field(default_factory=dict) # e.g., {"boxFront": Path("media/box2dfront/MyGame")}
    skip_images: bool = False


class MetadataFetcher:
    def __init__(self, steamgriddb_api_key=None, igdb_client_id=None, igdb_app_access_token=None):
        self.steamgriddb_api_key = steamgriddb_api_key
        self.igdb_client_id = igdb_client_id
        self.igdb_app_access_token = igdb_app_access_token
        self.requests = requests 
        self.IGDBWrapper = IGDBWrapper

    def _download_asset(self, asset_url: str, output_path: Path, asset_name: str, game_name: str, results_queue, headers: dict = None, source: str = "Generic") -> Path | None:
        """Downloads an asset, reports progress, and returns the local path."""

        results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"{source}: Downloading {asset_name} to {output_path.name}..."})
        
        if download_image(asset_url, output_path, headers=headers):
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"{source}: {asset_name} ({output_path.name}) downloaded."})
            return output_path
        else:
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"{source}: Failed to download {asset_name} ({output_path.name})."})
            return None

    def _fetch_steamgriddb_asset_urls(self, game_name: str, game_id: int, desired_asset_keys: list[str], results_queue, cancel_event) -> dict:
        """
        Internal helper to fetch URLs for specified SteamGridDB asset types.
        Returns a dictionary like: {"logo": {"url": "...", "headers": {...}, "original_extension": ".png"}, ...}
        The `desired_asset_keys` is a list of keys like ["logo", "steam"].
        """
        if not self.requests or not self.steamgriddb_api_key:
            return {} # Should have been checked before calling this

        headers = {"Authorization": f"Bearer {self.steamgriddb_api_key}"}
        fetched_urls_info = {}

        # Mapping from our desired_assets keys to SGDB endpoints/filenames
        asset_map_sgdb = {
            "logo":   {"endpoint": f"/logos/game/{game_id}",  "params": {}},
            "steam":  {"endpoint": f"/grids/game/{game_id}",  "params": {"dimensions": "460x215,920x430,600x900,342x482,660x930", "types": "static", "mimes": "image/png,image/jpeg"}},
            "hero":   {"endpoint": f"/heroes/game/{game_id}", "params": {"types": "static", "mimes": "image/png,image/jpeg"}},
            "tile":   {"endpoint": f"/grids/game/{game_id}",  "params": {"dimensions": "512x512,1024x1024", "types": "static", "mimes": "image/png,image/jpeg"}},
        }

        for asset_type_key in desired_asset_keys:
            if asset_type_key not in asset_map_sgdb:
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"SteamGridDB: Unknown asset type '{asset_type_key}' requested."})
                continue

            if cancel_event.is_set():
                print(f"[SGDB URL Fetch] Cancellation for {game_name} before {asset_type_key}.")
                break # Stop fetching more URLs for this game

            details = asset_map_sgdb[asset_type_key]
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"SteamGridDB: Fetching {asset_type_key} URL..."})

            try:
                asset_response = self.requests.get(
                    f"{STEAMGRIDDB_API_URL}{details['endpoint']}",
                    headers=headers,
                    params=details.get("params"),
                    timeout=10
                )
                asset_response.raise_for_status()
                asset_data = asset_response.json()

                if asset_data.get("success") and asset_data.get("data"):
                    asset_url = asset_data["data"][0]["url"]
                    # Determine extension
                    original_extension = ".png" # Default
                    if "mimes" in details["params"]:
                        if "image/jpeg" in details["params"]["mimes"] and asset_url.lower().endswith(".jpg"):
                            original_extension = ".jpg"
                        elif "image/png" in details["params"]["mimes"] and asset_url.lower().endswith(".png"):
                            original_extension = ".png"
                        # Add more specific mime-to-extension logic if needed based on actual URL or content-type if SGDB provided it
                    
                    # Less reliably, try to get from URL if not obvious from mimes
                    parsed_extension = Path(asset_url).suffix.lower()
                    if parsed_extension in [".jpg", ".jpeg", ".png", ".webp"]:
                        original_extension = parsed_extension

                    fetched_urls_info[asset_type_key] = {
                        "url": asset_url,
                        "headers": headers, # Needed for download by the generic downloader
                        "original_extension": original_extension
                    }
                    results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"SteamGridDB: {asset_type_key} URL found ({original_extension})."})
                else:
                    results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"SteamGridDB: No {asset_type_key} found."})
            except self.requests.exceptions.RequestException as e:
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"SteamGridDB: Error fetching {asset_type_key} URL: {e}"})
            except (IndexError, KeyError):
                results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"SteamGridDB: Could not parse {asset_type_key} data."})
        
        return fetched_urls_info

    def _fetch_igdb_data(self, game_name: str, game_info_from_search:dict, fetch_text: bool, desired_igdb_asset_map: dict[str, Path], 
                         skip_images: bool,
                         results_queue, cancel_event) -> dict:
        """
        Internal helper to process a found IGDB game for metadata and image URLs.
        Downloads images if not skipped.
        Returns a dict with 'text_data' and 'downloaded_images' (paths).
        'game_info_from_search' is the validated game object from the initial IGDB search.
        `desired_igdb_asset_map` is like {"boxFront": Path("media/box2dfront/MyGameBaseName")}
        """
        if not self.IGDBWrapper or not self.requests or not self.igdb_client_id or not self.igdb_app_access_token:
            return {"text_data": {}, "downloaded_images": {}} # Should be checked before calling

        final_igdb_data = {"text_data": {}, "downloaded_images": {}}
        game_info = game_info_from_search # Already validated best match

        if cancel_event.is_set(): return final_igdb_data

        # --- Textual Metadata ---
        if fetch_text:
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "IGDB: Processing text metadata..."})
            pegasus_metadata = {}
            if game_info.get("name"): pegasus_metadata["game"] = game_info["name"] # Usually already have this
            if game_info.get("summary"): pegasus_metadata["summary"] = game_info["summary"]
            if game_info.get("storyline"): pegasus_metadata["description"] = game_info["storyline"] # Pegasus uses description
            if game_info.get("total_rating") is not None: pegasus_metadata["rating"] = f"{int(round(game_info['total_rating']))}%"
            if game_info.get("first_release_date"):
                try:
                    pegasus_metadata["release"] = datetime.fromtimestamp(int(game_info["first_release_date"]), timezone.utc).strftime('%Y-%m-%d')
                except ValueError: pass # ignore if unparseable
            if game_info.get("genres"): pegasus_metadata["genre"] = ", ".join([g["name"] for g in game_info["genres"] if g.get("name")])
            
            devs, pubs = [], []
            if game_info.get("involved_companies"):
                for ic in game_info["involved_companies"]:
                    comp_name = ic.get("company", {}).get("name")
                    if not comp_name: continue
                    if ic.get("developer"): devs.append(comp_name)
                    if ic.get("publisher"): pubs.append(comp_name)
            if devs: pegasus_metadata["developer"] = ", ".join(devs)
            if pubs: pegasus_metadata["publisher"] = ", ".join(pubs)

            tags = []
            if game_info.get("game_modes"): tags.extend([m["name"] for m in game_info["game_modes"] if m.get("name")])
            if game_info.get("player_perspectives"): tags.extend([p["name"] for p in game_info["player_perspectives"] if p.get("name")])
            if tags: pegasus_metadata["tags"] = ", ".join(list(set(tags)))
            
            final_igdb_data["text_data"] = pegasus_metadata
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "IGDB: Text metadata processed."})

        if cancel_event.is_set(): return final_igdb_data

        # --- Image URLs and Downloads ---
        if desired_igdb_asset_map and not skip_images:
            results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "IGDB: Processing images..."})
            igdb_image_map_fields = {
                # Our key : { igdb_field, igdb_size_suffix }
                "boxFront": {"field": "cover", "image_id_key": "image_id", "size": "t_cover_big"},
                "screenshot": {"field": "screenshots", "image_id_key": "image_id", "size": "t_screenshot_big"},
                "background": {"field": "artworks", "image_id_key": "image_id", "size": "t_1080p"}
            }

            for asset_key, base_output_path in desired_igdb_asset_map.items(): # base_output_path is Path object without extension
                if cancel_event.is_set(): break
                if asset_key not in igdb_image_map_fields:
                    results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"IGDB: Unknown asset type '{asset_key}' requested."})
                    continue

                img_details = igdb_image_map_fields[asset_key]
                image_id = None

                if img_details["field"] in game_info:
                    if isinstance(game_info[img_details["field"]], list) and game_info[img_details["field"]]:
                        # Handle lists like screenshots, artworks - take the first one
                        image_id = game_info[img_details["field"]][0].get(img_details["image_id_key"])
                    elif isinstance(game_info[img_details["field"]], dict):
                        # Handle single objects like cover
                        image_id = game_info[img_details["field"]].get(img_details["image_id_key"])
                
                if image_id:
                    img_url = self.format_igdb_image_url(image_id, img_details["size"])
                    # IGDB images are typically jpg. The base_output_path from job already has dir and basename.
                    output_file_path_with_ext = base_output_path.with_suffix(".jpg") 
                    output_file_path_with_ext.parent.mkdir(parents=True, exist_ok=True) # Ensure directory exists
                    
                    downloaded_path = self._download_asset(img_url, output_file_path_with_ext, asset_key, game_name, results_queue, source="IGDB")
                    if downloaded_path:
                        final_igdb_data["downloaded_images"][asset_key] = downloaded_path
                else:
                    results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": f"IGDB: No image ID found for {asset_key}."})
        elif skip_images:
             results_queue.put({"status": "asset_update", "game_name": game_name, "asset_info": "IGDB: Image fetching skipped for this game (job setting)."})

        return final_igdb_data

    def execute_fetch_plan(self, fetch_jobs: list[FetchJob], results_queue, cancel_event, root_ui_for_dialog=None):
        """
        Executes a list of FetchJobs. Manages threading for a responsive UI if root_ui_for_dialog is provided.
        Puts progress and results onto results_queue.
        Final message on queue: {"status": "fetch_plan_complete", "all_results": { uuid: {game_name, text_data, downloaded_steamgriddb_assets, downloaded_igdb_assets}}}
        """
        
        # TODO: If root_ui_for_dialog is provided, manage a progress dialog here.
        # For now, we assume this method itself is run in a thread by the generator.

        all_results_by_game_name = {} # Changed from all_results_by_uuid
        total_jobs = len(fetch_jobs)
        processed_jobs = 0

        # 1. Optional: IGDB Game ID pre-fetch (if any IGDB work is needed)
        # This allows us to search for all IGDB games once, then process them.
        # For simplicity now, we'll search IGDB per game within the loop.
        # Consider pre-fetch later if many IGDB jobs cause rate limit concerns with individual searches.
        
        # Prepare IGDB wrapper if needed by any job
        igdb_wrapper_instance = None
        if any(job.fetch_igdb_text_metadata or job.igdb_assets for job in fetch_jobs):
            if self.IGDBWrapper and self.requests and self.igdb_client_id and self.igdb_app_access_token:
                igdb_wrapper_instance = self.IGDBWrapper(self.igdb_client_id, self.igdb_app_access_token)
            else:
                results_queue.put({"status": "global_update", "info": "IGDB not configured/available, skipping all IGDB tasks."})


        for job_index, job in enumerate(fetch_jobs):
            if cancel_event.is_set():
                results_queue.put({"status": "global_update", "info": "Fetch plan cancelled."})
                break
            
            processed_jobs +=1
            results_queue.put({
                "status": "job_update", 
                "game_name": job.game_name, 
                "current_job_num": processed_jobs, 
                "total_jobs": total_jobs,
            })

            job_result = {
                "game_name": job.game_name,
                "text_data": {}, # From IGDB
                "downloaded_steamgriddb_assets": {}, # { asset_type_key: Path }
                "downloaded_igdb_assets": {} # { asset_type_key: Path }
            }
            
            # job.output_directory.mkdir(parents=True, exist_ok=True) # Removed: individual asset dirs created as needed

            # --- SteamGridDB ---
            if (not job.skip_images) and (job.steamgriddb_assets and self.steamgriddb_api_key and self.requests):
                results_queue.put({"status": "asset_update", "game_name": job.game_name, "asset_info": f"SteamGridDB: Searching for game ID..."})
                sgdb_game_id = None
                try:
                    search_response = self.requests.get(f"{STEAMGRIDDB_API_URL}/search/autocomplete/{self.requests.utils.quote(job.game_name)}", headers={"Authorization": f"Bearer {self.steamgriddb_api_key}"}, timeout=10)
                    search_response.raise_for_status()
                    search_data = search_response.json()
                    if search_data.get("success") and search_data.get("data"):
                        sgdb_game_id = search_data["data"][0]["id"]
                        results_queue.put({"status": "asset_update", "game_name": job.game_name, "asset_info": f"SteamGridDB: Game ID {sgdb_game_id} found."})
                    else:
                         results_queue.put({"status": "asset_update", "game_name": job.game_name, "asset_info": f"SteamGridDB: Game not found."})
                except Exception as e: # Catch broad exceptions for network/parse errors
                    results_queue.put({"status": "asset_update", "game_name": job.game_name, "asset_info": f"SteamGridDB: Error searching game ID: {e}"})

                if sgdb_game_id and not cancel_event.is_set():
                    # Pass only the keys (asset types) to _fetch_steamgriddb_asset_urls
                    sgdb_asset_urls_info = self._fetch_steamgriddb_asset_urls(job.game_name, sgdb_game_id, list(job.steamgriddb_assets.keys()), results_queue, cancel_event)
                    
                    for asset_key, url_details in sgdb_asset_urls_info.items():
                        if cancel_event.is_set(): break
                        # Construct filename from user-defined base_path + original extension
                        base_output_path = job.steamgriddb_assets[asset_key] # This is now a Path object without extension
                        output_file_path = base_output_path.with_suffix(url_details['original_extension'])
                        
                        output_file_path.parent.mkdir(parents=True, exist_ok=True) # Ensure directory exists
                        
                        downloaded_path = self._download_asset(url_details["url"], output_file_path, asset_key, job.game_name, results_queue, headers=url_details.get("headers"), source="SteamGridDB")
                        if downloaded_path:
                            job_result["downloaded_steamgriddb_assets"][asset_key] = downloaded_path
            
            # --- IGDB ---
            # Pass the whole igdb_assets dict (map of asset_key: basename)
            if (job.fetch_igdb_text_metadata or job.igdb_assets) and igdb_wrapper_instance:
                results_queue.put({"status": "asset_update", "game_name": job.game_name, "asset_info": "IGDB: Searching for game..."})
                
                best_match_game_data = None
                SIMILARITY_THRESHOLD = 0.7 # Could be a param
                try:
                    api_query = (
                        f'search "{job.game_name}"; '
                        f"fields name, summary, storyline, total_rating, first_release_date, "
                        f"genres.name, cover.image_id, artworks.image_id, screenshots.image_id, "
                        f"involved_companies.company.name, involved_companies.developer, involved_companies.publisher, "
                        f"game_modes.name, player_perspectives.name; "
                        f"limit 5;" # Keep limit low for individual searches
                    )
                    json_bytes = igdb_wrapper_instance.api_request('games', api_query)
                    games_data = json.loads(json_bytes.decode('utf-8'))

                    if games_data:
                        highest_similarity_ratio = 0.0
                        temp_best_match = None
                        for igdb_game_candidate in games_data:
                            if not igdb_game_candidate.get("name"): continue
                            current_igdb_name = igdb_game_candidate["name"]
                            if current_igdb_name.lower() == job.game_name.lower():
                                temp_best_match = igdb_game_candidate
                                results_queue.put({"status": "asset_update", "game_name": job.game_name, "asset_info": f"IGDB: Exact match found - {current_igdb_name}"})
                                break 
                            similarity = difflib.SequenceMatcher(None, job.game_name.lower(), current_igdb_name.lower()).ratio()
                            if similarity > highest_similarity_ratio:
                                highest_similarity_ratio = similarity
                                temp_best_match = igdb_game_candidate
                        
                        if temp_best_match:
                            if temp_best_match.get("name", "").lower() == job.game_name.lower() or highest_similarity_ratio >= SIMILARITY_THRESHOLD:
                                best_match_game_data = temp_best_match
                                match_info = f"Exact match" if temp_best_match.get("name", "").lower() == job.game_name.lower() else f"Similarity: {highest_similarity_ratio:.2f}"
                                results_queue.put({"status": "asset_update", "game_name": job.game_name, "asset_info": f"IGDB: Selected match '{best_match_game_data['name']}' ({match_info})."})
                            else:
                                results_queue.put({"status": "asset_update", "game_name": job.game_name, "asset_info": f"IGDB: Best match '{temp_best_match['name']}' ({highest_similarity_ratio:.2f}) below threshold. Skipping."})
                        else:
                            results_queue.put({"status": "asset_update", "game_name": job.game_name, "asset_info": f"IGDB: No suitable match found."})
                    else:
                        results_queue.put({"status": "asset_update", "game_name": job.game_name, "asset_info": f"IGDB: No results for game search."})

                except Exception as e: # Catch broad exceptions
                    results_queue.put({"status": "asset_update", "game_name": job.game_name, "asset_info": f"IGDB: Error searching/validating game: {e}"})

                if best_match_game_data and not cancel_event.is_set():
                    igdb_processed_data = self._fetch_igdb_data(
                        job.game_name, 
                        best_match_game_data,
                        job.fetch_igdb_text_metadata,
                        job.igdb_assets, # Pass the dict {asset_key: Path without extension}
                        job.skip_images,
                        results_queue,
                        cancel_event
                    )
                    job_result["text_data"].update(igdb_processed_data.get("text_data", {}))
                    job_result["downloaded_igdb_assets"].update(igdb_processed_data.get("downloaded_images", {}))
            
            all_results_by_game_name[job.game_name] = job_result
            # Report intermediate full result for this job if needed by UI for live updates
            results_queue.put({
                "status": "job_completed",
                "uuid": job.game_uuid, # Using game_name as the identifier
                "data": job_result
            })

        results_queue.put({
            "status": "fetch_plan_complete",
            "all_results": all_results_by_game_name
        })
        print("[MetadataFetcher] Fetch plan execution complete.")


    # Removed original fetch_steamgriddb_assets_for_game as it's now part of execute_fetch_plan logic
    # and _fetch_steamgriddb_asset_urls helper.

    def format_igdb_image_url(self, image_id: str, size_suffix: str = "t_cover_big") -> str:
        # This remains a useful utility
        if not image_id:
            return ""
        return f"https://images.igdb.com/igdb/image/upload/{size_suffix}/{image_id}.jpg"

    # Removed original fetch_igdb_metadata_for_game as its logic is now in execute_fetch_plan
    # and _fetch_igdb_data helper.


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