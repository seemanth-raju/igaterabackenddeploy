"""Test script to simulate a Matrix COSEC device using the Push API.

This simulates the device side of the communication:
  1. Login to server (with optional push_token auth)
  2. Poll for commands and configs
  3. If commands available → getcmd → execute → updatecmd
  4. If configs available → getconfig → apply → updateconfig
  5. Push events via setevent

Usage:
    python test/test_push_api.py --server http://localhost:8000/api --serial AABBCCDDEEFF
    python test/test_push_api.py --server http://localhost:8000/api --serial AABBCCDDEEFF --password mysecret --auto
"""

import argparse
import base64
import time
import sys

import requests


def parse_text_response(text: str) -> dict:
    """Parse a text response like 'cmd-avlbl=1 status=1' into a dict."""
    result = {}
    for part in text.strip().split():
        if "=" in part:
            k, v = part.split("=", 1)
            result[k] = v
    return result


class DeviceSimulator:
    """Simulates a Matrix COSEC device talking to our Push API server."""

    def __init__(self, server_url: str, serial_no: str, device_type: int = 7, password: str = ""):
        self.server = server_url.rstrip("/")
        self.serial_no = serial_no
        self.device_type = device_type
        self.password = password  # push_token shared secret
        self.poll_interval = 5
        self.format = "text"

    def _base_params(self) -> dict:
        """Common params sent with every request."""
        p = {"device-type": self.device_type, "serial-no": self.serial_no}
        if self.password:
            p["password"] = self.password
        return p

    def login(self) -> dict:
        """Send login request to server."""
        url = f"{self.server}/push/login"
        params = self._base_params()
        print(f"\n→ LOGIN: {url}")
        print(f"  Params: {params}")

        resp = requests.get(url, params=params, timeout=10)
        print(f"  Status: {resp.status_code}")
        print(f"  Body: {resp.text}")

        data = parse_text_response(resp.text)
        if "poll-interval" in data:
            self.poll_interval = int(data["poll-interval"])
        if "format" in data:
            self.format = "xml" if data["format"] == "1" else "text"

        if data.get("status") == "0":
            print("  ⚠ Login rejected (status=0). Check push_token / serial-no.")
        else:
            print(f"  ✓ Login OK. Poll interval: {self.poll_interval}s")
        return data

    def poll(self) -> dict:
        """Send poll request to server."""
        url = f"{self.server}/push/poll"
        params = self._base_params()

        resp = requests.get(url, params=params, timeout=15)
        data = parse_text_response(resp.text)
        return data

    def getcmd(self) -> dict:
        """Get the next command from server."""
        url = f"{self.server}/push/getcmd"
        params = self._base_params()
        print(f"\n→ GETCMD: {url}")

        resp = requests.get(url, params=params, timeout=15)
        print(f"  Status: {resp.status_code}")
        print(f"  Body: {resp.text}")

        data = parse_text_response(resp.text)
        return data

    def updatecmd(self, cmd_id: int, success: bool = True, extra_params: dict = None) -> dict:
        """Report command execution result."""
        url = f"{self.server}/push/updatecmd"
        params = {
            **self._base_params(),
            "cmd-id": cmd_id,
            "status": "1" if success else "0",
        }
        if extra_params:
            params.update(extra_params)

        print(f"\n→ UPDATECMD: {url}")
        print(f"  Params: {params}")

        resp = requests.get(url, params=params, timeout=15)
        print(f"  Status: {resp.status_code}")
        print(f"  Body: {resp.text}")

        data = parse_text_response(resp.text)
        return data

    def getconfig(self) -> dict:
        """Get the next config from server."""
        url = f"{self.server}/push/getconfig"
        params = self._base_params()
        print(f"\n→ GETCONFIG: {url}")

        resp = requests.get(url, params=params, timeout=15)
        print(f"  Status: {resp.status_code}")
        print(f"  Body: {resp.text}")

        data = parse_text_response(resp.text)
        return data

    def updateconfig(self, config_id: int, success: bool = True) -> dict:
        """Report config update result."""
        url = f"{self.server}/push/updateconfig"
        params = {
            **self._base_params(),
            "config-id": config_id,
            "status": "1" if success else "0",
        }
        print(f"\n→ UPDATECONFIG: {url}")
        print(f"  Params: {params}")

        resp = requests.get(url, params=params, timeout=15)
        print(f"  Status: {resp.status_code}")
        print(f"  Body: {resp.text}")

        data = parse_text_response(resp.text)
        return data

    def setevent(self, seq_no: int = 1, evt_id: int = 49, user_id: str = "42") -> dict:
        """Push a simulated access event."""
        url = f"{self.server}/push/setevent"
        now = time.localtime()
        params = {
            **self._base_params(),
            "seq-no": seq_no,
            "roll-over-count": 0,
            "evt_id": evt_id,
            "date-dd": now.tm_mday,
            "date-mm": now.tm_mon,
            "date-yyyy": now.tm_year,
            "time-hh": now.tm_hour,
            "time-mm": now.tm_min,
            "time-ss": now.tm_sec,
            "detail-1": user_id,
            "detail-2": "0",
            "detail-3": "0",
            "detail-4": "0",
            "detail-5": "0",
        }
        print(f"\n→ SETEVENT: {url}")
        print(f"  Params: {params}")

        resp = requests.get(url, params=params, timeout=10)
        print(f"  Status: {resp.status_code}")
        print(f"  Body: {resp.text}")

        data = parse_text_response(resp.text)
        return data

    def run_poll_loop(self, max_polls: int = 20):
        """Run a continuous poll loop (like a real device would).

        Handles both commands (getcmd/updatecmd) and configs (getconfig/updateconfig).
        """
        print(f"\nStarting poll loop (interval={self.poll_interval}s, max={max_polls} polls)...")
        print("Press Ctrl+C to stop.\n")

        for i in range(max_polls):
            print(f"--- Poll {i + 1}/{max_polls} ---")
            try:
                data = self.poll()
                cmd_available = data.get("cmd-avlbl", "0")
                cfg_available = data.get("cnfg-avlbl", "0")
                print(f"  cmd-avlbl={cmd_available} cnfg-avlbl={cfg_available}")

                # Handle configs first (user creation should happen before commands)
                if cfg_available == "1":
                    cfg_data = self.getconfig()
                    config_id = cfg_data.get("config-id", "0")
                    print(f"  Received config: config-id={config_id}")
                    print(f"  Full config data: {cfg_data}")

                    print(f"  Applying config-id={config_id}...")
                    time.sleep(0.5)

                    self.updateconfig(int(config_id), success=True)
                    continue  # Poll again to check for more

                # Handle commands
                if cmd_available == "1":
                    cmd_data = self.getcmd()
                    cmd_id = cmd_data.get("cmd-id", "0")
                    print(f"  Received command: cmd-id={cmd_id}")
                    print(f"  Full command data: {cmd_data}")

                    print(f"  Simulating execution of cmd-id={cmd_id}...")
                    time.sleep(1)

                    result_params = self._simulate_command_result(int(cmd_id), cmd_data)
                    update_data = self.updatecmd(int(cmd_id), success=True, extra_params=result_params)

                    if update_data.get("cmd-avlbl") == "1":
                        print("  More commands available, continuing...")
                        continue

                time.sleep(self.poll_interval)

            except KeyboardInterrupt:
                print("\nPoll loop stopped by user.")
                break
            except Exception as e:
                print(f"  Error: {e}")
                time.sleep(self.poll_interval)

    def _simulate_command_result(self, cmd_id: int, cmd_data: dict) -> dict:
        """Generate simulated result data for a command."""
        if cmd_id == 1:  # Enroll credential — finger was scanned
            return {
                "user-id": cmd_data.get("user-id", ""),
                "cred-type": cmd_data.get("cred-type", "3"),
            }
        elif cmd_id == 2:  # Delete credential
            return {"user-id": cmd_data.get("user-id", "")}
        elif cmd_id == 3:  # Get credential — return fake fingerprint template
            fake_template = b"\x00\x01\x02" * 100  # Simulated fingerprint data
            template_b64 = base64.b64encode(fake_template).decode("ascii")
            return {
                "user-id": cmd_data.get("user-id", ""),
                "data-1": template_b64,
            }
        elif cmd_id == 4:  # Set credential — fingerprint pushed to device
            return {"user-id": cmd_data.get("user-id", "")}
        elif cmd_id == 7:  # Delete user
            return {"user-id": cmd_data.get("user-id", "")}
        elif cmd_id == 16:  # Get event seq
            return {"Cur-Seq-number": "100", "Cur-rollover-count": "0"}
        elif cmd_id == 22:  # Get user count
            return {"user-count": "5"}
        return {}


