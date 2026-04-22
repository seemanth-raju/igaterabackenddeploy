"""
iGatera Device Extractor -- Flask Server
Run:  python server.py
Open: http://localhost:5000
"""
import io
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import openpyxl
import requests
import urllib3
from flask import Flask, Response, jsonify, request, send_file, stream_with_context
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# Single-user local tool -- in-memory state is fine
_state = {"profiles": None, "fingerprints": None, "device_info": None}


# -- URL helpers --------------------------------------------------------------

def _normalize_backend_api_base(base_url):
    raw = (base_url or "").strip()
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = f"http://{raw}"
    parts = urlsplit(raw)
    if not parts.netloc:
        raise ValueError("Enter a valid backend URL")
    path = (parts.path or "").rstrip("/")
    if not path or path == "/":
        path = "/api"
    elif path.lower() != "/api":
        path = f"{path}/api" if not path.lower().endswith("/api") else path
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


# -- Session helpers ----------------------------------------------------------

class DeviceRequestError(Exception):
    def __init__(self, message, kind="request", status_code=None, response_text=""):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.response_text = response_text


_LOCKOUT_MINUTES_RE = re.compile(r"try again after\s+(\d+)\s+minutes?", re.IGNORECASE)


def _device_lockout_message(body):
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


def _response_indicates_lockout(status_code, body):
    text = (body or "").lower()
    return status_code == 429 or (
        "too many requests" in text and "account is locked" in text
    )


def _make_session(username, password):
    """Create a requests.Session with Digest auth.

    KEY BENEFIT: HTTPDigestAuth does a challenge-response handshake on the
    FIRST request (probe + authenticated retry = 2 HTTP calls).  After that
    the session caches the auth header and every subsequent request sends it
    directly -- just 1 HTTP call, 0 unauthenticated probes.

    Without a session every function call would trigger a fresh probe,
    counting as a failed-login attempt on strict devices even when the
    password is correct, eventually tripping the lockout.
    """
    s = requests.Session()
    s.auth = HTTPDigestAuth(username, password)
    s.verify = False
    return s


def _request_device(verb, url, session, params=None, timeout=(5, 10)):
    """Make one request via the shared session.

    verb -- "get" or "post"
    session -- a requests.Session created by _make_session()

    After the first successful Digest handshake the session caches the auth;
    subsequent calls skip the unauthenticated probe entirely.

    If the device only supports Basic Auth we detect that from the
    WWW-Authenticate header and switch the session to Basic -- permanently,
    so all later calls in this session also use Basic without probing again.
    """
    method = getattr(session, verb)

    def _do(**extra):
        try:
            return method(url, params=params, timeout=timeout, **extra)
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

    response = _do()
    body = response.text or ""

    # If the device speaks Basic only, switch the session auth once
    if response.status_code in (401, 403):
        www_auth = response.headers.get("WWW-Authenticate", "").lower()
        if "basic" in www_auth and "digest" not in www_auth:
            current = session.auth
            session.auth = HTTPBasicAuth(current.username, current.password)
            response = _do()
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


def _base_url(ip, port, https):
    return f"{'https' if https else 'http'}://{ip}:{port}/device.cgi"


def _user_lookup_url(ip, port, https):
    proto = "https" if https else "http"
    default = 443 if https else 80
    host = f"{ip}" if port == default else f"{ip}:{port}"
    return f"{proto}://{host}/device.cgi/users"


# -- Device API calls (all accept a shared session) ---------------------------

def device_ping(ip, port, https, session):
    """Verify the device is reachable and credentials are accepted.

    Tries /device-basic-config first (newer firmware), then falls back to
    /users (works on all firmware versions including older models).
    """
    base = _base_url(ip, port, https)
    try:
        _request_device(
            "get",
            f"{base}/device-basic-config",
            session,
            params={"action": "get", "format": "xml"},
            timeout=(3, 5),
        )
        return True
    except DeviceRequestError as exc:
        # auth/lock/network failures are definitive -- do not mask with fallback
        if exc.kind in ("auth", "locked", "connection", "timeout"):
            raise
        # endpoint not found on older firmware -- try /users instead
        pass

    _request_device(
        "get",
        _user_lookup_url(ip, port, https),
        session,
        params={"action": "get", "user-id": "1", "format": "xml"},
        timeout=(3, 5),
    )
    return True


