"""Push API endpoints — called BY the Matrix COSEC devices (not by frontend).

Architecture:
  - Device connects to our server (Third Party mode)
  - Device sends: login → poll (every N seconds) → getcmd → updatecmd
  - Device also sends: setevent (to push access events to us)

The device identifies itself by serial-no (MAC without colons) and device-type.
We match serial-no to Device.mac_address in our DB.
"""

import hashlib
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pydantic import BaseModel, Field

from app.api.deps import get_current_user, get_db
from database.models import (
    AccessEvent,
    AppUser,
    Device,
    DeviceCommand,
    DeviceConfig,
    DeviceUserMapping,
    UserRole,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/push", tags=["push-api (device-facing)"])

_SENSITIVE_PARAM_NAMES = {
    "password",
    "pwd",
    "pass",
    "token",
    "push_token",
    "api_password",
    "user-pin",
    "pin",
    "card1",
    "card2",
}


def _redact_params(params: dict | None) -> dict:
    redacted: dict = {}
    for key, value in (params or {}).items():
        key_text = str(key).lower()
        if key_text in _SENSITIVE_PARAM_NAMES or "password" in key_text or key_text.startswith("data-"):
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Map Matrix device-type integers to human-readable names
DEVICE_TYPE_MAP = {
    0: "Door V3", 1: "PVR", 2: "Vega", 3: "FMX",
    4: "Path V2", 5: "ARC DC200", 6: "Door V4", 7: "ARGO", 8: "ARGO FACE",
}

# Bounded per-device rate limiter — caps at _RATE_LIMIT_MAX_ENTRIES entries so
# spoofed/unknown serial numbers cannot grow this dict unboundedly.
_last_request: OrderedDict[str, float] = OrderedDict()
_RATE_LIMIT_INTERVAL = 1.0   # minimum seconds between requests per device
_RATE_LIMIT_MAX_ENTRIES = 10_000


def _find_device(serial_no: str, db: Session) -> Device | None:
    """Look up a device by its serial number (MAC without colons).

    The Push API sends serial-no = MAC address without colons.
    We store mac_address with colons (AA:BB:CC:DD:EE:FF), so we
    try both: exact match on mac_address (with colons re-inserted)
    and on device_serial_number.
    """
    # Try matching mac_address (insert colons: AABBCCDDEEFF → AA:BB:CC:DD:EE:FF)
    # Use case-insensitive compare — DB may store lowercase, device sends uppercase
    clean = serial_no.upper().replace(":", "").replace("-", "")
    if len(clean) == 12:
        mac_with_colons = ":".join(clean[i:i + 2] for i in range(0, 12, 2))
        device = db.query(Device).filter(Device.mac_address.ilike(mac_with_colons)).first()
        if device:
            return device

    # Fallback: match on device_serial_number. Normalize to uppercase because
    # imported/default serials are stored from MACs without separators.
    device = db.query(Device).filter(Device.device_serial_number == clean).first()
    if device:
        return device

    device = db.query(Device).filter(Device.device_serial_number == serial_no).first()
    return device


def _find_existing_event(
    device_id: int,
    seq_no: int,
    rollover_count: int,
    db: Session,
) -> AccessEvent | None:
    """Return an already stored device event for the same sequence tuple."""
    return (
        db.query(AccessEvent)
        .filter(
            AccessEvent.device_id == device_id,
            AccessEvent.device_seq_number == seq_no,
            AccessEvent.device_rollover_count == rollover_count,
        )
        .first()
    )


def _extract_basic_auth_password(request: Request) -> str:
    """Extract password from HTTP Basic Auth header.

    Matrix COSEC devices in Third Party mode send the configured
    User ID and Password via standard HTTP Basic Authentication.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("basic "):
        return ""
    try:
        import base64
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8", errors="ignore")
        # Basic auth format: "username:password"
        if ":" in decoded:
            return decoded.split(":", 1)[1]
        return decoded
    except Exception:
        return ""


def _verify_device_token(device: Device, params: dict, request: Request) -> bool:
    """Verify the push_token (shared secret) provided by the device.

    The device sends the password via:
      1. HTTP Basic Auth header (standard Matrix COSEC behavior)
      2. 'password' query/form param (fallback)

    If no push_token_hash is stored on the device, allow the request (dev mode).
    """
    if not device.push_token_hash:
        return True  # No token configured — allow (log warning at call site)

    # Try HTTP Basic Auth first (Matrix devices send credentials this way)
    provided = _extract_basic_auth_password(request)

    # Fallback to query/form param
    if not provided:
        provided = params.get("password", "")

    if not provided:
        _log.debug("Device %d: no password provided (checked Basic Auth + params)", device.device_id)
        return False
    return hashlib.sha256(provided.encode()).hexdigest() == device.push_token_hash


def _rate_check(serial_no: str) -> bool:
    """Bounded per-device rate limiter. Returns True if request is allowed."""
    now = monotonic()
    last = _last_request.get(serial_no, 0.0)
    if now - last < _RATE_LIMIT_INTERVAL:
        return False
    # Evict oldest entry when at capacity to keep memory bounded.
    if serial_no not in _last_request and len(_last_request) >= _RATE_LIMIT_MAX_ENTRIES:
        _last_request.popitem(last=False)
    _last_request[serial_no] = now
    _last_request.move_to_end(serial_no)
    return True


def _validate_serial_no(serial_no: str) -> bool:
    """Validate serial-no format: should be 12 hex characters."""
    if not serial_no:
        return False
    clean = serial_no.upper().replace(":", "").replace("-", "")
    return len(clean) == 12 and all(c in "0123456789ABCDEF" for c in clean)


async def _get_params(request: Request) -> dict:
    """Extract params from query string OR POST body (form-urlencoded or plain text).

    Matrix devices send params as POST body in form-urlencoded format
    when in Third Party mode.
    """
    params = dict(request.query_params)

    # If query params have what we need, use them
    if params.get("serial-no"):
        return params

    # Try form data (application/x-www-form-urlencoded)
    try:
        form = await request.form()
        if form:
            params.update(dict(form))
            if params.get("serial-no"):
                return params
    except Exception:
        pass

    # Try raw body as text (key=value&key=value)
    try:
        body = await request.body()
        if body:
            body_text = body.decode("utf-8", errors="ignore").strip()
            _log.debug("Push raw body received (%d bytes)", len(body))
            # Parse as query string format
            for part in body_text.replace("&", " ").split():
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k] = v
    except Exception:
        pass

    return params


def _authenticate_device(device: Device, params: dict, request: Request) -> str | None:
    """Authenticate a push device. Returns error message or None if OK."""
    if not _verify_device_token(device, params, request):
        _log.warning("Push auth failed for device %d (serial=%s) — check push_token matches device password",
                     device.device_id, device.device_serial_number)
        return "Authentication failed"
    if not device.push_token_hash:
        _log.debug("Device %d has no push_token configured (dev mode)", device.device_id)
    return None


def _text_response(body: str) -> Response:
    """Return a plain-text response (Matrix devices expect text format by default)."""
    return Response(content=body, media_type="text/plain")


def _xml_response(body: str) -> Response:
    """Return an XML response."""
    return Response(content=body, media_type="application/xml")


def _build_cmd_response(cmd: DeviceCommand, fmt: str) -> Response:
    """Build a getcmd response from a queued DeviceCommand."""
    params = cmd.params or {}
    if fmt == "xml":
        parts = [f"<cmd-id>{cmd.cmd_id}</cmd-id>"]
        for k, v in params.items():
            parts.append(f"<{k}>{v}</{k}>")
        xml_body = "<api>\n" + "\n".join(parts) + "\n</api>"
        return _xml_response(xml_body)
    else:
        parts = [f"cmd-id={cmd.cmd_id}"]
        for k, v in params.items():
            parts.append(f"{k}={v}")
        return _text_response(" ".join(parts))


def _resolve_tenant_id(device_id: int, matrix_user_id: str, db: Session) -> int | None:
    """Resolve a matrix_user_id on a device to our tenant_id via DeviceUserMapping."""
    if not matrix_user_id:
        return None
    mapping = (
        db.query(DeviceUserMapping)
        .filter(
            DeviceUserMapping.device_id == device_id,
            DeviceUserMapping.matrix_user_id == matrix_user_id,
        )
        .first()
    )
    return mapping.tenant_id if mapping else None


def _build_event_time(params: dict, device: Device) -> datetime:
    """Build a timezone-aware event time from device date/time params.

    Uses the device's site timezone if available, otherwise UTC.
    """
    try:
        import zoneinfo

        dd = int(params.get("date-dd", 0))
        mm = int(params.get("date-mm", 0))
        yyyy = int(params.get("date-yyyy", 2026))
        hh = int(params.get("time-hh", 0))
        mi = int(params.get("time-mm", 0))
        ss = int(params.get("time-ss", 0))

        # Use site timezone if available
        device_tz = timezone.utc
        if device.site and device.site.timezone:
            try:
                device_tz = zoneinfo.ZoneInfo(device.site.timezone)
            except (KeyError, Exception):
                pass

        local_time = datetime(yyyy, mm, dd, hh, mi, ss, tzinfo=device_tz)
        return local_time.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# LOGIN — device sends this first after being configured for Third Party mode
# ---------------------------------------------------------------------------

@router.api_route("/login", methods=["GET", "POST"])
async def device_login(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Handle device login. Device sends: /login?device-type=X&serial-no=XXXX

    We respond with poll parameters so the device knows how often to poll.
    """
    params = await _get_params(request)
    serial_no = params.get("serial-no", "")
    device_type = params.get("device-type", "")

    if not _validate_serial_no(serial_no):
        _log.warning("Push login: invalid serial-no format: %s", serial_no)
        return _text_response("poll-interval=5 poll-duration=15 poll-count=5 status=0 format=0")

    dt_int = int(device_type) if device_type.isdigit() else -1
    _log.info("Push login: serial-no=%s device-type=%s (%s)",
              serial_no, device_type, DEVICE_TYPE_MAP.get(dt_int, "unknown"))

    device = _find_device(serial_no, db)
    if device:
        # Debug: log what auth info the device is sending
        auth_header = request.headers.get("authorization", "")
        has_basic = auth_header.lower().startswith("basic ") if auth_header else False
        has_param_pw = bool(params.get("password"))
        has_token_hash = bool(device.push_token_hash)
        _log.info("Push login auth debug: device=%d has_token_hash=%s basic_auth=%s param_password=%s",
                  device.device_id, has_token_hash, has_basic, has_param_pw)

        # Authenticate
        auth_error = _authenticate_device(device, params, request)
        if auth_error:
            return _text_response("poll-interval=5 poll-duration=15 poll-count=5 status=0 format=0")

        # Update device status to online
        device.status = "online"
        device.last_heartbeat = datetime.now(timezone.utc)
        db.commit()
        _log.info("Device %d (%s) logged in via Push API", device.device_id, device.device_serial_number)
    else:
        _log.warning("Push login from unknown device: serial-no=%s", serial_no)

    # Respond with poll config — text format (login always uses text)
    from app.core.config import settings
    interval = settings.push_api_default_poll_interval
    return _text_response(f"poll-interval={interval} poll-duration=15 poll-count=5 status=1 format=0")


# ---------------------------------------------------------------------------
# POLL — device polls us periodically to check for pending commands/configs
# ---------------------------------------------------------------------------

@router.api_route("/poll", methods=["GET", "POST"])
async def device_poll(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Handle device poll. Device sends: /poll?device-type=X&serial-no=XXXX

    We respond with whether commands or configs are available.
    """
    params = await _get_params(request)
    serial_no = params.get("serial-no", "")

    device = _find_device(serial_no, db)
    if not device:
        _log.warning("Push poll from unknown device: serial-no=%s", serial_no)
        return _text_response("cmd-avlbl=0 cnfg-avlbl=0 status=1")

    # Authenticate
    auth_error = _authenticate_device(device, params, request)
    if auth_error:
        return _text_response("cmd-avlbl=0 cnfg-avlbl=0 status=0")

    # Rate check
    if not _rate_check(serial_no):
        return _text_response("cmd-avlbl=0 cnfg-avlbl=0 status=1")

    # Update heartbeat
    device.status = "online"
    device.last_heartbeat = datetime.now(timezone.utc)

    # Check for pending commands
    pending_cmd = (
        db.query(DeviceCommand)
        .filter(DeviceCommand.device_id == device.device_id, DeviceCommand.status == "pending")
        .order_by(DeviceCommand.created_at)
        .first()
    )

    # Check for pending configs
    pending_cfg = (
        db.query(DeviceConfig)
        .filter(DeviceConfig.device_id == device.device_id, DeviceConfig.status == "pending")
        .order_by(DeviceConfig.created_at)
        .first()
    )

    cmd_available = 1 if pending_cmd else 0
    cfg_available = 1 if pending_cfg else 0
    db.commit()

    _log.debug("Push poll: device=%d cmd_available=%d cfg_available=%d", device.device_id, cmd_available, cfg_available)
    return _text_response(f"cmd-avlbl={cmd_available} cnfg-avlbl={cfg_available} status=1")


# ---------------------------------------------------------------------------
# GETCMD — device asks for the next command to execute
# ---------------------------------------------------------------------------

@router.api_route("/getcmd", methods=["GET", "POST"])
async def device_get_command(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Handle getcmd. Device sends: /getcmd?device-type=X&serial-no=XXXX

    We return the oldest pending command for this device.
    """
    params = await _get_params(request)
    serial_no = params.get("serial-no", "")

    device = _find_device(serial_no, db)
    if not device:
        _log.warning("Push getcmd from unknown device: serial-no=%s", serial_no)
        return _text_response("status=0")

    # Authenticate
    auth_error = _authenticate_device(device, params, request)
    if auth_error:
        return _text_response("status=0")

    # Get the oldest pending command
    cmd = (
        db.query(DeviceCommand)
        .filter(DeviceCommand.device_id == device.device_id, DeviceCommand.status == "pending")
        .order_by(DeviceCommand.created_at)
        .first()
    )

    if not cmd:
        _log.debug("Push getcmd: device=%d no pending commands", device.device_id)
        return _text_response("status=0")

    # Mark as sent
    cmd.status = "sent"
    cmd.sent_at = datetime.now(timezone.utc)
    db.commit()

    _log.info("Push getcmd: device=%d sending command_id=%d cmd_id=%d params=%s",
              device.device_id, cmd.command_id, cmd.cmd_id, _redact_params(cmd.params))

    # Determine format (default text, use device config if available)
    fmt = "text"  # Default to text format
    return _build_cmd_response(cmd, fmt)


# ---------------------------------------------------------------------------
# UPDATECMD — device reports command execution result
# ---------------------------------------------------------------------------

@router.api_route("/updatecmd", methods=["GET", "POST"])
async def device_update_command(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Handle updatecmd. Device sends: /updatecmd?device-type=X&serial-no=XXXX&status=1&cmd-id=1&...

    Device reports whether the command succeeded or failed, along with result data.
    """
    params = await _get_params(request)
    _log.info("Push updatecmd params: %s", _redact_params(params))
    serial_no = params.get("serial-no", "")
    cmd_status = params.get("status", "0")  # 0=failure, 1=success
    cmd_id_str = params.get("cmd-id", "")

    device = _find_device(serial_no, db)
    if not device:
        _log.warning("Push updatecmd from unknown device: serial-no=%s", serial_no)
        return _text_response("cmd-avlbl=0 status=1")

    # Authenticate
    auth_error = _authenticate_device(device, params, request)
    if auth_error:
        return _text_response("cmd-avlbl=0 status=0")

    # Find the most recent sent command for this device with matching cmd-id
    cmd_id = int(cmd_id_str) if cmd_id_str.isdigit() else None
    query = (
        db.query(DeviceCommand)
        .filter(
            DeviceCommand.device_id == device.device_id,
            DeviceCommand.status == "sent",
        )
        .order_by(DeviceCommand.sent_at.desc())
    )
    if cmd_id is not None:
        query = query.filter(DeviceCommand.cmd_id == cmd_id)
    cmd = query.first()

    # Store the full result params (strip device-type, serial-no, status, cmd-id — keep the rest)
    result_data = {k: v for k, v in params.items() if k not in ("device-type", "serial-no", "status", "cmd-id", "password")}

    if cmd:
        cmd.status = "success" if cmd_status == "1" else "failed"
        cmd.completed_at = datetime.now(timezone.utc)
        cmd.result = result_data
        if cmd_status != "1":
            cmd.error_message = f"Device reported failure. Data: {result_data}"
        _log.info("Push updatecmd: device=%d command_id=%d status=%s result=%s",
                  device.device_id, cmd.command_id, cmd.status, result_data)

        # Post-process completed command (callbacks)
        try:
            from app.api.services.push.callbacks import handle_command_completion
            handle_command_completion(cmd, device, db)
        except Exception:
            _log.exception("Push updatecmd: callback error for command_id=%d", cmd.command_id)
    else:
        _log.warning("Push updatecmd: no matching sent command for device=%d cmd_id=%s",
                      device.device_id, cmd_id_str)

    # Check if more commands are pending
    next_pending = (
        db.query(DeviceCommand)
        .filter(DeviceCommand.device_id == device.device_id, DeviceCommand.status == "pending")
        .first()
    )
    cmd_available = 1 if next_pending else 0
    db.commit()

    return _text_response(f"cmd-avlbl={cmd_available} status=1")


# ---------------------------------------------------------------------------
# SETEVENT — device pushes access events to us
# ---------------------------------------------------------------------------

@router.api_route("/setevent", methods=["GET", "POST"])
async def device_set_event(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Handle setevent. Device pushes real-time access events.

    Device sends: /setevent?device-type=X&serial-no=XXXX&seq-no=123&evt_id=101&
                  date-dd=20&date-mm=3&date-yyyy=2026&time-hh=14&time-mm=30&time-ss=0&
                  detail-1=42&detail-2=...

    We parse and store the event in the access_event table.
    """
    params = await _get_params(request)
    serial_no = params.get("serial-no", "")

    _log.info("Push setevent params: %s", _redact_params(params))

    device = _find_device(serial_no, db)
    if not device:
        _log.warning("Push setevent from unknown device: serial-no=%s", serial_no)
        return _text_response("status=1")

    # Authenticate
    auth_error = _authenticate_device(device, params, request)
    if auth_error:
        return _text_response("status=0")

    # Parse event data
    seq_no = params.get("seq-no", "0")
    rollover = params.get("roll-over-count", "0")
    evt_id = params.get("evt_id", params.get("evt-id", "0"))
    seq_no_int = int(seq_no) if seq_no.isdigit() else 0
    rollover_int = int(rollover) if rollover.isdigit() else 0

    existing_event = _find_existing_event(device.device_id, seq_no_int, rollover_int, db)
    if existing_event:
        _log.info(
            "Push setevent: duplicate event ignored for device=%d seq=%d rollover=%d",
            device.device_id,
            seq_no_int,
            rollover_int,
        )
        next_seq = seq_no_int + 1 if seq_no.isdigit() else 1
        return _text_response(f"status=1 next-seq-no={next_seq} next-roll-over-count={rollover_int}")

    # Build timezone-aware event time
    event_time = _build_event_time(params, device)

    # Matrix COSEC Push API sends event fields as field-1 through field-5 (NOT detail-1)
    detail_1 = params.get("field-1", "")
    detail_2 = params.get("field-2", "")
    detail_3 = params.get("field-3", "")
    detail_4 = params.get("field-4", "")
    detail_5 = params.get("field-5", "")

    # Resolve tenant_id from matrix_user_id via DeviceUserMapping
    tenant_id = _resolve_tenant_id(device.device_id, detail_1, db)

    evt_id_int = int(evt_id) if evt_id.isdigit() else 0
    from app.api.services.logs.events import decode_auth_used, decode_direction, get_event_meta
    meta = get_event_meta(evt_id_int)
    auth_used = decode_auth_used(detail_3) or meta.auth_used
    direction = decode_direction(detail_3)

    _log.info("Push setevent: device=%d seq=%s evt_id=%s (%s) time=%s detail_1=%s tenant_id=%s auth=%s dir=%s",
              device.device_id, seq_no, evt_id, meta.description, event_time, detail_1, tenant_id, auth_used, direction)

    event = AccessEvent(
        company_id=device.company_id,
        device_id=device.device_id,
        tenant_id=tenant_id,
        event_type=meta.event_type,
        event_time=event_time,
        access_granted=meta.access_granted,
        auth_used=auth_used,
        direction=direction,
        cosec_event_id=evt_id_int,
        device_seq_number=seq_no_int,
        device_rollover_count=rollover_int,
        raw_data={
            "detail_1": detail_1, "detail_2": detail_2,
            "detail_3": detail_3, "detail_4": detail_4, "detail_5": detail_5,
        },
    )
    try:
        db.add(event)
        db.commit()

        # Broadcast to WebSocket clients
        try:
            from app.services.ws_manager import manager
            company_id_str = str(device.company_id) if device.company_id else None
            await manager.broadcast({
                "type": "access_event",
                "event_id": event.event_id,
                "device_id": device.device_id,
                "tenant_id": tenant_id,
                "event_type": event.event_type,
                "event_time": event.event_time.isoformat(),
                "access_granted": event.access_granted,
                "auth_used": auth_used,
                "cosec_event_id": event.cosec_event_id,
                "description": meta.description,
            }, company_id_str)
        except Exception:
            _log.exception("Push setevent: WebSocket broadcast failed")

    except IntegrityError:
        db.rollback()
        existing_event = _find_existing_event(device.device_id, seq_no_int, rollover_int, db)
        if existing_event:
            _log.info(
                "Push setevent: duplicate event already stored for device=%d seq=%d rollover=%d",
                device.device_id,
                seq_no_int,
                rollover_int,
            )
        else:
            _log.exception("Push setevent: failed to store event for device=%d", device.device_id)
    except Exception:
        db.rollback()
        _log.exception("Push setevent: failed to store event for device=%d", device.device_id)

    # Respond with next expected sequence
    next_seq = seq_no_int + 1 if seq_no.isdigit() else 1
    next_rollover = rollover_int
    return _text_response(f"status=1 next-seq-no={next_seq} next-roll-over-count={next_rollover}")


# ---------------------------------------------------------------------------
# GETCONFIG / UPDATECONFIG — device configuration sync
# ---------------------------------------------------------------------------

@router.api_route("/getconfig", methods=["GET", "POST"])
async def device_get_config(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Handle getconfig — device requests configuration updates.

    We return the oldest pending config for this device.
    Config-id 10 = User Configuration (create/update users on the device).
    """
    params = await _get_params(request)
    serial_no = params.get("serial-no", "")

    device = _find_device(serial_no, db)
    if not device:
        _log.warning("Push getconfig from unknown device: serial-no=%s", serial_no)
        return _text_response("status=0")

    # Authenticate
    auth_error = _authenticate_device(device, params, request)
    if auth_error:
        return _text_response("status=0")

    # Get the oldest pending config
    cfg = (
        db.query(DeviceConfig)
        .filter(DeviceConfig.device_id == device.device_id, DeviceConfig.status == "pending")
        .order_by(DeviceConfig.created_at)
        .first()
    )

    if not cfg:
        _log.debug("Push getconfig: device=%d no pending configs", device.device_id)
        return _text_response("status=0")

    # Mark as sent
    cfg.status = "sent"
    cfg.sent_at = datetime.now(timezone.utc)
    db.commit()

    cfg_params = cfg.params or {}
    # Strip private metadata keys (prefixed _) — never sent to device
    device_params = {k: v for k, v in cfg_params.items() if not k.startswith("_")}
    _log.info("Push getconfig: device=%d sending config_entry_id=%d config_id=%d params=%s",
              device.device_id, cfg.config_entry_id, cfg.config_id, _redact_params(device_params))

    # Build response: config-id=X param1=val1 param2=val2
    parts = [f"config-id={cfg.config_id}"]
    for k, v in device_params.items():
        parts.append(f"{k}={v}")
    return _text_response(" ".join(parts))


@router.api_route("/updateconfig", methods=["GET", "POST"])
async def device_update_config(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Handle updateconfig — device reports config update result."""
    params = await _get_params(request)
    _log.info("Push updateconfig params: %s", _redact_params(params))
    serial_no = params.get("serial-no", "")
    cfg_status = params.get("status", "0")
    config_id_str = params.get("config-id", "")

    device = _find_device(serial_no, db)
    if not device:
        _log.warning("Push updateconfig from unknown device: serial-no=%s", serial_no)
        return _text_response("cnfg-avlbl=0 status=1")

    # Authenticate
    auth_error = _authenticate_device(device, params, request)
    if auth_error:
        return _text_response("cnfg-avlbl=0 status=0")

    # Find the most recent sent config for this device with matching config-id
    config_id = int(config_id_str) if config_id_str.isdigit() else None
    query = (
        db.query(DeviceConfig)
        .filter(
            DeviceConfig.device_id == device.device_id,
            DeviceConfig.status == "sent",
        )
        .order_by(DeviceConfig.sent_at.desc())
    )
    if config_id is not None:
        query = query.filter(DeviceConfig.config_id == config_id)
    cfg = query.first()

    if cfg:
        cfg.status = "success" if cfg_status == "1" else "failed"
        cfg.completed_at = datetime.now(timezone.utc)
        if cfg_status != "1":
            cfg.error_message = f"Device reported config failure. config-id={config_id_str}"
        _log.info("Push updateconfig: device=%d config_entry_id=%d status=%s",
                  device.device_id, cfg.config_entry_id, cfg.status)

        # Post-process completed config (callbacks)
        try:
            from app.api.services.push.callbacks import handle_config_completion
            handle_config_completion(cfg, device, db)
        except Exception:
            _log.exception("Push updateconfig: callback error for config_entry_id=%d", cfg.config_entry_id)
    else:
        _log.warning("Push updateconfig: no matching sent config for device=%d config_id=%s",
                      device.device_id, config_id_str)

    # Check if more configs are pending
    next_pending = (
        db.query(DeviceConfig)
        .filter(DeviceConfig.device_id == device.device_id, DeviceConfig.status == "pending")
        .first()
    )
    cfg_available = 1 if next_pending else 0
    db.commit()

    return _text_response(f"cnfg-avlbl={cfg_available} status=1")


# ---------------------------------------------------------------------------
# OPERATIONS — track async operation status (used by frontend for push enrollment)
# ---------------------------------------------------------------------------

def _require_device_manager(current_user: AppUser) -> None:
    if current_user.role not in (UserRole.super_admin.value, UserRole.company_admin.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def get_operation_status_for_user(
    correlation_id: str,
    db: Session,
    current_user: AppUser,
) -> dict:
    """Get aggregate status of all commands/configs in an async operation.

    Returns 'pending' if any are pending/sent, 'success' if all done,
    'failed' if any failed, 'partial' if mix.
    """
    commands = (
        db.query(DeviceCommand)
        .filter(DeviceCommand.correlation_id == correlation_id)
        .all()
    )
    configs = (
        db.query(DeviceConfig)
        .filter(DeviceConfig.correlation_id == correlation_id)
        .all()
    )

    all_items = [
        *[{"type": "command", "id": c.command_id, "cmd_id": c.cmd_id, "status": c.status,
           "result": c.result, "error": c.error_message} for c in commands],
        *[{"type": "config", "id": c.config_entry_id, "config_id": c.config_id, "status": c.status,
           "error": c.error_message} for c in configs],
    ]

    if not all_items:
        return {"correlation_id": correlation_id, "status": "not_found", "items": []}

    # Enforce company scope — look up the device via the first command/config
    if current_user.role != UserRole.super_admin.value:
        device_id = (commands[0].device_id if commands else configs[0].device_id) if all_items else None
        if device_id is not None:
            device = db.query(Device).filter(Device.device_id == device_id).first()
            if device and device.company_id != current_user.company_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this operation")

    statuses = {item["status"] for item in all_items}
    if statuses <= {"success"}:
        overall = "success"
    elif statuses & {"pending", "sent"}:
        overall = "pending"
    elif "failed" in statuses and "success" in statuses:
        overall = "partial"
    else:
        overall = "failed"

    return {
        "correlation_id": correlation_id,
        "status": overall,
        "items": all_items,
    }


@router.get("/operations/{correlation_id}")
def get_operation_status(
    correlation_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return get_operation_status_for_user(correlation_id=correlation_id, db=db, current_user=current_user)


# ---------------------------------------------------------------------------
# ADMIN — queue commands & check status (called by frontend/dashboard, not device)
# ---------------------------------------------------------------------------


class QueueCommandRequest(BaseModel):
    device_id: int = Field(..., description="Target device ID")
    cmd_id: int = Field(..., description="Command ID (1=enroll, 4=set cred, 7=delete user, 22=get user count, etc.)")
    params: dict = Field(default_factory=dict, description="Command parameters (Matrix API param names)")
    correlation_id: str | None = Field(default=None, max_length=50, description="Optional internal tracking ID")


@router.post("/queue-command")
def queue_command_route(
    payload: QueueCommandRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    """Queue a command to be sent to a device on its next poll."""
    _require_device_manager(current_user)
    device = db.query(Device).filter(Device.device_id == payload.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if current_user.role != UserRole.super_admin.value and device.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this device")

    cmd = DeviceCommand(
        device_id=payload.device_id,
        cmd_id=payload.cmd_id,
        params=payload.params,
        correlation_id=payload.correlation_id,
    )
    db.add(cmd)
    db.commit()
    db.refresh(cmd)

    return {
        "command_id": cmd.command_id,
        "device_id": cmd.device_id,
        "cmd_id": cmd.cmd_id,
        "params": cmd.params,
        "status": cmd.status,
        "correlation_id": cmd.correlation_id,
        "message": "Command queued. Device will pick it up on next poll.",
    }


class QueueConfigRequest(BaseModel):
    device_id: int = Field(..., description="Target device ID")
    config_id: int = Field(..., description="Config ID (10=user config, 1=datetime, 2=device basic, etc.)")
    params: dict = Field(default_factory=dict, description="Config parameters")
    correlation_id: str | None = Field(default=None, max_length=50, description="Optional internal tracking ID")


@router.post("/queue-config")
def queue_config_route(
    payload: QueueConfigRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    """Queue a configuration to be sent to a device on its next poll."""
    _require_device_manager(current_user)
    device = db.query(Device).filter(Device.device_id == payload.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if current_user.role != UserRole.super_admin.value and device.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this device")

    cfg = DeviceConfig(
        device_id=payload.device_id,
        config_id=payload.config_id,
        params=payload.params,
        correlation_id=payload.correlation_id,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)

    return {
        "config_entry_id": cfg.config_entry_id,
        "device_id": cfg.device_id,
        "config_id": cfg.config_id,
        "params": cfg.params,
        "status": cfg.status,
        "correlation_id": cfg.correlation_id,
        "message": "Config queued. Device will pick it up on next poll.",
    }


@router.get("/commands/{device_id}")
def list_device_commands(
    device_id: int,
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[dict]:
    """List commands for a device. Optionally filter by status (pending/sent/success/failed)."""
    _require_device_manager(current_user)
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if current_user.role != UserRole.super_admin.value and device.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this device")
    query = db.query(DeviceCommand).filter(DeviceCommand.device_id == device_id)
    if status_filter:
        query = query.filter(DeviceCommand.status == status_filter)
    commands = query.order_by(DeviceCommand.created_at.desc()).limit(50).all()
    return [
        {
            "command_id": c.command_id,
            "cmd_id": c.cmd_id,
            "params": c.params,
            "status": c.status,
            "result": c.result,
            "correlation_id": c.correlation_id,
            "error_message": c.error_message,
            "created_at": str(c.created_at) if c.created_at else None,
            "sent_at": str(c.sent_at) if c.sent_at else None,
            "completed_at": str(c.completed_at) if c.completed_at else None,
        }
        for c in commands
    ]


@router.get("/devices/online")
def list_online_devices(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[dict]:
    """List devices that have connected via Push API (status=online)."""
    _require_device_manager(current_user)
    query = db.query(Device).filter(Device.status == "online")
    if current_user.role != UserRole.super_admin.value:
        query = query.filter(Device.company_id == current_user.company_id)
    devices = query.all()
    return [
        {
            "device_id": d.device_id,
            "device_serial_number": d.device_serial_number,
            "mac_address": d.mac_address,
            "ip_address": d.ip_address,
            "communication_mode": d.communication_mode,
            "status": d.status,
            "last_heartbeat": str(d.last_heartbeat) if d.last_heartbeat else None,
        }
        for d in devices
    ]
