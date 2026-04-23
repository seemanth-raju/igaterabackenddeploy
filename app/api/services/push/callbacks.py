"""Post-processing callbacks for Matrix Push API command/config completions.

When a device reports back via updatecmd/updateconfig, these functions
handle side effects: saving credentials, updating mappings, auto-queuing
follow-up commands (e.g., GET_CREDENTIAL after ENROLL_CREDENTIAL).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from database.models import (
    Credential,
    Device,
    DeviceCommand,
    DeviceConfig,
    DeviceUserMapping,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_tenant_id(correlation_id: str | None) -> int | None:
    """Extract an internal tenant ID from a correlation string if present.

    Supports formats:  "42",  "tenant:42:...",  "enroll-42-5-abc123"
    """
    if not correlation_id:
        return None
    if correlation_id.isdigit():
        return int(correlation_id)
    if correlation_id.startswith("tenant:"):
        tail = correlation_id.split("tenant:", 1)[1]
        tenant_part = tail.split(":", 1)[0]
        if tenant_part.isdigit():
            return int(tenant_part)
    # enroll-{tenant_id}-{device_id}-{uuid}
    if correlation_id.startswith("enroll-"):
        parts = correlation_id.split("-")
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
    return None


def _record_device_snapshot(device: Device, key: str, payload: dict) -> None:
    """Persist lightweight operational metadata on the device row."""
    current = dict(device.config or {})
    current[key] = {
        **payload,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    device.config = current


def _find_mapping_by_user_id(device_id: int, matrix_user_id: str, db: Session) -> DeviceUserMapping | None:
    return (
        db.query(DeviceUserMapping)
        .filter(
            DeviceUserMapping.device_id == device_id,
            DeviceUserMapping.matrix_user_id == matrix_user_id,
        )
        .first()
    )


# ---------------------------------------------------------------------------
# Command handlers (cmd_id → handler)
# ---------------------------------------------------------------------------


def _save_fingerprint_from_b64(
    template_b64: str,
    user_id: str,
    finger_no: int,
    device: Device,
    db: Session,
    source: str = "unknown",
) -> bool:
    """Save a base64-encoded fingerprint template to file + DB.

    Shared by ENROLL_CREDENTIAL (when device returns data-1 inline)
    and GET_CREDENTIAL (explicit template download).

    Returns True if saved successfully.
    """
    if not template_b64:
        return False

    # Resolve tenant_id from matrix_user_id
    mapping = _find_mapping_by_user_id(device.device_id, user_id, db)
    if not mapping:
        log.warning("%s: no mapping for user %s on device %d", source, user_id, device.device_id)
        return False

    tenant_id = mapping.tenant_id

    # Decode template.
    # Matrix COSEC devices send data via form-urlencoded POST where '+' is a space.
    # FastAPI decodes '+' → ' ', so we restore '+' before base64 decoding.
    # Also fix any missing padding that some device firmware omits.
    try:
        cleaned = template_b64.replace(" ", "+").strip()
        missing = (4 - len(cleaned) % 4) % 4
        if missing:
            cleaned += "=" * missing
        template_bytes = base64.b64decode(cleaned)
    except Exception:
        log.exception("%s: failed to decode base64 for user %s", source, user_id)
        return False

    if len(template_bytes) < 10:
        log.warning("%s: template too small (%d bytes) for user %s", source, len(template_bytes), user_id)
        return False

    # Save to file
    storage_dir = settings.fingerprint_storage_path
    os.makedirs(storage_dir, exist_ok=True)
    file_name = f"tenant_{tenant_id}_finger_{finger_no}.dat"
    file_path = os.path.join(storage_dir, file_name)

    with open(file_path, "wb") as f:
        f.write(template_bytes)

    file_hash = hashlib.sha256(template_bytes).hexdigest()

    # Upsert credential
    existing = (
        db.query(Credential)
        .filter(
            Credential.tenant_id == tenant_id,
            Credential.type == "finger",
            Credential.slot_index == finger_no,
        )
        .first()
    )
    if existing:
        existing.file_path = file_path
        existing.file_hash = file_hash
        existing.algorithm_version = "matrix_v1"
        log.info("%s: updated credential for tenant %d finger %d (%d bytes)",
                 source, tenant_id, finger_no, len(template_bytes))
    else:
        db.add(Credential(
            tenant_id=tenant_id,
            type="finger",
            slot_index=finger_no,
            file_path=file_path,
            file_hash=file_hash,
            algorithm_version="matrix_v1",
        ))
        log.info("%s: created credential for tenant %d finger %d (%d bytes)",
                 source, tenant_id, finger_no, len(template_bytes))

    # Update mapping as synced
    mapping.is_synced = True
    mapping.last_sync_at = datetime.now(timezone.utc)
    existing_resp = mapping.device_response or {}
    mapping.device_response = {**existing_resp, "fingerprint_pushed": True}
    db.flush()
    return True


def _on_enroll_credential_done(cmd: DeviceCommand, device: Device, db: Session) -> None:
    """cmd_id=1 (ENROLL_CREDENTIAL) succeeded — finger was scanned on device.

    Some device types (e.g. Path V2) return the fingerprint template directly
    in the ENROLL response as data-1. If present, save it immediately.
    Otherwise, queue GET_CREDENTIAL to download it separately.
    """
    params = cmd.params or {}
    result = cmd.result or {}
    user_id = params.get("user-id", "")
    finger_no = params.get("finger-no", "1")

    # Check if the device already returned the template inline
    template_b64 = result.get("data-1", "")
    if template_b64:
        log.info("ENROLL_CREDENTIAL for user %s on device %d returned data-1 inline — saving directly",
                 user_id, device.device_id)
        saved = _save_fingerprint_from_b64(
            template_b64, user_id, int(finger_no), device, db, source="ENROLL_CREDENTIAL",
        )
        if saved:
            return  # Done — no need to queue GET_CREDENTIAL

    # Template not in response — queue GET_CREDENTIAL to fetch it
    # NOTE: cred-type for GET/SET/DELETE uses different numbering than ENROLL:
    #   ENROLL: 1=Read Only Card, 2=Smart Card, 3=Finger, 4=Palm, 6=Face
    #   GET/SET/DELETE: 1=Card, 2=Finger, 3=Palm, 4=Face
    # So always hardcode "2" for Finger in GET_CREDENTIAL, never pass through ENROLL's cred-type.
    log.info("ENROLL_CREDENTIAL done for user %s on device %d — queuing GET_CREDENTIAL",
             user_id, device.device_id)

    from app.api.services.push.commands import CMD, queue_command
    queue_command(
        db=db,
        device_id=device.device_id,
        cmd_id=CMD.GET_CREDENTIAL,
        params={
            "cred-type": "2",  # GET: 1=Card, 2=Finger, 3=Palm, 4=Face
            "user-id": user_id,
            "finger-no": finger_no,
        },
        correlation_id=cmd.correlation_id,
    )


def _on_get_credential_done(cmd: DeviceCommand, device: Device, db: Session) -> None:
    """cmd_id=3 (GET_CREDENTIAL) succeeded — device returned fingerprint template."""
    params = cmd.params or {}
    result = cmd.result or {}
    user_id = params.get("user-id", "")
    finger_no = int(params.get("finger-no", "1"))

    template_b64 = result.get("data-1", "")
    saved = _save_fingerprint_from_b64(
        template_b64, user_id, finger_no, device, db, source="GET_CREDENTIAL",
    )
    if not saved:
        log.warning("GET_CREDENTIAL for user %s on device %d: no template saved", user_id, device.device_id)


def _on_set_credential_done(cmd: DeviceCommand, device: Device, db: Session) -> None:
    """cmd_id=4 (SET_CREDENTIAL) succeeded — fingerprint pushed to device.

    Update the DeviceUserMapping to mark fingerprint as synced.
    """
    params = cmd.params or {}
    user_id = params.get("user-id", "")

    mapping = _find_mapping_by_user_id(device.device_id, user_id, db)
    if mapping:
        mapping.is_synced = True
        mapping.last_sync_at = datetime.now(timezone.utc)
        existing_resp = mapping.device_response or {}
        mapping.device_response = {**existing_resp, "fingerprint_pushed": True}
        log.info("SET_CREDENTIAL synced for user %s on device %d", user_id, device.device_id)


def _on_delete_credential_done(_cmd: DeviceCommand, device: Device, _db: Session) -> None:
    """cmd_id=2 (DELETE_CREDENTIAL) succeeded."""
    log.info("DELETE_CREDENTIAL done for device %d", device.device_id)


def _on_delete_user_done(cmd: DeviceCommand, device: Device, db: Session) -> None:
    """cmd_id=7 (DELETE_USER) succeeded — remove the DeviceUserMapping."""
    params = cmd.params or {}
    user_id = params.get("user-id", "")

    mapping = _find_mapping_by_user_id(device.device_id, user_id, db)
    if mapping:
        db.delete(mapping)
        log.info("DELETE_USER: removed mapping for user %s on device %d", user_id, device.device_id)


def _on_get_user_count_done(cmd: DeviceCommand, device: Device, _db: Session) -> None:
    """cmd_id=22 (GET_USER_COUNT) succeeded."""
    result = cmd.result or {}
    _record_device_snapshot(device, "last_user_count_command", {
        "user_count": result.get("user-count"),
        "command_id": cmd.command_id,
    })


def _on_get_event_seq_done(cmd: DeviceCommand, device: Device, _db: Session) -> None:
    """cmd_id=16 (GET_CURRENT_EVENT_SEQ) succeeded."""
    result = cmd.result or {}
    _record_device_snapshot(device, "last_event_counter_command", {
        "seq_number": result.get("Cur-Seq-number", result.get("seq-number")),
        "rollover_count": result.get("Cur-rollover-count", result.get("roll-over-count")),
        "command_id": cmd.command_id,
    })


# ---------------------------------------------------------------------------
# Config handlers (config_id → handler)
# ---------------------------------------------------------------------------


def _on_user_config_done(cfg: DeviceConfig, device: Device, db: Session) -> None:
    """config_id=10 (User Configuration) — user created/updated on device (or failed).

    Create or update the DeviceUserMapping.
    """
    params = cfg.params or {}
    user_id = params.get("user-id", "")
    if not user_id:
        return

    if cfg.status == "failed":
        # Device rejected the user config — do NOT queue ENROLL.
        # If we enroll without a valid user profile the device creates the user
        # with default zone=0 (No Access) and the finger scan is useless.
        log.warning(
            "User config FAILED for user %s on device %d — skipping ENROLL_CREDENTIAL. "
            "Check the device accepted config-id=10 correctly.",
            user_id, device.device_id,
        )
        mapping = _find_mapping_by_user_id(device.device_id, user_id, db)
        if mapping:
            mapping.sync_error = "config_id=10 failed: device rejected user config"
            db.flush()
        return

    _record_device_snapshot(device, "last_user_config", {
        "config_entry_id": cfg.config_entry_id,
        "status": cfg.status,
        "user_id": user_id,
    })

    mapping = _find_mapping_by_user_id(device.device_id, user_id, db)
    now = datetime.now(timezone.utc)

    if mapping:
        mapping.last_sync_at = now
        mapping.last_sync_attempt_at = now
        mapping.sync_attempt_count = (mapping.sync_attempt_count or 0) + 1
        mapping.sync_error = None
        existing_resp = mapping.device_response or {}
        mapping.device_response = {**existing_resp, "user_created_via_push": True}
        log.info("User config synced for user %s on device %d", user_id, device.device_id)
    else:
        # Try to resolve tenant_id from the correlation_id only — never fall
        # back to int(user_id).  The device assigns matrix_user_ids from a
        # sequential slot counter (1, 2, 3 …) which are unrelated to internal
        # tenant_ids.  Using int(user_id) as tenant_id silently creates a
        # DeviceUserMapping pointing at the wrong (or non-existent) tenant —
        # the "ghost user" that appears in enrollment but not in the users list.
        tenant_id = _parse_tenant_id(cfg.correlation_id)
        if tenant_id is None:
            log.warning(
                "User config done for user %s on device %d but tenant_id could not be "
                "resolved from correlation_id=%s — skipping mapping creation",
                user_id, device.device_id, cfg.correlation_id,
            )
            return

        db.add(DeviceUserMapping(
            tenant_id=tenant_id,
            device_id=device.device_id,
            matrix_user_id=str(user_id),
            is_synced=False,  # Will be True after fingerprint push (SET_CREDENTIAL)
            last_sync_at=None,
            last_sync_attempt_at=now,
            sync_attempt_count=1,
            device_response={"user_created_via_push": True},
        ))
        log.info("User config: created mapping for tenant %d on device %d", tenant_id, device.device_id)

    db.flush()

    # If this config was queued as part of a capture-fingerprint flow, now queue ENROLL.
    # The finger index is stored as a private param (_enroll_finger_index) that was
    # stripped before sending to the device but preserved in the DB record.
    finger_index_str = (cfg.params or {}).get("_enroll_finger_index")
    if finger_index_str and finger_index_str.isdigit():
        from app.api.services.push.commands import CMD, queue_command
        queue_command(
            db=db,
            device_id=device.device_id,
            cmd_id=CMD.ENROLL_CREDENTIAL,
            params={
                "cred-type": "3",
                "user-id": user_id,
                "finger-no": finger_index_str,
            },
            correlation_id=cfg.correlation_id,
        )
        log.info("User config done — queued ENROLL_CREDENTIAL for user %s finger %s on device %d",
                 user_id, finger_index_str, device.device_id)


def _on_generic_config_done(cfg: DeviceConfig, device: Device, _db: Session) -> None:
    """Generic handler for non-user configs (datetime, device basic, etc.)."""
    _record_device_snapshot(device, "last_device_config", {
        "config_entry_id": cfg.config_entry_id,
        "config_id": cfg.config_id,
        "status": cfg.status,
    })


# ---------------------------------------------------------------------------
# Handler registries
# ---------------------------------------------------------------------------

_CMD_HANDLERS: dict[int, callable] = {
    1: _on_enroll_credential_done,   # ENROLL_CREDENTIAL
    2: _on_delete_credential_done,   # DELETE_CREDENTIAL
    3: _on_get_credential_done,      # GET_CREDENTIAL
    4: _on_set_credential_done,      # SET_CREDENTIAL
    7: _on_delete_user_done,         # DELETE_USER
    16: _on_get_event_seq_done,      # GET_CURRENT_EVENT_SEQ
    22: _on_get_user_count_done,     # GET_USER_COUNT
}

_CFG_HANDLERS: dict[int, callable] = {
    10: _on_user_config_done,  # User Configuration
}


def handle_command_completion(cmd: DeviceCommand, device: Device, db: Session) -> None:
    """React to a completed push command — dispatch to the appropriate handler."""
    if cmd.status == "failed":
        log.warning(
            "Push command failed — command_id=%s cmd_id=%s device=%d correlation=%s error=%s",
            cmd.command_id, cmd.cmd_id, device.device_id,
            cmd.correlation_id, cmd.error_message,
        )
        # Mark the mapping's sync error so operators can query for stuck enrollments.
        mapping = _find_mapping_by_user_id(
            device.device_id,
            (cmd.params or {}).get("user-id", ""),
            db,
        )
        if mapping:
            mapping.sync_error = f"cmd_id={cmd.cmd_id} failed: {cmd.error_message or 'no detail'}"
        db.flush()
        return

    if cmd.status != "success":
        return

    handler = _CMD_HANDLERS.get(cmd.cmd_id)
    if handler:
        handler(cmd, device, db)
    db.flush()
    log.debug("Processed push command callback for command_id=%s cmd_id=%s", cmd.command_id, cmd.cmd_id)


def handle_config_completion(cfg: DeviceConfig, device: Device, db: Session) -> None:
    """React to a completed push config — dispatch to the appropriate handler."""
    handler = _CFG_HANDLERS.get(cfg.config_id, _on_generic_config_done)
    handler(cfg, device, db)
    db.flush()
    log.debug("Processed push config callback for config_entry_id=%s config_id=%s",
              cfg.config_entry_id, cfg.config_id)
