import socket
import threading
import requests
from requests.auth import HTTPDigestAuth
import urllib3
import xml.etree.ElementTree as ET
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── CONFIG ────────────────────────────────────────────────────────────────────
DEVICE_IP    = "192.168.1.201"
MY_IP        = "192.168.1.100"   # your laptop's ethernet IP
MY_PORT      = 9000              # TCP port your laptop listens on
USERNAME     = "admin"
PASSWORD     = "12345"
START_SEQ    = 75                # current seq + 1
TIMEOUT      = (3, 10)
# ─────────────────────────────────────────────────────────────────────────────

auth = HTTPDigestAuth(USERNAME, PASSWORD)

EVENT_NAMES = {
    101: "✅ User Allowed",
    102: "✅ User Allowed - Duress",
    151: "❌ Denied - Invalid User",
    154: "❌ Denied - Timeout",
    157: "❌ Denied - Disabled User",
    158: "❌ Denied - Blocked User",
    159: "❌ Denied - Invalid Card",
    161: "❌ Denied - Control Zone",
    162: "❌ Denied - Door Lock",
    163: "❌ Denied - Invalid Access Group",
    164: "❌ Denied - Validity Expired",
    165: "❌ Denied - Invalid Route",
    166: "❌ Denied - Invalid Shift",
    175: "❌ Denied - Face Recognition Failed",
    402: "🔑 Login to Device",
    405: "👆 Enrollment",
    451: "⚙️  Config Change",
    453: "🟢 Device Power ON",
    457: "🔁 System Default",
}

SPECIAL_FUNCTIONS = {
    0: "Normal", 1: "Official IN", 2: "Official OUT",
    3: "Short Leave IN", 4: "Short Leave OUT",
    5: "Regular IN", 6: "Regular OUT",
    7: "Break End", 8: "Break Start",
}

USER_EVENTS = set(range(101, 180))

def decode_entry_exit(d3):
    try:
        return "← OUT" if (int(d3) & 0x01) == 1 else "→ IN "
    except:
        return "?    "

def print_event(xml_text):
    """Parse and print a single event received over TCP"""
    try:
        root = ET.fromstring(xml_text)
        for el in root.findall("Events"):
            eid  = int(el.findtext("event-id", "0"))
            seq  = el.findtext("seq-No", "?")
            date = el.findtext("date", "")
            time_ = el.findtext("time", "")
            d1   = el.findtext("detail-1", "0")
            d2   = el.findtext("detail-2", "0")
            d3   = el.findtext("detail-3", "0")
            name = EVENT_NAMES.get(eid, f"Event {eid}")
            ts   = f"{date} {time_}"

            if eid in USER_EVENTS:
                direction = decode_entry_exit(d3)
                spf = SPECIAL_FUNCTIONS.get(
                    int(d2) if d2.isdigit() else 0, f"SPF {d2}"
                )
                print(f"  [{seq}] {ts}   {direction}   User: {d1:<8}  {name}  ({spf})")
            else:
                print(f"  [{seq}] {ts}   {name}  d1={d1} d2={d2} d3={d3}")
    except ET.ParseError:
        # Device may send partial/non-XML data, print raw
        print(f"  [RAW] {xml_text[:200]}")

def handle_client(conn, addr):
    """Handle incoming TCP connection from device"""
    print(f"  [CONNECTED] Device connected from {addr}")
    buffer = ""
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            # Send TCP ACK back to device so it sends the next event
            conn.sendall(b"\x06")  # ACK byte
            text = data.decode("utf-8", errors="ignore").strip()
            if text:
                print_event(text)
    except Exception as e:
        print(f"  [CLIENT ERROR] {e}")
    finally:
        conn.close()
        print(f"  [DISCONNECTED] Device disconnected")

def start_tcp_server():
    """Start TCP server to receive events from device"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", MY_PORT))
    server.listen(5)
    print(f"  [TCP SERVER] Listening on port {MY_PORT}...")

    while True:
        conn, addr = server.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()

def register_with_device():
    """Tell the device to push events to our TCP server"""
    url = (
        f"http://{DEVICE_IP}/device.cgi/tcp-events"
        f"?action=getevent"
        f"&ipaddress={MY_IP}"
        f"&port={MY_PORT}"
        f"&keep-live-events=1"
        f"&roll-over-count=0"
        f"&seq-number={START_SEQ}"
        f"&format=xml"
    )
    print(f"  [REGISTER] Telling device to push events to {MY_IP}:{MY_PORT}...")
    try:
        r = requests.get(url, auth=auth, timeout=TIMEOUT)
        print(f"  [REGISTER] Device responded: HTTP {r.status_code}")
        print(f"  [REGISTER] Body: {r.text[:200]}")
        return r.status_code == 200
    except Exception as e:
        print(f"  [REGISTER ERROR] {e}")
        return False

def main():
    print("=" * 70)
    print("  COSEC Device — Real-time TCP Event Listener")
    print(f"  Device  : http://{DEVICE_IP}")
    print(f"  My IP   : {MY_IP}:{MY_PORT}")
    print(f"  Starting from seq #{START_SEQ}")
    print("  Ctrl+C to stop")
    print("=" * 70)
    print()

    # Start TCP server in background thread
    tcp_thread = threading.Thread(target=start_tcp_server, daemon=True)
    tcp_thread.start()
    time.sleep(1)  # give server a moment to start

    # Register with device
    if not register_with_device():
        print("  [ERROR] Failed to register with device")
        return

    print()
    print("  Waiting for events... punch the device now!")
    print()


    
    # Keep main thread alive
    while True:
        time.sleep(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Listener stopped.")