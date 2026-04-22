"""Matrix COSEC biometric device client.

API reference: http://<ip>/device.cgi/<endpoint>?action=<value>&...
Authentication: HTTP Digest Auth
"""

import hashlib
import ipaddress
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

import requests
import urllib3
from requests.auth import HTTPDigestAuth

from app.core.config import settings
from app.core.security import decrypt_password
from app.utils import get_fingerprint_storage_path

if not settings.matrix_device_verify_tls:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_log = logging.getLogger(__name__)


def validate_device_target(device_ip: str, api_port: int) -> None:
    """Reject backend-reachable non-device targets before making HTTP calls."""
    if not device_ip:
        raise ValueError("Device IP address is required")
    if "://" in device_ip or "/" in device_ip or "@" in device_ip:
        raise ValueError("Device target must be an IP address, not a URL")

    try:
        parsed_ip = ipaddress.ip_address(device_ip)
    except ValueError as exc:
        raise ValueError("Device target must be a valid IP address") from exc

    if parsed_ip.is_loopback or parsed_ip.is_link_local or parsed_ip.is_multicast or parsed_ip.is_unspecified:
        raise ValueError("Device target IP range is not allowed")

    allowed_cidrs = [ipaddress.ip_network(cidr) for cidr in settings.matrix_device_allowed_cidrs]
    if allowed_cidrs and not any(parsed_ip in network for network in allowed_cidrs):
        raise ValueError("Device target IP is outside the allowed device networks")

    if not 1 <= int(api_port) <= 65535:
        raise ValueError("Device API port must be between 1 and 65535")


