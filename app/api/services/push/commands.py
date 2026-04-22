"""Helper functions to queue commands for devices via the Push API.

Instead of making direct HTTP calls to devices, we now queue commands
in the DeviceCommand table. The device picks them up when it polls.

Usage:
    from app.api.services.push.commands import queue_command, CMD

    queue_command(db, device_id=3, cmd_id=CMD.ENROLL_CREDENTIAL, params={
        "user-id": "42", "cred-type": "3", "finger-no": "1",
    })
"""

import base64
import logging
from enum import IntEnum

from sqlalchemy.orm import Session

from database.models import DeviceCommand, DeviceConfig, DeviceUserMapping, Tenant

_log = logging.getLogger(__name__)

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


class CMD(IntEnum):
    """Matrix COSEC Push API command IDs."""
    ENROLL_CREDENTIAL = 1
    DELETE_CREDENTIAL = 2
    GET_CREDENTIAL = 3
    SET_CREDENTIAL = 4
    DELETE_ALL_CREDENTIALS = 5
    GET_CREDENTIAL_COUNT = 6
    DELETE_USER = 7
    GET_USER_PHOTO = 8
    SET_USER_PHOTO = 9
    CLEAR_ALARM = 10
    ACKNOWLEDGE_ALARM = 11
    LOCK_DOOR = 12
    UNLOCK_DOOR = 13
    NORMALIZE_DOOR = 14
    OPEN_DOOR = 15
    GET_CURRENT_EVENT_SEQ = 16
    DEFAULT_DEVICE = 17
    REBOOT_DEVICE = 18
    ACTIVATE_AUX_RELAY = 19
    DEACTIVATE_AUX_RELAY = 20
    FIRMWARE_UPGRADE = 21
    GET_USER_COUNT = 22


# ---------------------------------------------------------------------------
# Low-level queue functions
# ---------------------------------------------------------------------------


def queue_command(
    db: Session,
    device_id: int,
    cmd_id: int,
    params: dict | None = None,
    correlation_id: str | None = None,
) -> DeviceCommand:
    """Queue a command to be sent to a device on its next poll.

    Args:
        db: Database session
        device_id: Target device ID
        cmd_id: Command ID (use CMD enum)
        params: Command-specific parameters (keys are the Matrix API param names)
        correlation_id: Optional internal tracking ID

    Returns:
        The created DeviceCommand record
    """
    cmd = DeviceCommand(
        device_id=device_id,
        cmd_id=cmd_id,
        params=params or {},
        correlation_id=correlation_id,
    )
    db.add(cmd)
    db.flush()
    _log.info("Queued command %d (cmd_id=%d) for device %d: %s",
              cmd.command_id, cmd_id, device_id, _redact_params(params))
    return cmd


def queue_config(
    db: Session,
    device_id: int,
    config_id: int,
    params: dict | None = None,
    correlation_id: str | None = None,
) -> DeviceConfig:
    """Queue a config to be sent to a device on its next poll.

    Args:
        db: Database session
        device_id: Target device ID
        config_id: Config ID (10=user config, 1=datetime, 2=device basic, etc.)
        params: Config-specific parameters
        correlation_id: Optional internal tracking ID

    Returns:
        The created DeviceConfig record
    """
    cfg = DeviceConfig(
        device_id=device_id,
        config_id=config_id,
        params=params or {},
        correlation_id=correlation_id,
    )
    db.add(cfg)
    db.flush()
    _log.info("Queued config %d (config_id=%d) for device %d: %s",
              cfg.config_entry_id, config_id, device_id, _redact_params(params))
    return cfg


def get_pending_commands(db: Session, device_id: int) -> list[DeviceCommand]:
    """Get all pending commands for a device."""
    return (
        db.query(DeviceCommand)
        .filter(DeviceCommand.device_id == device_id, DeviceCommand.status == "pending")
        .order_by(DeviceCommand.created_at)
        .all()
    )