def interactive_menu(sim: DeviceSimulator):
    """Interactive menu for testing individual endpoints."""
    while True:
        print("\n" + "=" * 60)
        print("Matrix COSEC Push API — Device Simulator")
        print("=" * 60)
        print(f"Server: {sim.server}")
        print(f"Serial: {sim.serial_no} | Device type: {sim.device_type}")
        print(f"Auth:   {'enabled' if sim.password else 'disabled'}")
        print("-" * 60)
        print("1. Login")
        print("2. Single poll")
        print("3. Get command (getcmd)")
        print("4. Update command (updatecmd)")
        print("5. Get config (getconfig)")
        print("6. Update config (updateconfig)")
        print("7. Send event (setevent)")
        print("8. Run poll loop (auto)")
        print("9. Check operation status")
        print("0. Exit")
        print("-" * 60)

        choice = input("Choose: ").strip()

        if choice == "1":
            sim.login()
        elif choice == "2":
            data = sim.poll()
            print(f"  Result: {data}")
        elif choice == "3":
            sim.getcmd()
        elif choice == "4":
            cmd_id = input("  cmd-id: ").strip() or "1"
            success = input("  success (1/0, default=1): ").strip() or "1"
            sim.updatecmd(int(cmd_id), success == "1")
        elif choice == "5":
            sim.getconfig()
        elif choice == "6":
            config_id = input("  config-id: ").strip() or "10"
            success = input("  success (1/0, default=1): ").strip() or "1"
            sim.updateconfig(int(config_id), success == "1")
        elif choice == "7":
            seq = input("  seq-no (default=1): ").strip() or "1"
            evt = input("  evt_id (default=49=access_granted): ").strip() or "49"
            uid = input("  user-id/detail-1 (default=42): ").strip() or "42"
            sim.setevent(int(seq), int(evt), uid)
        elif choice == "8":
            polls = input("  max polls (default=20): ").strip() or "20"
            sim.run_poll_loop(int(polls))
        elif choice == "9":
            corr_id = input("  correlation_id: ").strip()
            if corr_id:
                url = f"{sim.server}/push/operations/{corr_id}"
                print(f"\n→ GET {url}")
                resp = requests.get(url, timeout=10)
                print(f"  Status: {resp.status_code}")
                import json
                print(f"  Body: {json.dumps(resp.json(), indent=2)}")
        elif choice == "0":
            print("Bye!")
            break
        else:
            print("Invalid choice.")


def main():
    parser = argparse.ArgumentParser(description="Matrix COSEC Push API device simulator")
    parser.add_argument("--server", default="http://localhost:8000/api",
                        help="Server base URL (default: http://localhost:8000/api)")
    parser.add_argument("--serial", default="AABBCCDDEEFF",
                        help="Device serial number / MAC without colons (default: AABBCCDDEEFF)")
    parser.add_argument("--device-type", type=int, default=7,
                        help="Device type (default: 7=ARGO)")
    parser.add_argument("--password", default="",
                        help="Push token / shared secret for authentication")
    parser.add_argument("--auto", action="store_true",
                        help="Run poll loop automatically instead of interactive menu")
    parser.add_argument("--polls", type=int, default=20,
                        help="Max polls in auto mode (default: 20)")

    args = parser.parse_args()
    sim = DeviceSimulator(args.server, args.serial, args.device_type, args.password)

    if args.auto:
        print("Logging in...")
        sim.login()
        sim.run_poll_loop(args.polls)
    else:
        interactive_menu(sim)


if __name__ == "__main__":
    main()
