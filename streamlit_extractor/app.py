"""
iGatera Device Extractor
========================
Runs on your LOCAL NETWORK (same subnet as the Matrix COSEC devices).

Extracts enrolled users + fingerprint templates from a device,
then uploads them to the iGatera cloud backend via POST /api/devices/upload-import.

Setup:
    pip install -r requirements.txt
    streamlit run app.py
"""

import io
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urlunsplit

import openpyxl
import requests
import streamlit as st
import urllib3
from requests.auth import HTTPDigestAuth

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ---------------------------------------------------------------------------
# iGatera backend URL helpers
# ---------------------------------------------------------------------------

def _normalize_backend_api_base(base_url: str) -> str:
    """Normalize a user-entered backend URL to the API base.

    Accepts values like:
    - http://host
    - http://host/
    - http://host/api
    - https://host:8443

    Returns:
    - http://host/api
    - https://host:8443/api
    """
    raw = (base_url or "").strip()
    if not raw:
        return ""

    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"http://{raw}"

    parts = urlsplit(raw)
    if not parts.netloc:
        raise ValueError("Enter a valid backend URL, for example http://host or https://host/api")

    path = (parts.path or "").rstrip("/")
    if not path or path == "/":
        path = "/api"
    elif path.lower() != "/api":
        path = f"{path}/api" if not path.lower().endswith("/api") else path

    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _backend_api_url(base_url: str, path: str) -> str:
    api_base = _normalize_backend_api_base(base_url)
    if not api_base:
        raise ValueError("Backend URL is required")
    return f"{api_base.rstrip('/')}/{path.lstrip('/')}"


# ---------------------------------------------------------------------------
# Matrix COSEC device client (standalone â€” no backend imports needed)
# ---------------------------------------------------------------------------

class DeviceRequestError(Exception):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "request",
        status_code: int | None = None,
        response_text: str = "",
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.response_text = response_text


_LOCKOUT_MINUTES_RE = re.compile(r"try again after\s+(\d+)\s+minutes?", re.IGNORECASE)


def _device_lockout_message(body: str) -> str:
    match = _LOCKOUT_MINUTES_RE.search(body or "")
    if match:
        minutes = match.group(1)
        return (
            f"Device account is temporarily locked after failed login attempts. "
            f"Wait {minutes} minutes, then retry with the correct username and password."
        )
    return (
        "Device account is temporarily locked after failed login attempts. "
        "Wait for the lockout to clear before retrying."
    )


def _response_indicates_lockout(status_code: int, body: str) -> bool:
    text = (body or "").lower()
    return status_code == 429 or (
        "too many requests" in text and "account is locked" in text
    )