def get_command_status(db: Session, command_id: int) -> DeviceCommand | None:
    """Check the status of a queued command."""
    return db.query(DeviceCommand).filter(DeviceCommand.command_id == command_id).first()


def resolve_matrix_user_id(db: Session, device_id: int, tenant_id: int) -> str:
    """Return the preferred Matrix user-id for a tenant on a device.

    Priority:
      1. Existing mapping for the target device
      2. Any existing mapping for this tenant on another device
      3. Fallback to tenant_id
    """
    mapping = (
        db.query(DeviceUserMapping)
        .filter(
            DeviceUserMapping.tenant_id == tenant_id,
            DeviceUserMapping.device_id == device_id,
        )
        .first()
    )
    if mapping and mapping.matrix_user_id:
        return str(mapping.matrix_user_id)

    mapping = (
        db.query(DeviceUserMapping)
        .filter(DeviceUserMapping.tenant_id == tenant_id)
        .first()
    )
    if mapping and mapping.matrix_user_id:
        return str(mapping.matrix_user_id)

    return str(tenant_id)


# ---------------------------------------------------------------------------
# High-level push enrollment helpers
# ---------------------------------------------------------------------------


def push_create_user(
    db: Session,
    device_id: int,
    tenant: Tenant,
    correlation_id: str,
    active: bool = True,
    valid_till: "datetime | None" = None,
    enroll_finger_index: int | None = None,
) -> DeviceConfig:
    """Queue config-id=10 to create/update a user on a push-mode device.

    This maps to the Matrix COSEC User Configuration (config_id=10).

    Args:
        valid_till: Per-device expiry override. Falls back to tenant.global_access_till
                    when not supplied. Pass the value from DeviceUserMapping.valid_till
                    so each device can have an independent validity window.
    """
    from datetime import datetime as _dt

    matrix_user_id = resolve_matrix_user_id(db, device_id, tenant.tenant_id)

    # Per-device date wins; fall back to global tenant date
    effective_till = valid_till if valid_till is not None else (
        tenant.global_access_till.date() if tenant.global_access_till else None
    )
    # Normalise datetime → date if caller passed a full datetime
    if isinstance(effective_till, _dt):
        effective_till = effective_till.date()

    params = {
        "user-id": matrix_user_id,
        "ref-user-id": matrix_user_id,
        "name": tenant.full_name[:15],
        "user-active": "1" if active else "0",
    }
    if effective_till:
        params["validity-enable"] = "1"
        params["validity-date-dd"] = str(effective_till.day)
        params["validity-date-mm"] = str(effective_till.month)
        params["validity-date-yyyy"] = str(effective_till.year)
    else:
        # No expiry — set a far-future date so the device never blocks access.
        # validity-enable=0 is unreliable across device models; explicit date is safer.
        params["validity-enable"] = "1"
        params["validity-date-dd"] = "31"
        params["validity-date-mm"] = "12"
        params["validity-date-yyyy"] = "2099"

    # Private metadata — stripped by getconfig before sending to device.
    # Tells the callback to queue ENROLL after user creation succeeds.
    if enroll_finger_index is not None:
        params["_enroll_finger_index"] = str(enroll_finger_index)

    return queue_config(
        db=db,
        device_id=device_id,
        config_id=10,
        params=params,
        correlation_id=correlation_id,
    )


def push_enroll_credential(
    db: Session,
    device_id: int,
    tenant_id: int,
    finger_index: int = 1,
    correlation_id: str | None = None,
) -> DeviceCommand:
    """Queue cmd-id=1 (ENROLL_CREDENTIAL) to trigger fingerprint enrollment on device.

    Device will enter enrollment mode and wait for user to scan finger.
    On success, the callback auto-queues GET_CREDENTIAL to fetch the template.
    """
    matrix_user_id = resolve_matrix_user_id(db, device_id, tenant_id)
    return queue_command(
        db=db,
        device_id=device_id,
        cmd_id=CMD.ENROLL_CREDENTIAL,
        params={
            "cred-type": "3",  # 3=Finger
            "user-id": matrix_user_id,
            "finger-no": str(finger_index),
        },
        correlation_id=correlation_id,
    )


