import requests
from requests.auth import HTTPBasicAuth
import json
import os
from typing import List, Dict

# ================== CONFIGURATION ==================
PANELS = [
    {"ip": "103.252.145.91", "port": 1025},
    {"ip": "103.252.145.91", "port": 1026},   # replace placeholders with real values
    {"ip": "103.252.145.91", "port": 1035},
    {"ip": "103.252.145.91", "port": 1040},
]

USERNAME = "Admin"
PASSWORD = "m395"

# Provide your list of user-ids here (alphanumeric, max 15 chars each)
USER_IDS: List[str] = [
    "1101",  # <-- ADD ALL YOUR USER-IDs HERE
    # ... add the rest
]

OUTPUT_DIR = "matrix_users_export"
os.makedirs(OUTPUT_DIR, exist_ok=True)
# ===================================================

auth = HTTPBasicAuth(USERNAME, PASSWORD)
session = requests.Session()
session.auth = auth

def get_user_config(panel: Dict, user_id: str) -> Dict:
    url = f"http://{panel['ip']}:{panel['port']}/device.cgi/users?action=get&user-id={user_id}&format=xml"
    try:
        r = session.get(url, timeout=10)
        r.raise_for_status()
        return {"status": "success", "data": r.text}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def get_credential(panel: Dict, user_id: str, cred_type: int, index: int = None) -> Dict:
    params = f"type={cred_type}&user-id={user_id}&format=xml"
    if index is not None:
        if cred_type == 1:   # Finger
            params += f"&finger-index={index}"
        elif cred_type == 3: # Palm
            params += f"&palm-index={index}"
        elif cred_type == 5: # Face
            params += f"&face-index={index}"

    url = f"http://{panel['ip']}:{panel['port']}/device.cgi/credential?action=get&{params}"
    try:
        r = session.get(url, timeout=10)
        r.raise_for_status()
        return {"status": "success", "data": r.text}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def main():
    for panel in PANELS:
        panel_name = f"{panel['ip']}_{panel['port']}"
        print(f"\n=== Processing Panel {panel_name} ===")
        
        for uid in USER_IDS:
            print(f"  Fetching user: {uid}")
            user_data = get_user_config(panel, uid)
            
            # Fetch credentials
            credentials = {}
            # Cards
            credentials["card"] = get_credential(panel, uid, 2)
            # Fingers (1-10)
            credentials["finger"] = {}
            for i in range(1, 11):
                credentials["finger"][f"finger_{i}"] = get_credential(panel, uid, 1, i)
            # Palms (if supported)
            credentials["palm"] = {}
            for i in range(1, 12):
                credentials["palm"][f"palm_{i}"] = get_credential(panel, uid, 3, i)
            # Face (if supported)
            credentials["face"] = {}
            for i in range(1, 31):
                credentials["face"][f"face_{i}"] = get_credential(panel, uid, 5, i)

            # Save everything
            export = {
                "user_id": uid,
                "panel": panel_name,
                "user_config": user_data,
                "credentials": credentials
            }
            
            filename = f"{OUTPUT_DIR}/{panel_name}_user_{uid}.json"
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(export, f, indent=2, ensure_ascii=False)
            
            print(f"    → Saved to {filename}")

if __name__ == "__main__":
    main()