def device_get_info(ip, port, https, session):
    try:
        response = _request_device(
            "get",
            f"{_base_url(ip, port, https)}/device-basic-config",
            session,
            params={"action": "get", "format": "xml"},
            timeout=(5, 10),
        )
    except DeviceRequestError as exc:
        if exc.kind in ("auth", "locked", "connection", "timeout"):
            raise
        return {}  # endpoint not available on this firmware
    try:
        root = ET.fromstring(response.text)
        def _find(*tags):
            for t in tags:
                v = root.findtext(t)
                if v and v.strip():
                    return v.strip()
            return None
        return {
            "mac":    _find("mac-address", "Mac-Address", "mac_address"),
            "model":  _find("device-model", "Device-Model", "model"),
            "serial": _find("serial-number", "Serial-Number", "serial_number"),
        }
    except ET.ParseError:
        return {}


def device_get_user_count(ip, port, https, session):
    response = _request_device(
        "get",
        f"{_base_url(ip, port, https)}/command",
        session,
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


def device_get_raw_user_by_id_response(ip, port, https, session, user_id):
    response = _request_device(
        "get",
        _user_lookup_url(ip, port, https),
        session,
        params={"action": "get", "user-id": user_id, "format": "xml"},
        timeout=5,
    )
    return response.status_code, response.text


def _parse_validity_xml(root):
    if (root.findtext("validity-enable") or "").strip() != "1":
        return ""
    dd   = (root.findtext("validity-date-dd")   or "").strip()
    mm   = (root.findtext("validity-date-mm")   or "").strip()
    yyyy = (root.findtext("validity-date-yyyy") or "").strip()
    if dd and mm and yyyy:
        try:
            return f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"
        except Exception:
            pass
    return ""


def _parse_user_response(body, fallback_user_index=""):
    body = (body or "").strip()
    if not body:
        return None
    if any(x in body for x in ("Response-Code=10", "<Response-Code>10</Response-Code>",
                                "Response-Code=13", "<Response-Code>13</Response-Code>",
                                "Request Failed")):
        return None
    try:
        root = ET.fromstring(body)
        rc = root.findtext("Response-Code") or root.findtext("response-code")
        if rc and rc.strip() not in ("0", ""):
            return None
        uid = (root.findtext("user-id") or "").strip()
        if uid:
            return {
                "user_id":     uid,
                "ref_user_id": (root.findtext("ref-user-id") or uid).strip(),
                "user_index":  (root.findtext("user-index") or fallback_user_index).strip(),
                "full_name":   (root.findtext("name") or uid).strip(),
                "is_active":   (root.findtext("user-active") or "1").strip() != "0",
                "valid_till":  _parse_validity_xml(root),
            }
    except ET.ParseError:
        pass
    if "user-id" not in body and "name" not in body:
        return None
    def _e(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", body, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""
    uid = _e("user-id")
    if not uid:
        return None
    dd, mm, yyyy = _e("validity-date-dd"), _e("validity-date-mm"), _e("validity-date-yyyy")
    valid_till = ""
    if dd and mm and yyyy:
        try:
            valid_till = f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"
        except Exception:
            pass
    return {
        "user_id":     uid,
        "ref_user_id": _e("ref-user-id") or uid,
        "user_index":  _e("user-index") or fallback_user_index,
        "full_name":   _e("name") or uid,
        "is_active":   (_e("user-active") or "1").strip() != "0",
        "valid_till":  valid_till,
    }


def device_get_user_by_index(ip, port, https, session, index):
    response = _request_device(
        "get",
        _user_lookup_url(ip, port, https),
        session,
        params={"action": "get", "user-index": index, "format": "xml"},
        timeout=(3, 10),
    )
    return _parse_user_response(response.text, fallback_user_index=str(index))


def device_get_user_by_id(ip, port, https, session, user_id):
    response = _request_device(
        "get",
        _user_lookup_url(ip, port, https),
        session,
        params={"action": "get", "user-id": user_id, "format": "xml"},
        timeout=5,
    )
    return _parse_user_response(response.text)


def device_get_fingerprint(ip, port, https, session, user_id, finger_index):
    params = {"action": "get", "type": "1", "user-id": user_id, "finger-index": finger_index}
    for verb in ("get", "post"):
        try:
            r = _request_device(
                verb,
                f"{_base_url(ip, port, https)}/credential",
                session,
                params=params,
                timeout=(5, 30),
            )
            if not r.content:
                continue
            c = r.content.strip()
            if (b"Request Failed" in c or b"Response-Code=" in c
                    or (c.startswith(b"<") and b"Response-Code" in c)):
                continue
            return r.content
        except DeviceRequestError as exc:
            if exc.kind in {"locked", "auth", "connection", "timeout"}:
                raise
            continue
    return None


# -- Flask routes -------------------------------------------------------------

@app.route("/")
def index():
    return send_file(Path(__file__).parent / "index.html")


@app.route("/api/connect", methods=["POST"])
def api_connect():
    d = request.json
    ip, port, https = d["ip"], int(d["port"]), bool(d.get("https"))
    username, password = d["username"], d["password"]

    # One session for all three calls -- digest handshake happens once only
    session = _make_session(username, password)
    try:
        device_ping(ip, port, https, session)
        count = device_get_user_count(ip, port, https, session)
        info  = device_get_info(ip, port, https, session)
    except DeviceRequestError as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "kind": exc.kind,
            "statusCode": exc.status_code,
        })

    _state["device_info"] = info
    return jsonify({"ok": True, "userCount": count, "info": info})