def push_set_credential(
    db: Session,
    device_id: int,
    tenant_id: int,
    finger_index: int,
    template_path: str,
    correlation_id: str | None = None,
) -> DeviceCommand:
    """Queue cmd-id=4 (SET_CREDENTIAL) to push a fingerprint template to device.

    Reads the template file and base64-encodes it for the device.
    """
    with open(template_path, "rb") as f:
        template_bytes = f.read()
    template_b64 = base64.b64encode(template_bytes).decode("ascii")
    matrix_user_id = resolve_matrix_user_id(db, device_id, tenant_id)

    return queue_command(
        db=db,
        device_id=device_id,
        cmd_id=CMD.SET_CREDENTIAL,
        params={
            "cred-type": "2",  # SET/GET/DELETE: 1=Card, 2=Finger, 3=Palm, 4=Face
            "user-id": matrix_user_id,
            "finger-no": str(finger_index),
            "data-1": template_b64,
        },
        correlation_id=correlation_id,
    )


def push_get_credential(
    db: Session,
    device_id: int,
    tenant_id: int,
    finger_index: int = 1,
    correlation_id: str | None = None,
) -> DeviceCommand:
    """Queue cmd-id=3 (GET_CREDENTIAL) to download fingerprint template from device."""
    matrix_user_id = resolve_matrix_user_id(db, device_id, tenant_id)
    return queue_command(
        db=db,
        device_id=device_id,
        cmd_id=CMD.GET_CREDENTIAL,
        params={
            "cred-type": "2",  # GET/SET/DELETE: 1=Card, 2=Finger, 3=Palm, 4=Face
            "user-id": matrix_user_id,
            "finger-no": str(finger_index),
        },
        correlation_id=correlation_id,
    )


def push_delete_user(
    db: Session,
    device_id: int,
    tenant_id: int,
    correlation_id: str | None = None,
) -> DeviceCommand:
    """Queue cmd-id=7 (DELETE_USER) to remove a user from the device."""
    matrix_user_id = resolve_matrix_user_id(db, device_id, tenant_id)
    return queue_command(
        db=db,
        device_id=device_id,
        cmd_id=CMD.DELETE_USER,
        params={"user-id": matrix_user_id},
        correlation_id=correlation_id,
    )


def push_delete_credential(
    db: Session,
    device_id: int,
    tenant_id: int,
    cred_type: str = "2",  # DELETE: 1=Card, 2=Finger, 3=Palm, 4=Face
    correlation_id: str | None = None,
) -> DeviceCommand:
    """Queue cmd-id=2 (DELETE_CREDENTIAL) to remove credentials from device."""
    matrix_user_id = resolve_matrix_user_id(db, device_id, tenant_id)
    return queue_command(
        db=db,
        device_id=device_id,
        cmd_id=CMD.DELETE_CREDENTIAL,
        params={
            "cred-type": cred_type,
            "user-id": matrix_user_id,
        },
        correlation_id=correlation_id,
    )


def push_get_event_seq(
    db: Session,
    device_id: int,
    correlation_id: str | None = None,
) -> DeviceCommand:
    """Queue cmd-id=16 (GET_CURRENT_EVENT_SEQ) to get current event counter."""
    return queue_command(
        db=db,
        device_id=device_id,
        cmd_id=CMD.GET_CURRENT_EVENT_SEQ,
        params={},
        correlation_id=correlation_id,
    )


def push_get_user_count(
    db: Session,
    device_id: int,
    correlation_id: str | None = None,
) -> DeviceCommand:
    """Queue cmd-id=22 (GET_USER_COUNT) to get enrolled user count."""
    return queue_command(
        db=db,
        device_id=device_id,
        cmd_id=CMD.GET_USER_COUNT,
        params={},
        correlation_id=correlation_id,
    )
