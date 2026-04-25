"""
iGatera Panel Lite Extractor
=============================
Run on the same local network as the Matrix Panel Lite device.

Workflow:
  1. Connect to Panel Lite (IP + port + credentials)
  2. Enter user IDs manually, fetch user profiles
  3. Extract fingerprint templates (raw binary, 10 slots per user)
  4. Upload to iGatera backend

Setup:
    pip install -r requirements.txt
    streamlit run app.py
"""

import io
import re
import xml.etree.ElementTree as ET

import openpyxl
import requests
import streamlit as st
import urllib3
from requests.auth import HTTPDigestAuth

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BACKEND_API = "https://app.igatera.com:8099/api"


# ---------------------------------------------------------------------------
# Panel Lite device client
# ---------------------------------------------------------------------------

class DeviceError(Exception):
    def __init__(self, message, *, kind="request", status_code=None, response_text=""):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.response_text = response_text


def _make_session(username: str, password: str) -> requests.Session:
    s = requests.Session()
    s.auth = HTTPDigestAuth(username, password)
    s.verify = False
    return s


def _request(session: requests.Session, method: str, url: str, *,
             params=None, data=None, timeout=(5, 20)):
    try:
        resp = getattr(session, method)(url, params=params, data=data, timeout=timeout)
    except requests.exceptions.ConnectionError as e:
        raise DeviceError(
            "Cannot reach device. Check IP, port, and network path.",
            kind="connection",
        ) from e
    except requests.exceptions.Timeout as e:
        raise DeviceError("Request timed out.", kind="timeout") from e
    except requests.exceptions.RequestException as e:
        raise DeviceError(f"Request failed: {e}") from e

    if resp.status_code in (401, 403):
        raise DeviceError(
            "Authentication failed — check username and password.",
            kind="auth",
            status_code=resp.status_code,
            response_text=resp.text,
        )
    if resp.status_code >= 400:
        raise DeviceError(
            f"Device returned HTTP {resp.status_code}.",
            kind="http",
            status_code=resp.status_code,
            response_text=resp.text,
        )
    return resp


def _base(ip: str, port: int) -> str:
    return f"http://{ip}:{port}/device.cgi"


# -- Connection test ---------------------------------------------------------

def panel_test_connection(ip: str, port: int, username: str, password: str) -> dict:
    """
    Verify connectivity and credentials.
    Returns {'ok': True, 'mac': ..., 'model': ..., 'serial': ...} on success.
    """
    session = _make_session(username, password)
    # Try device-basic-config first (Panel Lite supports it)
    try:
        resp = _request(
            session, "get", f"{_base(ip, port)}/device-basic-config",
            params={"action": "get", "format": "xml"},
            timeout=(3, 6),
        )
        root = ET.fromstring(resp.text)

        def _f(*tags):
            for t in tags:
                v = root.findtext(t)
                if v and v.strip():
                    return v.strip()
            return None

        return {
            "ok": True,
            "mac":    _f("mac-address", "Mac-Address"),
            "model":  _f("device-model", "Device-Model"),
            "serial": _f("serial-number", "Serial-Number"),
        }
    except (DeviceError, ET.ParseError):
        pass

    # Fallback: probe /users endpoint
    _request(
        session, "get", f"{_base(ip, port)}/users",
        params={"action": "get", "user-id": "1", "format": "xml"},
        timeout=(3, 6),
    )
    return {"ok": True, "mac": None, "model": None, "serial": None}


# -- User fetch --------------------------------------------------------------