@app.route("/api/debug-user", methods=["POST"])
def api_debug_user():
    d = request.json
    ip, port, https = d["ip"], int(d["port"]), bool(d.get("https"))
    username, password = d["username"], d["password"]
    user_id = int(d["userId"])
    session = _make_session(username, password)
    try:
        status_code, raw_body = device_get_raw_user_by_id_response(
            ip, port, https, session, user_id)
        parsed = _parse_user_response(raw_body) if status_code == 200 else None
        return jsonify({"statusCode": status_code, "raw": raw_body, "parsed": parsed})
    except DeviceRequestError as exc:
        return jsonify({
            "statusCode": exc.status_code,
            "raw": exc.response_text,
            "parsed": None,
            "error": str(exc),
            "kind": exc.kind,
        })


@app.route("/api/extract", methods=["POST"])
def api_extract():
    d = request.json
    ip, port, https = d["ip"], int(d["port"]), bool(d.get("https"))
    username, password = d["username"], d["password"]
    extract_fps = bool(d.get("extractFps", True))
    max_user_id = max(50, min(9999, int(d.get("maxUserId", 500))))

    def generate():
        _state["profiles"] = None
        _state["fingerprints"] = None

        def emit(obj):
            return f"data: {json.dumps(obj)}\n\n"

        # One session for the entire extraction -- hundreds of requests,
        # but only a single digest handshake at the start
        session = _make_session(username, password)

        try:
            yield emit({"type": "status", "msg": "Getting user count from device..."})
            total = device_get_user_count(ip, port, https, session)
            if total < 0:
                total = 0
            yield emit({"type": "status", "msg": f"Device reports {total} user(s). Scanning by index..."})

            profiles_found, seen = [], set()
            max_index = max(total + 20, total * 2) if total > 0 else 5000
            consecutive_misses, miss_limit = 0, (20 if total > 0 else 50)

            for idx in range(1, max_index + 1):
                if total > 0 and len(profiles_found) >= total:
                    break
                profile = device_get_user_by_index(ip, port, https, session, idx)
                if profile is None:
                    consecutive_misses += 1
                    if consecutive_misses > miss_limit and (total <= 0 or idx > total):
                        break
                else:
                    consecutive_misses = 0
                    uid = profile["user_id"]
                    if uid not in seen:
                        seen.add(uid)
                        profiles_found.append(profile)
                pct = min(len(profiles_found) / max(total, 1), 0.99) if total > 0 else min(idx / max_index, 0.5)
                yield emit({"type": "user_progress", "pct": pct,
                            "found": len(profiles_found), "total": total})

            scan_method = "user-index"
            if not profiles_found or (total > 0 and len(profiles_found) < total):
                scan_method = "user-id"
                yield emit({"type": "status", "msg": f"Index scan incomplete - running user-ID fallback (1-{max_user_id})..."})
                for uid_int in range(1, max_user_id + 1):
                    profile = device_get_user_by_id(ip, port, https, session, uid_int)
                    if profile is not None:
                        uid = profile["user_id"]
                        if uid not in seen:
                            seen.add(uid)
                            profiles_found.append(profile)
                    yield emit({"type": "user_progress", "pct": uid_int / max_user_id,
                                "found": len(profiles_found), "total": total or "?"})

            _state["profiles"] = profiles_found
            yield emit({"type": "user_done", "found": len(profiles_found), "scanMethod": scan_method})

            if not profiles_found:
                yield emit({"type": "done", "users": 0, "fingerprints": 0,
                            "profiles": [], "scanMethod": scan_method})
                return

            fingerprints = {}
            if extract_fps:
                user_ids = [p["user_id"] for p in profiles_found]
                yield emit({"type": "status",
                            "msg": f"Extracting fingerprints from {len(user_ids)} user(s)..."})
                for i, uid in enumerate(user_ids):
                    user_fps = {}
                    consecutive_empty = 0
                    for finger_idx in range(1, 11):
                        data_bytes = device_get_fingerprint(
                            ip, port, https, session, uid, finger_idx)
                        if data_bytes:
                            user_fps[finger_idx] = data_bytes
                            consecutive_empty = 0
                        else:
                            consecutive_empty += 1
                            if user_fps and consecutive_empty >= 3:
                                break
                    if user_fps:
                        fingerprints[uid] = user_fps
                    fp_count = sum(len(v) for v in fingerprints.values())
                    yield emit({"type": "fp_progress", "pct": (i + 1) / len(user_ids),
                                "checked": i + 1, "total": len(user_ids), "found": fp_count})

            _state["fingerprints"] = fingerprints
            total_fps = sum(len(v) for v in fingerprints.values())
            users_with_fp = len(fingerprints)

            fp_map = {uid: len(fps) for uid, fps in fingerprints.items()}
            for p in profiles_found:
                p["fp_count"] = fp_map.get(p["user_id"], 0)

            yield emit({"type": "done", "users": len(profiles_found), "fingerprints": total_fps,
                        "usersWithFp": users_with_fp, "profiles": profiles_found,
                        "scanMethod": scan_method})
        except DeviceRequestError as exc:
            _state["profiles"] = None
            _state["fingerprints"] = None
            yield emit({"type": "error", "msg": str(exc), "kind": exc.kind})

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/upload", methods=["POST"])
def api_upload():
    d = request.json
    profiles     = _state.get("profiles")
    fingerprints = _state.get("fingerprints") or {}
    device_info  = _state.get("device_info") or {}

    if not profiles:
        return jsonify({"ok": False, "error": "No extracted data -- run extraction first."}), 400

    backend_url   = d["backendUrl"]
    group_id      = d["groupId"]
    site_id       = d["siteId"]
    device_ip     = d["deviceIp"]
    device_vendor = d.get("deviceVendor", "Matrix")
    device_model  = d.get("deviceModel", "COSEC")
    device_mac    = (d.get("deviceMac") or "").strip()
    company_id    = (d.get("companyId") or "").strip()

    # Build Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Users"
    ws.append(["user_id", "ref_user_id", "full_name", "is_active", "valid_till", "user_index"])
    for p in profiles:
        ws.append([p["user_id"], p.get("ref_user_id", p["user_id"]), p["full_name"],
                   "1" if p["is_active"] else "0", p["valid_till"], p.get("user_index", "")])
    excel_buf = io.BytesIO()
    wb.save(excel_buf)

    files = [("users_excel", ("users.xlsx", excel_buf.getvalue(),
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
    for uid, fp_dict in fingerprints.items():
        for finger_idx, fp_bytes in fp_dict.items():
            files.append(("fingerprints",
                          (f"{uid}_finger_{finger_idx}.dat", fp_bytes, "application/octet-stream")))

    form_data = {"group_id": str(int(group_id)), "site_id": str(int(site_id)),
                 "device_ip": device_ip, "device_vendor": device_vendor,
                 "device_model": device_model}
    effective_mac = device_mac or (device_info.get("mac") or "").strip()
    if effective_mac:
        form_data["device_mac"] = effective_mac
    if device_info.get("serial"):
        form_data["device_serial"] = device_info["serial"]
    if company_id:
        form_data["company_id"] = company_id

    try:
        api_base = _normalize_backend_api_base(backend_url)
        url = f"{api_base.rstrip('/')}/devices/upload-import"
        resp = requests.post(url, data=form_data, files=files, timeout=(15, 120))

        if resp.status_code == 201:
            return jsonify({"ok": True, "result": resp.json()})
        elif resp.status_code == 401:
            return jsonify({"ok": False,
                            "error": "Backend requires anonymous migration upload support."}), 401
        else:
            try:
                detail = resp.json().get("detail", resp.text[:500])
            except Exception:
                detail = resp.text[:500]
            return jsonify({"ok": False, "error": f"HTTP {resp.status_code}: {detail}"}), resp.status_code

    except requests.exceptions.ConnectionError:
        return jsonify({"ok": False, "error": "Cannot reach backend -- check the Backend Base URL."}), 503
    except requests.exceptions.Timeout:
        return jsonify({"ok": False,
                        "error": "Request timed out. Check the database before retrying."}), 504
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


if __name__ == "__main__":
    print("\n  iGatera Device Extractor")
    print("  " + "-" * 39)
    print("  Open http://localhost:5000 in your browser")
    print("  Press Ctrl+C to stop\n")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