def _request_device(
    method,
    url: str,
    *,
    username: str,
    password: str,
    params: dict | None = None,
    timeout=(5, 10),
):
    try:
        response = method(
            url,
            params=params,
            auth=_auth(username, password),
            timeout=timeout,
            verify=False,
        )
    except requests.exceptions.ConnectionError as exc:
        raise DeviceRequestError(
            "Cannot reach device. Check the IP, port, protocol, and local network path.",
            kind="connection",
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise DeviceRequestError(
            "Device request timed out. Check connectivity and try again.",
            kind="timeout",
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise DeviceRequestError(f"Device request failed: {exc}", kind="request") from exc

    body = response.text or ""
    if _response_indicates_lockout(response.status_code, body):
        raise DeviceRequestError(
            _device_lockout_message(body),
            kind="locked",
            status_code=response.status_code,
            response_text=body,
        )
    if response.status_code in (401, 403):
        raise DeviceRequestError(
            "Device rejected the username or password. If you already retried several times, "
            "wait for any device lockout to clear before trying again.",
            kind="auth",
            status_code=response.status_code,
            response_text=body,
        )
    if response.status_code >= 400:
        raise DeviceRequestError(
            f"Device returned HTTP {response.status_code}.",
            kind="http",
            status_code=response.status_code,
            response_text=body,
        )
    return response


def _base_url(ip: str, port: int, https: bool) -> str:
    return f"{'https' if https else 'http'}://{ip}:{port}/device.cgi"


def _auth(username: str, password: str) -> HTTPDigestAuth:
    return HTTPDigestAuth(username, password)


def _user_lookup_url(ip: str, port: int, https: bool) -> str:
    protocol = "https" if https else "http"
    default_port = 443 if https else 80
    if port == default_port:
        return f"{protocol}://{ip}/device.cgi/users"
    return f"{protocol}://{ip}:{port}/device.cgi/users"


def device_ping(
    ip: str,
    port: int,
    https: bool,
    username: str,
    password: str,
    probe_user_id: int | None = None,
) -> bool:
    # Only perform one authenticated probe. Repeated probes on bad credentials
    # can trigger the device-side failed-login lockout very quickly.
    _ = probe_user_id
    _request_device(
        requests.get,
        f"{_base_url(ip, port, https)}/device-basic-config",
        username=username,
        password=password,
        params={"action": "get", "format": "xml"},
        timeout=(3, 5),
    )
    return True


def device_get_info(ip: str, port: int, https: bool, username: str, password: str) -> dict:
    """Returns {'mac': str|None, 'model': str|None, 'serial': str|None}."""
    response = _request_device(
        requests.get,
        f"{_base_url(ip, port, https)}/device-basic-config",
        username=username,
        password=password,
        params={"action": "get", "format": "xml"},
        timeout=(5, 10),
    )
    try:
        root = ET.fromstring(response.text)

        def _find(*tags):
            for tag in tags:
                v = root.findtext(tag)
                if v and v.strip():
                    return v.strip()
            return None

        return {
            "mac": _find("mac-address", "Mac-Address", "mac_address"),
            "model": _find("device-model", "Device-Model", "model"),
            "serial": _find("serial-number", "Serial-Number", "serial_number"),
        }
    except ET.ParseError:
        return {}


def device_get_user_count(ip: str, port: int, https: bool, username: str, password: str) -> int:
    response = _request_device(
        requests.get,
        f"{_base_url(ip, port, https)}/command",
        username=username,
        password=password,
        params={"action": "getusercount", "format": "xml"},
        timeout=(5, 15),
    )
    body = response.text
    try:
        root = ET.fromstring(body)
        for tag in ("user-count", "User-Count", "no-of-users", "total-users", "users-count"):
            v = root.findtext(tag)
            if v and v.strip().isdigit():
                return int(v.strip())
    except ET.ParseError:
        pass
    m = re.search(r"user[-_\s]*count\s*[=:]\s*(\d+)", body, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return -1


def device_get_raw_user_by_id_response(
    ip: str, port: int, https: bool, username: str, password: str, user_id: int
) -> tuple[int | None, str]:
    response = _request_device(
        requests.get,
        _user_lookup_url(ip, port, https),
        username=username,
        password=password,
        params={"action": "get", "user-id": user_id, "format": "xml"},
        timeout=5,
    )
    return response.status_code, response.text


def _parse_validity_xml(root: ET.Element) -> str:
    if (root.findtext("validity-enable") or "").strip() != "1":
        return ""
    dd = (root.findtext("validity-date-dd") or "").strip()
    mm = (root.findtext("validity-date-mm") or "").strip()
    yyyy = (root.findtext("validity-date-yyyy") or "").strip()
    if dd and mm and yyyy:
        try:
            return f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"
        except Exception:
            return ""
    return ""


def _parse_user_response(body: str, fallback_user_index: str = "") -> dict | None:
    body = (body or "").strip()
    if not body:
        return None
    if (
        "Response-Code=10" in body
        or "<Response-Code>10</Response-Code>" in body
        or "Response-Code=13" in body
        or "<Response-Code>13</Response-Code>" in body
        or "Request Failed" in body
    ):
        return None

    try:
        root = ET.fromstring(body)
        rc = root.findtext("Response-Code") or root.findtext("response-code")
        if rc and rc.strip() not in ("0", ""):
            return None

        user_id = (root.findtext("user-id") or "").strip()
        if user_id:
            return {
                "user_id": user_id,
                "ref_user_id": (root.findtext("ref-user-id") or user_id).strip(),
                "user_index": (root.findtext("user-index") or fallback_user_index).strip(),
                "full_name": (root.findtext("name") or user_id).strip(),
                "is_active": (root.findtext("user-active") or "1").strip() != "0",
                "valid_till": _parse_validity_xml(root),
            }
    except ET.ParseError:
        pass

    # Fallback for devices that return slightly malformed XML/text but still contain usable fields.
    if "user-id" not in body and "name" not in body:
        return None

    def _extract(tag: str) -> str:
        match = re.search(rf"<{tag}>(.*?)</{tag}>", body, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    user_id = _extract("user-id")
    if not user_id:
        return None

    ref_user_id = _extract("ref-user-id") or user_id
    full_name = _extract("name") or user_id
    user_active = _extract("user-active") or "1"
    user_index = _extract("user-index") or fallback_user_index
    dd = _extract("validity-date-dd")
    mm = _extract("validity-date-mm")
    yyyy = _extract("validity-date-yyyy")
    valid_till = ""
    if dd and mm and yyyy:
        try:
            valid_till = f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"
        except Exception:
            valid_till = ""

    return {
        "user_id": user_id,
        "ref_user_id": ref_user_id,
        "user_index": user_index,
        "full_name": full_name,
        "is_active": user_active.strip() != "0",
        "valid_till": valid_till,
    }


def device_get_user_by_index(
    ip: str, port: int, https: bool, username: str, password: str, index: int
) -> dict | None:
    response = _request_device(
        requests.get,
        _user_lookup_url(ip, port, https),
        username=username,
        password=password,
        params={"action": "get", "user-index": index, "format": "xml"},
        timeout=(3, 10),
    )
    return _parse_user_response(response.text, fallback_user_index=str(index))


def device_get_user_by_id(
    ip: str, port: int, https: bool, username: str, password: str, user_id: int
) -> dict | None:
    response = _request_device(
        requests.get,
        _user_lookup_url(ip, port, https),
        username=username,
        password=password,
        params={"action": "get", "user-id": user_id, "format": "xml"},
        timeout=5,
    )
    return _parse_user_response(response.text)


def _scan_users_by_id(
    ip: str,
    port: int,
    https: bool,
    username: str,
    password: str,
    max_user_id: int = 500,
    stop_after_misses: int = 100,
    progress_placeholder=None,
) -> list[dict]:
    profiles: list[dict] = []
    seen: set[str] = set()
    consecutive_misses = 0
    found_any = False

    for user_id in range(1, max_user_id + 1):
        profile = device_get_user_by_id(ip, port, https, username, password, user_id)
        if profile is None:
            if found_any:
                consecutive_misses += 1
                if consecutive_misses > stop_after_misses:
                    break
        else:
            found_any = True
            consecutive_misses = 0
            uid = profile["user_id"]
            if uid not in seen:
                seen.add(uid)
                profiles.append(profile)

        if progress_placeholder is not None:
            pct = user_id / max(max_user_id, 1)
            progress_placeholder.progress(
                pct,
                text=f"User-id scan: checked {user_id}/{max_user_id} â€” found {len(profiles)} user(s)",
            )

    return profiles


def device_get_fingerprint(
    ip: str, port: int, https: bool, username: str, password: str,
    user_id: str, finger_index: int,
) -> bytes | None:
    params = {"action": "get", "type": "1", "user-id": user_id, "finger-index": finger_index}
    for method in (requests.get, requests.post):
        try:
            r = _request_device(
                method,
                f"{_base_url(ip, port, https)}/credential",
                username=username,
                password=password,
                params=params,
                timeout=(5, 30),
            )
            if not r.content:
                continue
            c = r.content.strip()
            if (
                b"Request Failed" in c
                or b"Response-Code=" in c
                or (c.startswith(b"<") and b"Response-Code" in c)
            ):
                continue
            return r.content
        except DeviceRequestError as exc:
            if exc.kind in {"locked", "auth", "connection", "timeout"}:
                raise
            continue
    return None


def extract_all_users(
    ip: str, port: int, https: bool, username: str, password: str,
    total: int,
    fallback_max_user_id: int = 500,
    progress_placeholder=None,
) -> tuple[list[dict], str]:
    profiles: list[dict] = []
    seen: set[str] = set()
    max_index = max(total + 20, total * 2) if total > 0 else 5_000
    consecutive_misses = 0
    miss_limit = 20 if total > 0 else 50

    for idx in range(1, max_index + 1):
        if total > 0 and len(profiles) >= total:
            break
        profile = device_get_user_by_index(ip, port, https, username, password, idx)
        if profile is None:
            consecutive_misses += 1
            if consecutive_misses > miss_limit and (total <= 0 or idx > total):
                break
            continue
        consecutive_misses = 0
        uid = profile["user_id"]
        if uid not in seen:
            seen.add(uid)
            profiles.append(profile)
        if progress_placeholder is not None:
            pct = min(len(profiles) / max(total, 1), 1.0)
            label_total = total if total > 0 else "?"
            progress_placeholder.progress(pct, text=f"Index scan: users {len(profiles)} / {label_total}")

    scan_method = "user-index"
    needs_user_id_fallback = not profiles or (total > 0 and len(profiles) < total)
    if needs_user_id_fallback:
        fallback_profiles = _scan_users_by_id(
            ip,
            port,
            https,
            username,
            password,
            max_user_id=fallback_max_user_id,
            progress_placeholder=progress_placeholder,
        )
        for profile in fallback_profiles:
            uid = profile["user_id"]
            if uid not in seen:
                seen.add(uid)
                profiles.append(profile)
        if fallback_profiles:
            scan_method = "user-id"
        elif not profiles:
            scan_method = "none"

    return profiles, scan_method


def extract_all_fingerprints(
    ip: str, port: int, https: bool, username: str, password: str,
    user_ids: list[str],
    progress_placeholder=None,
) -> dict[str, dict[int, bytes]]:
    """Returns {user_id: {finger_index: bytes}}."""
    results: dict[str, dict[int, bytes]] = {}
    for i, uid in enumerate(user_ids):
        user_fps: dict[int, bytes] = {}
        consecutive_empty = 0
        for finger_idx in range(1, 11):
            data = device_get_fingerprint(ip, port, https, username, password, uid, finger_idx)
            if data:
                user_fps[finger_idx] = data
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                if user_fps and consecutive_empty >= 3:
                    break
        if user_fps:
            results[uid] = user_fps
        if progress_placeholder is not None:
            pct = (i + 1) / len(user_ids)
            fp_count = sum(len(v) for v in results.values())
            progress_placeholder.progress(
                pct, text=f"Users checked: {i + 1}/{len(user_ids)} â€” {fp_count} template(s) found"
            )
    return results


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="iGatera Device Extractor",
    page_icon="ðŸ”",
    layout="wide",
)

st.title("ðŸ” iGatera Device Extractor")
st.caption(
    "Run this on your **local network** â€” same subnet as the Matrix COSEC device. "
    "Extracts all enrolled users and fingerprint templates, then uploads to your iGatera backend."
)

# â”€â”€â”€ Session state init â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
for key, default in {
    "profiles": None,
    "fingerprints": None,
    "device_info": None,
    "user_scan_method": None,
    "device_mac_override": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

detected_device_info = st.session_state.get("device_info") or {}
detected_mac = (detected_device_info.get("mac") or "").strip()
if detected_mac and not (st.session_state.get("device_mac_override") or "").strip():
    st.session_state["device_mac_override"] = detected_mac

# â”€â”€â”€ Sidebar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
with st.sidebar:
    st.header("ðŸ“¡ Device Connection")
    device_ip = st.text_input("Device IP Address", value="192.168.1.100", placeholder="192.168.x.x")
    device_port = st.number_input("API Port", value=80, min_value=1, max_value=65535, step=1)
    use_https = st.checkbox("Use HTTPS", value=False)
    api_username = st.text_input("API Username", value="admin")
    api_password = st.text_input("API Password", type="password")

    st.divider()
    st.header("â˜ï¸ iGatera Backend")
    backend_url = st.text_input(
        "Backend Base URL",
        value="http://your-backend-server/api",
        help="e.g. http://43.12.x.x or https://app.yourcompany.com/api",
    )
    normalized_backend_url = ""
    if backend_url and "your-backend" not in backend_url:
        try:
            normalized_backend_url = _normalize_backend_api_base(backend_url)
            st.caption(f"API base: {normalized_backend_url}")
        except ValueError:
            st.caption("Enter a valid backend URL.")

    st.divider()
    st.header("ðŸ“‹ Import Settings")
    group_id = st.number_input("Group ID", min_value=1, value=1, step=1, help="Group to assign all imported tenants to")
    site_id = st.number_input("Site ID", min_value=1, value=1, step=1, help="Site the device belongs to")
    company_id_override = st.text_input(
        "Company ID (super-admin only)",
        value="",
        help="Leave blank unless you are a super-admin managing multiple companies",
    )
    device_mac_override = st.text_input(
        "Device MAC Address",
        key="device_mac_override",
        help="Optional manual override. If Step 1 reads the device MAC successfully, it will be prefilled here.",
        placeholder="AA:BB:CC:DD:EE:FF",
    )

    st.divider()
    st.header("âš™ï¸ Options")
    extract_fps = st.checkbox("Extract fingerprint templates", value=True)
    device_vendor_override = st.text_input("Device Vendor", value="Matrix")
    device_model_override = st.text_input("Device Model", value="COSEC")
    debug_user_id = st.number_input("Debug User ID", value=38, min_value=1, step=1)

# â”€â”€â”€ Step 1: Connect â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
st.subheader("Step 1 â€” Connect & Verify Device")

col_btn, col_status = st.columns([1, 3])
with col_btn:
    connect_clicked = st.button("ðŸ”Œ Test Connection", use_container_width=True)

if connect_clicked:
    with col_status:
        try:
            with st.spinner("Connecting to device..."):
                device_ping(
                    device_ip,
                    device_port,
                    use_https,
                    api_username,
                    api_password,
                    probe_user_id=int(debug_user_id),
                )
            with st.spinner("Reading device info..."):
                count = device_get_user_count(device_ip, device_port, use_https, api_username, api_password)
                info = device_get_info(device_ip, device_port, use_https, api_username, api_password)
                st.session_state["device_info"] = info
            user_count_str = f"{count} user(s) enrolled" if count >= 0 else "user count unavailable"
            mac_str = f" | MAC: `{info.get('mac')}`" if info.get("mac") else ""
            model_str = f" | Model: {info.get('model')}" if info.get("model") else ""
            st.success(f"Connected - {user_count_str}{mac_str}{model_str}")
        except DeviceRequestError as exc:
            st.error(str(exc))
            st.session_state["device_info"] = None

debug_lookup_clicked = st.button("Debug User ID Lookup", use_container_width=False)
if debug_lookup_clicked:
    try:
        with st.spinner(f"Reading raw response for user-id {int(debug_user_id)}..."):
            status_code, raw_body = device_get_raw_user_by_id_response(
                device_ip,
                device_port,
                use_https,
                api_username,
                api_password,
                int(debug_user_id),
            )
            parsed = _parse_user_response(raw_body) if status_code == 200 else None

        st.info(f"Raw lookup status for user-id {int(debug_user_id)}: HTTP {status_code}")
        if parsed:
            st.success(f"Parsed user: {parsed['user_id']} - {parsed['full_name']}")
            st.dataframe([parsed], use_container_width=True, hide_index=True)
        else:
            st.warning("No parseable user record was found in the response.")
        with st.expander("View raw device response"):
            st.code(raw_body[:4000] if raw_body else "(empty response)", language="xml")
    except DeviceRequestError as exc:
        st.error(str(exc))
        if exc.response_text:
            with st.expander("View raw device response"):
                st.code(exc.response_text[:4000], language="html")

extract_clicked = st.button(
    "Extract Users" + (" & Fingerprints" if extract_fps else ""),
    use_container_width=True,
    type="primary",
)

if extract_clicked:
    try:
        with st.spinner("Getting user count..."):
            total = device_get_user_count(device_ip, device_port, use_https, api_username, api_password)

        if total == 0:
            st.info("Device reported 0 users, but we will still scan the device records directly.")
        elif total < 0:
            st.info("Could not read user count - will scan device records directly.")
            total = 0

        st.markdown("**Extracting user profiles...**")
        user_prog = st.progress(0.0, text="Starting...")
        profiles, scan_method = extract_all_users(
            device_ip,
            device_port,
            use_https,
            api_username,
            api_password,
            total,
            fallback_max_user_id=500,
            progress_placeholder=user_prog,
        )
        st.session_state["profiles"] = profiles
        st.session_state["user_scan_method"] = scan_method

        if profiles:
            user_prog.progress(1.0, text=f"Done - {len(profiles)} user(s) extracted via {scan_method} scan")
        else:
            user_prog.progress(1.0, text="Done - no users found")
            st.warning(
                "No users were found by either user-index scan or user-id scan. "
                "Double-check device credentials and confirm the users are readable via the API."
            )

        if extract_fps and profiles:
            st.markdown("**Extracting fingerprint templates...**")
            fp_prog = st.progress(0.0, text="Starting...")
            user_ids = [p["user_id"] for p in profiles]
            fingerprints = extract_all_fingerprints(
                device_ip, device_port, use_https, api_username, api_password,
                user_ids, progress_placeholder=fp_prog,
            )
            total_templates = sum(len(v) for v in fingerprints.values())
            fp_prog.progress(
                1.0, text=f"Done - {total_templates} template(s) from {len(fingerprints)} user(s)"
            )
            st.session_state["fingerprints"] = fingerprints
        else:
            st.session_state["fingerprints"] = {}

        fp_total = sum(len(v) for v in (st.session_state["fingerprints"] or {}).values())
        st.success(f"Extracted **{len(profiles)}** users and **{fp_total}** fingerprint template(s)")
    except DeviceRequestError as exc:
        st.session_state["profiles"] = None
        st.session_state["fingerprints"] = None
        st.error(str(exc))

if st.session_state["profiles"]:
    st.subheader("Step 3 â€” Preview Extracted Data")
    fingerprints = st.session_state["fingerprints"] or {}
    scan_method = st.session_state.get("user_scan_method") or "unknown"
    st.info(f"Users discovered using `{scan_method}` scan.")
    preview_rows = []
    for p in st.session_state["profiles"]:
        fp_count = len(fingerprints.get(p["user_id"], {}))
        preview_rows.append({
            "User ID": p["user_id"],
            "Ref User ID": p.get("ref_user_id", ""),
            "User Index": p.get("user_index", ""),
            "Full Name": p["full_name"],
            "Active": "Yes" if p["is_active"] else "No",
            "Valid Till": p["valid_till"] or "-",
            "Fingerprints": fp_count,
        })
    st.dataframe(preview_rows, use_container_width=True, hide_index=True)

    fp_total = sum(len(v) for v in fingerprints.values())
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Total Users", len(st.session_state["profiles"]))
    col_b.metric("Users with Fingerprints", len(fingerprints))
    col_c.metric("Total Templates", fp_total)

    with st.expander("View raw extracted records"):
        st.dataframe(st.session_state["profiles"], use_container_width=True, hide_index=True)

# â”€â”€â”€ Step 4: Upload â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if st.session_state["profiles"]:
    st.subheader("Step 4 â€” Upload to iGatera Backend")

    if not backend_url or "your-backend" in backend_url:
        st.warning("Enter the correct Backend Base URL in the sidebar.")
    else:
        st.info("This extractor uploads without backend login. The backend must allow anonymous migration uploads.")
        upload_clicked = st.button("Upload to iGatera", type="primary", use_container_width=True)
        if upload_clicked:
            profiles = st.session_state["profiles"]
            fingerprints = st.session_state["fingerprints"] or {}
            device_info = st.session_state["device_info"] or {}

            with st.spinner("Building Excel file..."):
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Users"
                ws.append(["user_id", "ref_user_id", "full_name", "is_active", "valid_till", "user_index"])
                for p in profiles:
                    ws.append([
                        p["user_id"],
                        p.get("ref_user_id", p["user_id"]),
                        p["full_name"],
                        "1" if p["is_active"] else "0",
                        p["valid_till"],
                        p.get("user_index", ""),
                    ])
                excel_buf = io.BytesIO()
                wb.save(excel_buf)
                excel_bytes = excel_buf.getvalue()

            fp_total = sum(len(v) for v in fingerprints.values())
            with st.spinner(f"Uploading {len(profiles)} user(s) + {fp_total} template(s)..."):
                files: list = [
                    (
                        "users_excel",
                        (
                            "users.xlsx",
                            excel_bytes,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        ),
                    )
                ]
                for uid, fp_dict in fingerprints.items():
                    for finger_idx, fp_bytes in fp_dict.items():
                        files.append((
                            "fingerprints",
                            (f"{uid}_finger_{finger_idx}.dat", fp_bytes, "application/octet-stream"),
                        ))

                form_data: dict = {
                    "group_id": str(int(group_id)),
                    "site_id": str(int(site_id)),
                    "device_ip": device_ip,
                    "device_vendor": device_vendor_override,
                    "device_model": device_model_override,
                }
                effective_device_mac = device_mac_override.strip() or (device_info.get("mac") or "").strip()
                if effective_device_mac:
                    form_data["device_mac"] = effective_device_mac
                if device_info.get("serial"):
                    form_data["device_serial"] = device_info["serial"]
                if company_id_override.strip():
                    form_data["company_id"] = company_id_override.strip()

                url = _backend_api_url(backend_url, "/devices/upload-import")

                try:
                    resp = requests.post(
                        url, data=form_data, files=files, timeout=(15, 120)
                    )

                    if resp.status_code == 201:
                        result = resp.json()
                        st.success("Upload complete!")

                        r1, r2, r3, r4 = st.columns(4)
                        r1.metric("Imported", result["imported_user_count"])
                        r2.metric("Created", result["created_tenants"])
                        r3.metric("Updated", result["updated_tenants"])
                        r4.metric("Fingerprints Stored", result["imported_fingerprint_count"])

                        if result.get("warnings"):
                            for w in result["warnings"]:
                                st.warning(w)

                        with st.expander("View per-user results"):
                            st.dataframe(result.get("users", []), use_container_width=True)

                    elif resp.status_code == 401:
                        st.error("Upload requires backend support for anonymous migration uploads. Enable it on the backend and retry.")
                    else:
                        st.error(f"Upload failed: HTTP {resp.status_code}")
                        try:
                            st.code(str(resp.json().get("detail", resp.text[:500])))
                        except Exception:
                            st.code(resp.text[:500])

                except requests.exceptions.ConnectionError:
                    st.error("Cannot reach backend â€” check the Backend Base URL in the sidebar.")
                except requests.exceptions.Timeout:
                    st.error("Request timed out. Check the database before retrying to avoid duplicate imports.")
                except Exception as exc:
                    st.error(f"Unexpected error: {exc}")

# â”€â”€â”€ Footer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
st.divider()
st.caption("iGatera Device Extractor â€” run this tool on the same local network as your Matrix COSEC devices.")