def _parse_user(body: str) -> dict | None:
    body = (body or "").strip()
    if not body:
        return None
    no_record = (
        "Response-Code=10" in body
        or "<Response-Code>10</Response-Code>" in body
        or "Response-Code=13" in body
        or "<Response-Code>13</Response-Code>" in body
        or "Request Failed" in body
    )
    if no_record:
        return None
    try:
        root = ET.fromstring(body)
        rc = root.findtext("Response-Code") or root.findtext("response-code")
        if rc and rc.strip() not in ("0", ""):
            return None
        uid = (root.findtext("user-id") or "").strip()
        if uid:
            return {
                "user_id":   uid,
                "full_name": (root.findtext("name") or uid).strip(),
                "is_active": (root.findtext("user-active") or "1").strip() != "0",
            }
    except ET.ParseError:
        pass
    # Regex fallback for slightly malformed XML
    def _e(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", body, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""
    uid = _e("user-id")
    if not uid:
        return None
    return {
        "user_id":   uid,
        "full_name": _e("name") or uid,
        "is_active": (_e("user-active") or "1").strip() != "0",
    }


def panel_get_user(ip: str, port: int, username: str, password: str, user_id: str) -> dict | None:
    """
    Fetch a single user by user-id.
    Returns a dict with user_id, full_name, is_active — or None if not found.
    """
    session = _make_session(username, password)
    resp = _request(
        session, "get", f"{_base(ip, port)}/users",
        params={"action": "get", "user-id": user_id, "format": "xml"},
        timeout=(5, 10),
    )
    return _parse_user(resp.text)


# -- Fingerprint extraction --------------------------------------------------

def panel_get_fingerprint(
    ip: str, port: int, username: str, password: str,
    user_id: str, finger_index: int,
) -> bytes | None:
    """
    Retrieve one fingerprint template as raw binary bytes.

    Per the Matrix API docs: the credential endpoint for biometric types
    returns raw/hex data (not XML), and POST must be used.

    Returns bytes if a template exists, None otherwise.
    """
    session = _make_session(username, password)
    params = {
        "action":       "get",
        "type":         "1",   # 1 = Finger
        "user-id":      user_id,
        "finger-index": finger_index,
    }
    for method in ("post", "get"):
        try:
            resp = _request(
                session, method, f"{_base(ip, port)}/credential",
                params=params, timeout=(5, 30),
            )
            if not resp.content:
                continue
            c = resp.content.strip()
            # Skip XML error responses
            if (
                b"Request Failed" in c
                or b"Response-Code=" in c
                or (c.startswith(b"<") and b"Response-Code" in c)
            ):
                continue
            return resp.content
        except DeviceError as e:
            if e.kind in ("auth", "connection", "timeout"):
                raise
            continue
    return None


def extract_fingerprints_for_users(
    ip: str, port: int, username: str, password: str,
    user_ids: list[str],
    progress_placeholder=None,
) -> dict[str, dict[int, bytes]]:
    """
    Returns {user_id: {finger_index: raw_bytes}}.
    Scans all 10 finger slots per user, stops early after 3 consecutive empty slots
    once at least one template has been found.
    """
    results: dict[str, dict[int, bytes]] = {}
    total = len(user_ids)

    for i, uid in enumerate(user_ids):
        user_fps: dict[int, bytes] = {}
        consecutive_empty = 0

        for finger_idx in range(1, 11):
            data = panel_get_fingerprint(ip, port, username, password, uid, finger_idx)
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
            pct = (i + 1) / max(total, 1)
            fp_count = sum(len(v) for v in results.values())
            progress_placeholder.progress(
                pct,
                text=f"Users checked: {i + 1}/{total} — {fp_count} template(s) found",
            )

    return results


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="iGatera Panel Lite Extractor",
    page_icon="🔍",
    layout="wide",
)

st.title("🔍 iGatera — Panel Lite Extractor")
st.caption(
    "Run this on the **same local network** as your Matrix Panel Lite device. "
    "Extracts users and fingerprint templates, then uploads to the iGatera backend."
)