class MatrixDeviceClient:
    """Client for interacting with Matrix COSEC biometric access devices."""

    def __init__(
        self,
        device_ip: str,
        username: str,
        encrypted_password: str | None = None,
        use_https: bool = False,
        api_port: int = 80,
        password: str | None = None,
    ):
        self.device_ip = device_ip
        self.username = username
        self.password = password if password is not None else (
            decrypt_password(encrypted_password) if encrypted_password else ""
        )
        self.protocol = "https" if use_https else "http"
        self.api_port = api_port
        validate_device_target(self.device_ip, self.api_port)
        self.base_url = f"{self.protocol}://{self.device_ip}:{self.api_port}/device.cgi"
        self.auth = HTTPDigestAuth(self.username, self.password)
        self.timeout = (5, 30)
        self.verify_tls = settings.matrix_device_verify_tls

    @staticmethod
    def _is_success(response: requests.Response) -> bool:
        """Check if device response indicates success (Response-Code 0)."""
        return response.status_code == 200 and (
            "Response-Code=0" in response.text
            or "<Response-Code>0</Response-Code>" in response.text
        )

    @staticmethod
    def _response_code_is_error(body: str) -> bool:
        return (
            "Request Failed" in body
            or "Response-Code=10" in body
            or "Response-Code=13" in body
            or "<Response-Code>10</Response-Code>" in body
            or "<Response-Code>13</Response-Code>" in body
        )

    @staticmethod
    def _parse_user_xml(body: str) -> dict | None:
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return None

        rc = root.findtext("Response-Code") or root.findtext("response-code")
        if rc and rc.strip() not in ("0", ""):
            return None

        user_id = (root.findtext("user-id") or "").strip()
        ref_user_id = (root.findtext("ref-user-id") or "").strip()
        name = (root.findtext("name") or "").strip()
        if not user_id and not ref_user_id and not name:
            return None

        return {
            "user_id": user_id,
            "user_index": (root.findtext("user-index") or "").strip(),
            "ref_user_id": ref_user_id,
            "name": name,
            "user_active": (root.findtext("user-active") or "").strip(),
            "vip": (root.findtext("vip") or "").strip(),
            "validity_enable": (root.findtext("validity-enable") or "").strip(),
            "validity_date_dd": (root.findtext("validity-date-dd") or "").strip(),
            "validity_date_mm": (root.findtext("validity-date-mm") or "").strip(),
            "validity_date_yyyy": (root.findtext("validity-date-yyyy") or "").strip(),
            "user_pin": (root.findtext("user-pin") or "").strip(),
            "card1": (root.findtext("card1") or "").strip(),
            "card2": (root.findtext("card2") or "").strip(),
            "by_pass_finger": (root.findtext("by-pass-finger") or "").strip(),
        }

    @staticmethod
    def _normalized_tag(tag: str | None) -> str:
        if not tag:
            return ""
        return "".join(ch for ch in tag.lower() if ch.isalnum())

    @classmethod
    def _find_text_by_tag(cls, root: ET.Element, *tag_names: str) -> str | None:
        wanted = {cls._normalized_tag(name) for name in tag_names}
        for node in root.iter():
            if cls._normalized_tag(node.tag) in wanted and node.text is not None:
                text = node.text.strip()
                if text:
                    return text
        return None

    @staticmethod
    def _parse_first_int(value: str | None) -> int | None:
        if not value:
            return None
        match = re.search(r"\d+", value)
        if not match:
            return None
        return int(match.group(0))

    @classmethod
    def _extract_user_count(cls, body: str) -> int | None:
        body = body.strip()
        if not body:
            return None

        if "<" in body:
            try:
                root = ET.fromstring(body)
            except ET.ParseError:
                root = None

            if root is not None:
                response_code = cls._find_text_by_tag(root, "Response-Code", "response-code")
                if response_code and response_code.strip() not in ("0", ""):
                    return None

                count_text = cls._find_text_by_tag(
                    root,
                    "user-count",
                    "User-Count",
                    "usercount",
                    "users-count",
                    "userscount",
                    "no-of-users",
                    "number-of-users",
                    "total-users",
                )
                count = cls._parse_first_int(count_text)
                if count is not None:
                    return count

        regex_patterns = (
            r"user[-_\s]*count\s*[=:]\s*(\d+)",
            r"users[-_\s]*count\s*[=:]\s*(\d+)",
            r"no[-_\s]*of[-_\s]*users\s*[=:]\s*(\d+)",
            r"number[-_\s]*of[-_\s]*users\s*[=:]\s*(\d+)",
            r"total[-_\s]*users\s*[=:]\s*(\d+)",
        )
        for pattern in regex_patterns:
            match = re.search(pattern, body, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Check device reachability. Returns True if online."""
        try:
            response = requests.get(
                f"{self.base_url}/device-basic-config",
                params={"action": "get"},
                auth=self.auth,
                timeout=(3, 5),
                verify=self.verify_tls,
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def get_event_count(self) -> dict:
        """
        Get the current event sequence number and rollover count.
        Returns {"seq_number": int, "rollover_count": int} or {"error": str}.
        """
        try:
            response = requests.get(
                f"{self.base_url}/command",
                params={"action": "geteventcount", "format": "xml"},
                auth=self.auth,
                timeout=self.timeout,
                verify=self.verify_tls,
            )
            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}"}
            root = ET.fromstring(response.text)
            seq = root.findtext("seq-number") or root.findtext("Seq-number") or "1"
            rollover = root.findtext("Roll-over-count") or root.findtext("roll-over-count") or "0"
            return {"seq_number": int(seq), "rollover_count": int(rollover)}
        except Exception as exc:
            return {"error": str(exc)}

    def fetch_events(self, rollover_count: int, seq_number: int, no_of_events: int = 100) -> list[dict]:
        """
        Fetch up to `no_of_events` events starting at seq_number.

        Returns list of dicts with keys:
            rollover_count, seq_number, event_time (datetime),
            cosec_event_id, detail_1..5
        """
        try:
            response = requests.get(
                f"{self.base_url}/events",
                params={
                    "action": "getevent",
                    "roll-over-count": rollover_count,
                    "seq-number": seq_number,
                    "no-of-events": no_of_events,
                    "format": "xml",
                },
                auth=self.auth,
                timeout=self.timeout,
                verify=self.verify_tls,
            )
            if response.status_code != 200:
                _log.warning("fetch_events: device %s returned HTTP %d", self.device_ip, response.status_code)
                return []

            _log.debug("fetch_events raw response from %s: %.500s", self.device_ip, response.text)

            root = ET.fromstring(response.text)
            event_nodes = root.findall("Events") or root.findall("Event")
            if not event_nodes:
                event_nodes = [c for c in root if "event" in c.tag.lower()]

            events = []
            for evt in event_nodes:
                raw_date = evt.findtext("date") or ""
                raw_time = evt.findtext("time") or "00:00:00"
                try:
                    day, month, year = raw_date.split("/")
                    event_time = datetime.strptime(
                        f"{year}-{month.zfill(2)}-{day.zfill(2)} {raw_time}", "%Y-%m-%d %H:%M:%S"
                    )
                except ValueError:
                    event_time = datetime.now(timezone.utc)

                events.append({
                    "rollover_count": int(evt.findtext("roll-over-count") or rollover_count),
                    "seq_number": int(evt.findtext("seq-No") or seq_number),
                    "event_time": event_time,
                    "cosec_event_id": int(evt.findtext("event-id") or 0),
                    "detail_1": evt.findtext("detail-1") or "",
                    "detail_2": evt.findtext("detail-2") or "",
                    "detail_3": evt.findtext("detail-3") or "",
                    "detail_4": evt.findtext("detail-4") or "",
                    "detail_5": evt.findtext("detail-5") or "",
                })
            return events
        except requests.exceptions.ConnectionError:
            _log.warning("fetch_events: cannot reach device %s", self.device_ip)
            return []
        except requests.exceptions.Timeout:
            _log.warning("fetch_events: device %s timed out", self.device_ip)
            return []
        except Exception:
            _log.exception("fetch_events: unexpected error on device %s", self.device_ip)
            return []

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    def get_user_count(self) -> int:
        """Get total enrolled user count. Returns -1 on error."""
        try:
            response = requests.get(
                f"{self.base_url}/command",
                params={"action": "getusercount", "format": "xml"},
                auth=self.auth,
                timeout=self.timeout,
                verify=self.verify_tls,
            )
            if response.status_code != 200:
                _log.warning(
                    "get_user_count: device %s returned HTTP %d",
                    self.device_ip,
                    response.status_code,
                )
                return -1
            body = response.text.strip()
            count = self._extract_user_count(body)
            if count is not None:
                return count

            _log.warning(
                "get_user_count: device %s returned an unreadable payload: %.500s",
                self.device_ip,
                body,
            )
            return -1
        except Exception:
            _log.exception("get_user_count: error from device %s", self.device_ip)
            return -1

    def create_user(
        self,
        user_id: str,
        name: str,
        active: bool = True,
        validity_end_date: date | None = None,
        enable_fr: str | None = None,
        card1: str | None = None,
    ) -> dict:
        """
        Create or update a user on the device.

        Args:
            user_id: Unique user identifier (max 15 chars)
            name: User display name (max 15 chars)
            active: Whether user can access the door
            validity_end_date: Optional date after which device denies access
            enable_fr: "1" to enable face recognition, "0" to disable
            card1: Optional RFID card number
        """
        params: dict = {
            "action": "set",
            "user-id": str(user_id),
            "ref-user-id": str(user_id),
            "name": name,
            "user-active": "1" if active else "0",
            "format": "xml",
        }
        if validity_end_date is not None:
            params["validity-enable"] = "1"
            params["validity-date-dd"] = str(validity_end_date.day)
            params["validity-date-mm"] = str(validity_end_date.month)
            params["validity-date-yyyy"] = str(validity_end_date.year)
        if enable_fr:
            params["enable-fr"] = str(enable_fr)
        if card1:
            params["card1"] = str(card1)

        response = requests.get(
            f"{self.base_url}/users",
            params=params,
            auth=self.auth,
            timeout=self.timeout,
            verify=self.verify_tls,
        )
        success = self._is_success(response)
        return {"status_code": response.status_code, "response": response.text, "success": success}

    def delete_user(self, user_id: str) -> dict:
        """Delete a user from the device."""
        response = requests.get(
            f"{self.base_url}/users",
            params={"action": "delete", "user-id": str(user_id), "format": "xml"},
            auth=self.auth,
            timeout=self.timeout,
            verify=self.verify_tls,
        )
        success = self._is_success(response)
        return {"status_code": response.status_code, "response": response.text, "success": success}

    def list_users(self) -> list[str]:
        """
        Return all user-id strings currently enrolled on the device.
        Iterates by user-index until all users are found or a gap threshold is hit.
        Returns [] on error.
        """
        total = self.get_user_count()
        if total <= 0:
            return []

        user_ids: list[str] = []
        max_index = min(total * 3, 5_000)
        consecutive_empty = 0

        for idx in range(1, max_index + 1):
            if len(user_ids) >= total:
                break
            try:
                response = requests.get(
                    f"{self.base_url}/users",
                    params={"action": "get", "user-index": idx, "format": "xml"},
                    auth=self.auth,
                    timeout=(3, 10),
                    verify=self.verify_tls,
                )
                body = response.text.strip()

                if response.status_code != 200 or not body:
                    consecutive_empty += 1
                    if consecutive_empty > 30:
                        break
                    continue

                if "Response-Code=10" in body or "<Response-Code>10</Response-Code>" in body:
                    consecutive_empty += 1
                    continue

                consecutive_empty = 0
                uid: str | None = None
                if "<" in body:
                    try:
                        root = ET.fromstring(body)
                        rc = root.findtext("Response-Code") or root.findtext("response-code")
                        if rc and rc.strip() not in ("0", ""):
                            continue
                        uid = root.findtext("user-id") or root.findtext("User-Id")
                    except ET.ParseError:
                        pass
                if uid is None:
                    for part in body.split():
                        if part.lower().startswith("user-id="):
                            uid = part.split("=", 1)[1]
                            break
                if uid and uid.strip() and uid.strip() != "0":
                    user_ids.append(uid.strip())

            except requests.exceptions.ConnectionError:
                _log.warning("list_users: cannot reach device %s at index %d", self.device_ip, idx)
                return []
            except requests.exceptions.Timeout:
                _log.warning("list_users: timeout on device %s at index %d", self.device_ip, idx)
                return []
            except Exception:
                _log.exception("list_users: error at user-index %d on device %s", idx, self.device_ip)
                continue

        return user_ids

    def get_user_by_index(self, user_index: int) -> dict | None:
        """Fetch one user record by compact user-index."""
        try:
            response = requests.get(
                f"{self.base_url}/users",
                params={"action": "get", "user-index": user_index, "format": "xml"},
                auth=self.auth,
                timeout=(3, 10),
                verify=self.verify_tls,
            )
            body = response.text.strip()
            if response.status_code != 200 or not body or self._response_code_is_error(body):
                return None
            return self._parse_user_xml(body)
        except requests.exceptions.ConnectionError:
            _log.warning("get_user_by_index: cannot reach device %s at index %d", self.device_ip, user_index)
            return None
        except requests.exceptions.Timeout:
            _log.warning("get_user_by_index: timeout on device %s at index %d", self.device_ip, user_index)
            return None
        except Exception:
            _log.exception("get_user_by_index: error at index %d on device %s", user_index, self.device_ip)
            return None

    def get_user_by_id(self, user_id: int | str) -> dict | None:
        """Fetch one user record by device user-id."""
        try:
            response = requests.get(
                f"{self.base_url}/users",
                params={"action": "get", "user-id": str(user_id), "format": "xml"},
                auth=self.auth,
                timeout=(3, 10),
                verify=self.verify_tls,
            )
            body = response.text.strip()
            if response.status_code != 200 or not body or self._response_code_is_error(body):
                return None
            return self._parse_user_xml(body)
        except requests.exceptions.ConnectionError:
            _log.warning("get_user_by_id: cannot reach device %s at user-id %s", self.device_ip, user_id)
            return None
        except requests.exceptions.Timeout:
            _log.warning("get_user_by_id: timeout on device %s at user-id %s", self.device_ip, user_id)
            return None
        except Exception:
            _log.exception("get_user_by_id: error at user-id %s on device %s", user_id, self.device_ip)
            return None

    def _scan_profiles_by_user_id(self, max_user_id: int = 5_000, stop_after_misses: int = 250) -> list[dict]:
        profiles: list[dict] = []
        seen_user_ids: set[str] = set()
        consecutive_misses = 0
        found_any = False

        for user_id in range(1, max_user_id + 1):
            profile = self.get_user_by_id(user_id)
            if profile is None:
                if found_any:
                    consecutive_misses += 1
                    if consecutive_misses > stop_after_misses:
                        break
                continue

            found_any = True
            consecutive_misses = 0
            matrix_user_id = (profile.get("user_id") or profile.get("ref_user_id") or "").strip()
            if matrix_user_id and matrix_user_id not in seen_user_ids:
                seen_user_ids.add(matrix_user_id)
                profiles.append(profile)

        return profiles

    def list_user_profiles(self, reported_total: int | None = None) -> list[dict]:
        """
        Return user records using the device-reported user count.

        Devices often use sparse `user-id` values, but `user-index` is compact,
        so we iterate indexes until we collect the reported number of users.
        """
        total = reported_total if reported_total is not None else self.get_user_count()

        profiles: list[dict] = []
        seen_user_ids: set[str] = set()
        index = 1
        max_index = max(total + 20, total * 2) if total > 0 else 5_000
        consecutive_misses = 0
        miss_limit = 20 if total > 0 else 50

        while index <= max_index:
            if total > 0 and len(profiles) >= total:
                break
            profile = self.get_user_by_index(index)
            if profile is None:
                consecutive_misses += 1
                if consecutive_misses > miss_limit and (total <= 0 or index > total):
                    break
                index += 1
                continue

            consecutive_misses = 0
            user_id = (profile.get("user_id") or profile.get("ref_user_id") or "").strip()
            if user_id and user_id not in seen_user_ids:
                seen_user_ids.add(user_id)
                profiles.append(profile)
            index += 1

        if profiles or total > 0:
            return profiles

        _log.warning(
            "list_user_profiles: device %s did not yield profiles by user-index; falling back to user-id scan",
            self.device_ip,
        )
        return self._scan_profiles_by_user_id()

    def wipe_all_users(self, max_index: int = 2000, stop_after_misses: int = 50) -> dict:
        """
        Delete every user on the device by iterating user-index slots.
        Stops after `stop_after_misses` consecutive empty slots.
        Returns {"deleted": [uid, ...], "errors": [{user_id, error}, ...]}.
        """
        deleted: list[str] = []
        errors: list[dict] = []
        consecutive_misses = 0

        for idx in range(1, max_index + 1):
            if consecutive_misses >= stop_after_misses:
                break
            try:
                response = requests.get(
                    f"{self.base_url}/users",
                    params={"action": "get", "user-index": idx, "format": "xml"},
                    auth=self.auth,
                    timeout=(3, 10),
                    verify=self.verify_tls,
                )
                body = response.text.strip()

                if (
                    response.status_code != 200
                    or not body
                    or "Response-Code=10" in body
                    or "<Response-Code>10</Response-Code>" in body
                ):
                    consecutive_misses += 1
                    continue

                consecutive_misses = 0
                uid: str | None = None
                if "<" in body:
                    try:
                        root = ET.fromstring(body)
                        uid = root.findtext("user-id") or root.findtext("User-Id")
                    except ET.ParseError:
                        pass
                if uid is None:
                    for part in body.split():
                        if part.lower().startswith("user-id="):
                            uid = part.split("=", 1)[1]
                            break

                if not uid or uid.strip() == "0":
                    continue
                uid = uid.strip()

                self.delete_fingerprint(uid)
                result = self.delete_user(uid)
                if result["success"]:
                    deleted.append(uid)
                else:
                    errors.append({"user_id": uid, "error": result["response"]})

            except requests.exceptions.ConnectionError:
                _log.warning("wipe_all_users: lost connection to %s at index %d", self.device_ip, idx)
                break
            except Exception:
                _log.exception("wipe_all_users: error at index %d on %s", idx, self.device_ip)
                continue

        _log.info("wipe_all_users: %s â€” deleted %d, errors %d", self.device_ip, len(deleted), len(errors))
        return {"deleted": deleted, "errors": errors}

    # ------------------------------------------------------------------
    # Fingerprint credentials (cross-device sync)
    # ------------------------------------------------------------------

    @staticmethod
    def _looks_like_error_payload(content: bytes) -> bool:
        stripped = content.strip()
        if not stripped:
            return True
        if b"Request Failed" in stripped or b"Response-Code=" in stripped:
            return True
        if stripped.startswith(b"<") and (
            b"Response-Code" in stripped or b"response-code" in stripped or b"COSEC_API" in stripped
        ):
            return True
        return False

    def _fetch_credential_binary(self, params: dict) -> bytes | None:
        for request_fn in (requests.get, requests.post):
            try:
                response = request_fn(
                    f"{self.base_url}/credential",
                    params=params,
                    auth=self.auth,
                    timeout=self.timeout,
                    verify=self.verify_tls,
                )
            except requests.exceptions.RequestException:
                continue

            if response.status_code != 200 or not response.content:
                continue
            if self._looks_like_error_payload(response.content):
                continue
            return response.content

        return None

    def get_fingerprint_template(self, user_id: str, finger_index: int = 1) -> bytes | None:
        return self._fetch_credential_binary({
            "action": "get",
            "type": "1",
            "user-id": str(user_id),
            "finger-index": str(finger_index),
        })

    def list_fingerprint_templates(self, user_id: str, max_finger_index: int = 10) -> dict[int, bytes]:
        templates: dict[int, bytes] = {}
        consecutive_misses = 0

        for finger_index in range(1, max_finger_index + 1):
            template = self.get_fingerprint_template(user_id, finger_index)
            if template is None:
                consecutive_misses += 1
                if templates and consecutive_misses >= 3:
                    break
                continue

            templates[finger_index] = template
            consecutive_misses = 0

        return templates

    def trigger_fingerprint_enrollment(self, user_id: str, finger_index: int = 1) -> dict:
        """
        Put the device into fingerprint enrollment mode for this user.
        The user must then place their finger on the device sensor.

        After calling this, wait for the user to scan their finger, then
        call extract_fingerprint() to retrieve the captured template.
        """
        response = requests.get(
            f"{self.base_url}/enrolluser",
            params={
                "action": "enroll",
                "type": "2",        # 2 = Fingerprint
                "user-id": str(user_id),
                "format": "xml",
            },
            auth=self.auth,
            timeout=self.timeout,
            verify=self.verify_tls,
        )
        success = self._is_success(response)
        return {"status_code": response.status_code, "response": response.text, "success": success}

    def extract_fingerprint(self, user_id: str, finger_index: int = 1) -> tuple[bytes | None, str | None]:
        """
        Pull a fingerprint template from the device and save it to local storage.

        Returns (template_bytes, file_path) or (None, None) if not yet captured.
        Call this after trigger_fingerprint_enrollment() and user has placed finger.
        """
        content = self.get_fingerprint_template(user_id, finger_index)
        if content is None:
            return None, None

        storage_path = get_fingerprint_storage_path()
        file_name = f"tenant_{user_id}_finger_{finger_index}.dat"
        file_path = storage_path / file_name
        file_path.write_bytes(content)
        return content, str(file_path)

    def import_fingerprint(self, user_id: str, file_path: str, finger_index: int = 1) -> dict:
        """
        Push a stored fingerprint template to the device.

        Use this to enroll a tenant on additional devices without requiring
        them to place their finger again.

        Args:
            user_id: Target user on the device
            file_path: Path to the .dat fingerprint template file
            finger_index: Finger slot index (1-10)
        """
        if not os.path.exists(file_path):
            return {"status_code": 0, "response": f"File not found: {file_path}", "success": False}

        with open(file_path, "rb") as f:
            binary_data = f.read()

        response = requests.post(
            f"{self.base_url}/credential",
            params={"action": "set", "type": "1", "user-id": str(user_id), "finger-index": str(finger_index)},
            data=binary_data,
            headers={"Content-Type": "application/octet-stream"},
            auth=self.auth,
            timeout=self.timeout,
            verify=self.verify_tls,
        )
        success = self._is_success(response)
        return {"status_code": response.status_code, "response": response.text, "success": success}

    def delete_fingerprint(self, user_id: str) -> dict:
        """Delete all fingerprint templates for a user on the device."""
        response = requests.get(
            f"{self.base_url}/credential",
            params={"action": "delete", "user-id": str(user_id), "type": "1", "format": "xml"},
            auth=self.auth,
            timeout=self.timeout,
            verify=self.verify_tls,
        )
        success = self._is_success(response)
        return {"status_code": response.status_code, "response": response.text, "success": success}


def calculate_file_hash(file_path: str) -> str:
    """Return SHA256 hex digest of a file, or '' if not found."""
    if not os.path.exists(file_path):
        return ""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
