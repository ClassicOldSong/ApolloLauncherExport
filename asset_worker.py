#!/usr/bin/env python3
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

try:
    from igdb.wrapper import IGDBWrapper
    if not requests:
        raise ImportError("IGDBWrapper also needs 'requests' library.")
except ImportError:
    IGDBWrapper = None

from api_clients import fetch_steamgriddb_assets_for_game, fetch_igdb_metadata_for_game
from utils import download_image

def asset_fetching_worker(app_map, steamgriddb_api_key, out_dir_media_base, results_queue, cancel_event, 
                          fetch_igdb_enabled, igdb_client_id, igdb_app_access_token):
    """Worker function to fetch assets for all games."""
    total_games = len(app_map)
    processed_games = 0
    errors_occurred = False
    print(f"[Thread] Starting asset fetching for {total_games} games.")

    for name, game_data in app_map.items():
        if cancel_event.is_set():
            print("[Thread] Cancellation detected before processing game:", name)
            break # Exit the loop over games
        
        processed_games += 1
        results_queue.put({
            "status": "game_update", 
            "game_name": name, 
            "current_game_num": processed_games, 
            "total_games": total_games
        })

        uuid = game_data["uuid"]
        current_game_media_dir = out_dir_media_base / uuid
        current_game_media_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Fetch SteamGridDB asset URLs (not actual downloads)
            steamgriddb_assets_info = {}
            if steamgriddb_api_key:
                steamgriddb_assets_info = fetch_steamgriddb_assets_for_game(name, steamgriddb_api_key, results_queue, cancel_event)
                
                # Download SteamGridDB assets
                for asset_type, asset_data in steamgriddb_assets_info.items():
                    if cancel_event.is_set():
                        print(f"[Thread] Cancellation detected before downloading {asset_type} for {name}.")
                        break
                    
                    save_path = current_game_media_dir / asset_data["filename"]
                    if save_path.exists() and save_path.is_file():
                        print(f"[Thread] Skipping download for {name} - {asset_data['filename']}, already exists.")
                        results_queue.put({
                            "status": "asset_update",
                            "game_name": name,
                            "asset_info": f"{asset_data['filename']} already exists. Skipped."
                        })
                        continue

                    results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"Downloading {asset_type}..."})
                    
                    if download_image(asset_data["url"], save_path, headers=asset_data.get("headers")):
                        results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"{asset_data['filename']} downloaded."})
                    else:
                        results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"Failed to download {asset_type}."})
                        
            if not steamgriddb_assets_info and not any(current_game_media_dir.iterdir()):
                results_queue.put({"status": "asset_update", "game_name": name, "asset_info": "No SteamGridDB assets found."})
                print(f"[Thread] No SteamGridDB assets were fetched for {name}.")

            if cancel_event.is_set():
                print(f"[Thread] Cancellation detected after SteamGridDB fetch for {name}.")
                break

            # Fetch IGDB metadata and image URLs
            if fetch_igdb_enabled:
                if igdb_client_id and igdb_app_access_token and IGDBWrapper:
                    igdb_data = fetch_igdb_metadata_for_game(name, igdb_client_id, igdb_app_access_token, 
                                                 results_queue, cancel_event, steamgriddb_assets_info)
                    if igdb_data: # If data was actually fetched
                        # Extract image URLs from IGDB data and download them
                        image_urls = igdb_data.get("image_urls", {})
                        for image_type, image_data in image_urls.items():
                            if cancel_event.is_set():
                                print(f"[Thread] Cancellation detected before downloading {image_type} for {name}.")
                                break
                                
                            save_path = current_game_media_dir / image_data["filename"]
                            if save_path.exists() and save_path.is_file():
                                results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"{image_data['filename']} already exists. Skipped IGDB download."})
                                continue
                                
                            results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"Downloading {image_type} (IGDB)..."})
                            
                            if download_image(image_data["url"], save_path):
                                results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"{image_data['filename']} (IGDB) downloaded."})
                            else:
                                results_queue.put({"status": "asset_update", "game_name": name, "asset_info": f"Failed to download {image_data['filename']} (IGDB)."})
                        
                        # Remove image_urls from metadata before sending to queue (textual metadata only)
                        igdb_text_data = {k: v for k, v in igdb_data.items() if k != "image_urls"}
                        
                        if igdb_text_data: # Only send if there's textual metadata
                            results_queue.put({
                                "status": "igdb_text_data_ready",
                                "game_uuid": uuid, # Send UUID for reliable mapping
                                "game_name": name, # Keep for display/logging if needed
                                "data": igdb_text_data
                            })
                else:
                    results_queue.put({"status": "asset_update", "game_name": name, "asset_info": "Skipping IGDB: Not configured or library missing."})
                    print(f"[Thread] Skipping IGDB metadata for {name}: Not configured or library missing.")

        except Exception as e:
            error_msg = f"[Thread] Error processing assets/metadata for {name}: {e}"
            results_queue.put({"status": "asset_update", "game_name": name, "asset_info": error_msg})
            print(error_msg)
            errors_occurred = True
        
        if cancel_event.is_set(): # Check again after a game is processed
            print("[Thread] Cancellation detected after processing game:", name)
            break

    if cancel_event.is_set():
        results_queue.put({"status": "cancelled"})
        print("[Thread] Asset fetching was cancelled.")
    else:
        results_queue.put({"status": "complete", "errors_occurred": errors_occurred})
        print("[Thread] Asset fetching complete (not cancelled).") 