# -- Session state -----------------------------------------------------------
for key, default in {
    "connected":   False,
    "device_info": None,
    "profiles":    None,   # list[dict]
    "fingerprints": None,  # {uid: {finger_idx: bytes}}
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("📡 Panel Lite Connection")
    device_ip   = st.text_input("Device IP Address", value="192.168.1.100", placeholder="192.168.x.x")
    device_port = st.number_input("Port", value=1040, min_value=1, max_value=65535, step=1)
    api_username = st.text_input("Username", value="admin")
    api_password = st.text_input("Password", type="password")

    test_clicked = st.button("🔌 Test Connection", use_container_width=True)
    if test_clicked:
        if not device_ip or not api_password:
            st.error("Enter IP and password.")
        else:
            try:
                with st.spinner("Connecting..."):
                    info = panel_test_connection(device_ip, device_port, api_username, api_password)
                st.session_state["connected"]   = True
                st.session_state["device_info"] = info
                parts = ["Connected"]
                if info.get("model"):
                    parts.append(f"Model: {info['model']}")
                if info.get("mac"):
                    parts.append(f"MAC: {info['mac']}")
                st.success(" | ".join(parts))
            except DeviceError as e:
                st.session_state["connected"]   = False
                st.session_state["device_info"] = None
                st.error(str(e))

    st.divider()
    st.header("☁️ iGatera Backend")
    st.info(f"**{BACKEND_API}**", icon="🔒")

    st.divider()
    st.header("📋 Import Settings")
    group_id = st.number_input(
        "Group ID", min_value=1, value=1, step=1,
        help="Tenant group to assign all imported users to",
    )
    site_id = st.number_input(
        "Site ID", min_value=1, value=1, step=1,
        help="Site the Panel Lite belongs to",
    )
    company_id_override = st.text_input(
        "Company ID (super-admin only)",
        value="",
        help="Leave blank unless you are managing multiple companies",
    )

# ---------------------------------------------------------------------------
# Step 1 — Connection status
# ---------------------------------------------------------------------------
st.subheader("Step 1 — Connection Status")

if st.session_state["connected"]:
    info = st.session_state["device_info"] or {}
    cols = st.columns(3)
    cols[0].success("Connected")
    if info.get("model"):
        cols[1].info(f"Model: {info['model']}")
    if info.get("mac"):
        cols[2].info(f"MAC: {info['mac']}")
else:
    st.warning("Not connected — use the **Test Connection** button in the sidebar.")

# ---------------------------------------------------------------------------
# Step 2 — Fetch Users by ID
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Step 2 — Fetch Users by ID")

if not st.session_state["connected"]:
    st.info("Connect to the device first.")
else:
    st.caption(
        "Enter one or more User IDs (comma-separated). "
        "Example: `2002001, 2002002, 2002003`"
    )
    user_ids_input = st.text_area(
        "User ID(s)",
        height=80,
        placeholder="2002001, 2002002, 2002003",
    )

    fetch_clicked = st.button("🔎 Fetch User(s)", type="primary", use_container_width=True)

    if fetch_clicked:
        raw_ids = [x.strip() for x in user_ids_input.replace("\n", ",").split(",") if x.strip()]
        if not raw_ids:
            st.error("Enter at least one User ID.")
        else:
            found: list[dict] = []
            not_found: list[str] = []
            errors: list[str] = []

            prog = st.progress(0.0, text="Fetching users...")
            for i, uid in enumerate(raw_ids):
                try:
                    profile = panel_get_user(device_ip, device_port, api_username, api_password, uid)
                    if profile:
                        found.append(profile)
                    else:
                        not_found.append(uid)
                except DeviceError as e:
                    errors.append(f"{uid}: {e}")
                prog.progress((i + 1) / len(raw_ids), text=f"Checked {i + 1}/{len(raw_ids)}")

            prog.progress(1.0, text="Done")
            st.session_state["profiles"] = found if found else None

            if found:
                st.success(f"Found **{len(found)}** user(s).")
            if not_found:
                st.warning(f"Not found on device: {', '.join(not_found)}")
            if errors:
                for err in errors:
                    st.error(err)

# -- Preview fetched users ---
if st.session_state["profiles"]:
    fps_map = {
        uid: len(fps)
        for uid, fps in (st.session_state.get("fingerprints") or {}).items()
    }
    rows = [
        {
            "User ID":     p["user_id"],
            "Full Name":   p["full_name"],
            "Active":      "Yes" if p["is_active"] else "No",
            "Fingerprints": fps_map.get(p["user_id"], 0),
        }
        for p in st.session_state["profiles"]
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Step 3 — Extract Fingerprints
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Step 3 — Extract Fingerprints")

if not st.session_state["profiles"]:
    st.info("Fetch users first (Step 2).")
else:
    st.caption(
        "Extracts up to 10 fingerprint templates per user using POST to "
        "`/device.cgi/credential?action=get&type=1`. "
        "Templates are raw binary — identical format for re-enrolling to another device."
    )

    extract_clicked = st.button(
        "🖐 Extract Fingerprints",
        type="primary",
        use_container_width=True,
    )

    if extract_clicked:
        user_ids = [p["user_id"] for p in st.session_state["profiles"]]
        fp_prog = st.progress(0.0, text="Starting fingerprint extraction...")
        try:
            fingerprints = extract_fingerprints_for_users(
                device_ip, device_port, api_username, api_password,
                user_ids,
                progress_placeholder=fp_prog,
            )
            st.session_state["fingerprints"] = fingerprints
            total_fp = sum(len(v) for v in fingerprints.values())
            fp_prog.progress(1.0, text=f"Done — {total_fp} template(s) from {len(fingerprints)} user(s)")

            if total_fp == 0:
                st.warning(
                    "No fingerprint templates found. "
                    "Verify the users are enrolled with fingerprints on the device."
                )
            else:
                st.success(
                    f"Extracted **{total_fp}** fingerprint template(s) "
                    f"from **{len(fingerprints)}** user(s)."
                )
        except DeviceError as e:
            st.error(str(e))
            st.session_state["fingerprints"] = None

    # Summary metrics
    fingerprints = st.session_state.get("fingerprints") or {}
    if fingerprints:
        total_fp = sum(len(v) for v in fingerprints.values())
        c1, c2, c3 = st.columns(3)
        c1.metric("Users with Fingerprints", len(fingerprints))
        c2.metric("Total Templates", total_fp)
        c3.metric("Avg Templates / User", f"{total_fp / max(len(fingerprints), 1):.1f}")

        with st.expander("View fingerprint detail per user"):
            detail = [
                {
                    "User ID": uid,
                    "Finger Slots": ", ".join(str(k) for k in sorted(fps.keys())),
                    "Templates":    len(fps),
                }
                for uid, fps in fingerprints.items()
            ]
            st.dataframe(detail, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Step 4 — Upload to iGatera
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Step 4 — Upload to iGatera Backend")

if not st.session_state["profiles"]:
    st.info("Complete Steps 2 and 3 first.")
else:
    fingerprints = st.session_state.get("fingerprints") or {}
    total_fp = sum(len(v) for v in fingerprints.values())
    device_info = st.session_state.get("device_info") or {}

    col_a, col_b = st.columns(2)
    col_a.metric("Users to upload", len(st.session_state["profiles"]))
    col_b.metric("Fingerprint templates", total_fp)

    st.caption(
        f"Uploading to: `{BACKEND_API}/devices/upload-import` — "
        "anonymous migration upload (no login required)."
    )

    upload_clicked = st.button(
        "📤 Upload to iGatera",
        type="primary",
        use_container_width=True,
    )

    if upload_clicked:
        profiles = st.session_state["profiles"]

        with st.spinner("Building Excel file..."):
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Users"
            ws.append(["user_id", "ref_user_id", "full_name", "is_active", "valid_till", "user_index"])
            for p in profiles:
                ws.append([
                    p["user_id"],
                    p["user_id"],
                    p["full_name"],
                    "1" if p["is_active"] else "0",
                    "",
                    "",
                ])
            excel_buf = io.BytesIO()
            wb.save(excel_buf)
            excel_bytes = excel_buf.getvalue()

        files: list = [
            (
                "users_excel",
                ("users.xlsx", excel_bytes,
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            )
        ]
        for uid, fp_dict in fingerprints.items():
            for finger_idx, fp_bytes in fp_dict.items():
                files.append((
                    "fingerprints",
                    (f"{uid}_finger_{finger_idx}.dat", fp_bytes, "application/octet-stream"),
                ))

        form_data: dict = {
            "group_id":      str(int(group_id)),
            "site_id":       str(int(site_id)),
            "device_ip":     device_ip,
            "device_vendor": "Matrix",
            "device_model":  "Panel Lite",
        }
        if device_info.get("mac"):
            form_data["device_mac"] = device_info["mac"]
        if device_info.get("serial"):
            form_data["device_serial"] = device_info["serial"]
        if company_id_override.strip():
            form_data["company_id"] = company_id_override.strip()

        with st.spinner(f"Uploading {len(profiles)} user(s) + {total_fp} template(s)..."):
            try:
                resp = requests.post(
                    f"{BACKEND_API}/devices/upload-import",
                    data=form_data,
                    files=files,
                    timeout=(15, 120),
                    verify=False,
                )

                if resp.status_code == 201:
                    result = resp.json()
                    st.success("Upload complete!")

                    r1, r2, r3, r4 = st.columns(4)
                    r1.metric("Imported",           result.get("imported_user_count", 0))
                    r2.metric("Created",            result.get("created_tenants", 0))
                    r3.metric("Updated",            result.get("updated_tenants", 0))
                    r4.metric("Fingerprints Stored", result.get("imported_fingerprint_count", 0))

                    for w in result.get("warnings", []):
                        st.warning(w)

                    with st.expander("View per-user results"):
                        st.dataframe(result.get("users", []), use_container_width=True)

                elif resp.status_code == 401:
                    st.error(
                        "Backend rejected the request — anonymous migration uploads may be disabled. "
                        "Enable `ALLOW_ANONYMOUS_MIGRATION_UPLOADS=true` on the backend."
                    )
                else:
                    st.error(f"Upload failed: HTTP {resp.status_code}")
                    try:
                        st.code(str(resp.json().get("detail", resp.text[:500])))
                    except Exception:
                        st.code(resp.text[:500])

            except requests.exceptions.ConnectionError:
                st.error(f"Cannot reach backend at `{BACKEND_API}`. Check network/VPN.")
            except requests.exceptions.Timeout:
                st.error("Request timed out. Check the database before retrying to avoid duplicates.")
            except Exception as exc:
                st.error(f"Unexpected error: {exc}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    "iGatera Panel Lite Extractor — "
    "run this tool on the same local network as your Matrix Panel Lite device."
)
