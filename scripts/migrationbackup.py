import requests
from requests.auth import HTTPDigestAuth

# --- Configuration ---
DEVICE_IP = "192.168.1.201"
USERNAME = "admin"
PASSWORD = "12345"
MAX_USER_ID = 500  # Will check IDs from 1 to 500

def backup_users_by_id():
    auth_method = HTTPDigestAuth(USERNAME, PASSWORD)
    
    print(f"Connecting to {DEVICE_IP} to scan user-ids from 1 to {MAX_USER_ID}...")
    
    found_users = 0
    
    # Open the file once to write all valid responses
    with open("matrix_users_backup.xml", "w", encoding="utf-8") as f:
        f.write("<?xml version='1.0' encoding='utf-8' ?>\n<MatrixBackup>\n")
        
        for user_id in range(1, MAX_USER_ID + 1):
            # Query explicitly by user-id
            url = f"http://{DEVICE_IP}/device.cgi/users?action=get&user-id={user_id}&format=xml"
            
            try:
                response = requests.get(url, auth=auth_method, timeout=5)
                
                # If we get a 200 OK, check the content
                if response.status_code == 200:
                    text = response.text
                    
                    # Skip if the user does not exist (Code 13) or command failed
                    if "<Response-Code>13</Response-Code>" not in text and "Request Failed" not in text:
                        
                        # Strip the redundant XML headers so the final file is clean
                        clean_xml = text.replace("<?xml version='1.0' encoding='utf-8' ?>", "").strip()
                        
                        # Optional: ensure it's not just a blank success code
                        if "user-id" in clean_xml or "name" in clean_xml:
                            f.write(clean_xml + "\n")
                            found_users += 1
                            print(f" -> Found and backed up User ID: {user_id}")
                            
            except requests.exceptions.RequestException as e:
                print(f"Network error at user-id {user_id}: {e}")
                
        f.write("</MatrixBackup>\n")
        
    print(f"\nScan Complete! Successfully extracted {found_users} users to 'matrix_users_backup.xml'.")

if __name__ == "__main__":
    backup_users_by_id()