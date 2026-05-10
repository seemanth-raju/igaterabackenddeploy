"""Tenant device enrollment — supports push and direct communication modes.

Push mode: commands are queued in DeviceCommand/DeviceConfig tables and the device
picks them up on its next poll (/push/poll → /push/getcmd → /push/updatecmd).

Direct mode: the server makes HTTP requests directly to the device API using its
ip_address/api_username/api_password. Results are synchronous — no correlation_id.

Enrollment flow (push):
  1. POST /tenants/{id}/capture-fingerprint
       → queues config-id=10 (create user) + cmd-id=1 (ENROLL_CREDENTIAL)
       → device prompts user for finger scan
       → callback auto-queues GET_CREDENTIAL to fetch & store template in DB

  2. POST /tenants/{id}/enroll  (after fingerprint is stored)
       → queues config-id=10 (create user) + cmd-id=4 (SET_CREDENTIAL)
       → pushes stored fingerprint template to target device(s)

  3. DELETE /tenants/{id}/unenroll
       → queues cmd-id=2 (DELETE_CREDENTIAL) + cmd-id=7 (DELETE_USER)

Enrollment flow (direct):
  1. POST /tenants/{id}/capture-fingerprint
       → calls device API: create user + trigger enrollment mode
       → user scans finger at device
       → call POST /tenants/{id}/extract-fingerprint to pull the template

  2. POST /tenants/{id}/enroll
       → calls device API: create user + push stored fingerprint template

  3. DELETE /tenants/{id}/unenroll
       → calls device API: delete fingerprint + delete user
"""

import uuid
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.services.companies.service import ensure_company_user_quota
from app.api.services.groups.service import validate_group_selection
from app.api.services.push.commands import (
    push_create_user,
    push_delete_user,
    push_get_credential,
    push_get_face,
    push_set_credential,
    push_set_face,
    resolve_matrix_user_id,
)
from database.models import (
    Credential,
    Device,
    DeviceAssignmentLog,
    DeviceUserMapping,
    Site,
    Tenant,
    TenantDeviceAccess,
    TenantSiteAccess,
)


# ---------------------------------------------------------------------------
# Validity helpers
# ---------------------------------------------------------------------------


def is_access_active(tenant: Tenant) -> bool:
    """Return True if the tenant should have user-active=1 on the device.

    The Matrix COSEC Push API (config-id=10) has no validity START date concept —
    only an end date (validity-date-dd/mm/yyyy). Setting user-active=0 to represent
    "access hasn't started yet" is wrong: it permanently disables the user on the
    device. The device's own validity-date field handles end-date expiry.

    Only fundamental enable/disable flags control user-active.
    """
    return bool(tenant.is_active and tenant.is_access_enabled)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _get_tenant_or_404(tenant_id: int, db: Session) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


def _get_device_or_404(device_id: int, db: Session) -> Device:
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Device {device_id} not found")
    return device


def _get_device_for_tenant_or_404(tenant: Tenant, device_id: int, db: Session) -> Device:
    device = _get_device_or_404(device_id, db)
    if device.company_id != tenant.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device does not belong to tenant's company",
        )
    return device


def _make_correlation_id(tenant_id: int, device_id: int) -> str:
    return f"enroll-{tenant_id}-{device_id}-{uuid.uuid4().hex[:8]}"


def _find_fingerprint_credential(tenant_id: int, db: Session, finger_index: int = 1) -> Credential | None:
    return (
        db.query(Credential)
        .filter(
            Credential.tenant_id == tenant_id,
            Credential.type == "finger",
            Credential.slot_index == finger_index,
        )
        .order_by(Credential.created_at.desc())
        .first()
    )


def _get_all_fingerprints(tenant_id: int, db: Session) -> list[Credential]:
    """Return all stored fingerprint credentials for a tenant that have a usable file."""
    return (
        db.query(Credential)
        .filter(
            Credential.tenant_id == tenant_id,
            Credential.type == "finger",
            Credential.file_path.isnot(None),
        )
        .order_by(Credential.slot_index)
        .all()
    )


def _find_card_credential(tenant_id: int, db: Session, slot_index: int = 1) -> Credential | None:
    return (
        db.query(Credential)
        .filter(
            Credential.tenant_id == tenant_id,
            Credential.type == "card",
            Credential.slot_index == slot_index,
        )
        .first()
    )


def _find_pin_credential(tenant_id: int, db: Session) -> Credential | None:
    return (
        db.query(Credential)
        .filter(Credential.tenant_id == tenant_id, Credential.type == "pin")
        .first()
    )


def _find_face_credential(tenant_id: int, db: Session, face_no: int = 1) -> Credential | None:
    return (
        db.query(Credential)
        .filter(
            Credential.tenant_id == tenant_id,
            Credential.type == "face",
            Credential.slot_index == face_no,
        )
        .order_by(Credential.created_at.desc())
        .first()
    )


def _upsert_credential(
    tenant_id: int,
    db: Session,
    ctype: str,
    slot_index: int = 1,
    raw_value: str | None = None,
    file_path: str | None = None,
) -> Credential:
    cred = (
        db.query(Credential)
        .filter(
            Credential.tenant_id == tenant_id,
            Credential.type == ctype,
            Credential.slot_index == slot_index,
        )
        .first()
    )
    if cred:
        if raw_value is not None:
            cred.raw_value = raw_value
        if file_path is not None:
            cred.file_path = file_path
    else:
        cred = Credential(
            tenant_id=tenant_id,
            type=ctype,
            slot_index=slot_index,
            raw_value=raw_value,
            file_path=file_path,
        )
        db.add(cred)
    db.flush()
    return cred


def _get_stored_card_pin(tenant_id: int, db: Session) -> tuple[str | None, str | None, str | None]:
    """Return (card1, card2, user_pin) raw values for a tenant from stored credentials."""
    c1 = _find_card_credential(tenant_id, db, slot_index=1)
    c2 = _find_card_credential(tenant_id, db, slot_index=2)
    pin = _find_pin_credential(tenant_id, db)
    return (
        c1.raw_value if c1 else None,
        c2.raw_value if c2 else None,
        pin.raw_value if pin else None,
    )


def _upsert_mapping(
    tenant_id: int,
    device_id: int,
    db: Session,
    *,
    synced: bool = False,
    fingerprint_pushed: bool = False,
    valid_from: datetime | None = None,
    valid_till: datetime | None = None,
) -> DeviceUserMapping:
    mapping = (
        db.query(DeviceUserMapping)
        .filter(DeviceUserMapping.tenant_id == tenant_id, DeviceUserMapping.device_id == device_id)
        .first()
    )
    now = db.query(func.current_timestamp()).scalar()
    if mapping:
        mapping.is_synced = synced
        mapping.last_sync_at = now if synced else mapping.last_sync_at
        mapping.last_sync_attempt_at = now
        mapping.sync_attempt_count = (mapping.sync_attempt_count or 0) + 1
        if fingerprint_pushed:
            existing = mapping.device_response or {}
            mapping.device_response = {**existing, "fingerprint_pushed": True}
        if valid_from is not None:
            mapping.valid_from = valid_from
        if valid_till is not None:
            mapping.valid_till = valid_till
        mapping.updated_at = now
    else:
        mapping = DeviceUserMapping(
            tenant_id=tenant_id,
            device_id=device_id,
            matrix_user_id=resolve_matrix_user_id(db, device_id, tenant_id),
            is_synced=synced,
            last_sync_at=now if synced else None,
            last_sync_attempt_at=now,
            sync_attempt_count=1,
            valid_from=valid_from,
            valid_till=valid_till,
            device_response={"fingerprint_pushed": fingerprint_pushed},
        )
        db.add(mapping)
    db.flush()
    return mapping


def _upsert_site_access_for_device(
    tenant_id: int,
    device: Device,
    db: Session,
    valid_from: datetime | None = None,
    valid_till: datetime | None = None,
) -> None:
    """Ensure a TenantSiteAccess + TenantDeviceAccess row exists for the device's site.

    Called when enrolling directly to a device so the member site_accesses view stays
    consistent with device-level enrollment.
    """
    if not device.site_id:
        return

    site_access = (
        db.query(TenantSiteAccess)
        .filter(TenantSiteAccess.tenant_id == tenant_id, TenantSiteAccess.site_id == device.site_id)
        .first()
    )
    if not site_access:
        site_access = TenantSiteAccess(
            tenant_id=tenant_id,
            site_id=device.site_id,
            valid_from=valid_from,
            valid_till=valid_till,
        )
        db.add(site_access)
        db.flush()

    dev_access = (
        db.query(TenantDeviceAccess)
        .filter(
            TenantDeviceAccess.tenant_id == tenant_id,
            TenantDeviceAccess.device_id == device.device_id,
        )
        .first()
    )
    if not dev_access:
        db.add(TenantDeviceAccess(
            tenant_id=tenant_id,
            device_id=device.device_id,
            site_access_id=site_access.site_access_id,
            valid_from=valid_from,
            valid_till=valid_till,
        ))


# ---------------------------------------------------------------------------
# Direct-mode helpers — call device API synchronously via MatrixDeviceClient
# ---------------------------------------------------------------------------


def _make_direct_client(device: Device):
    from app.services.matrix.device_client import MatrixDeviceClient
    if not device.ip_address:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device has no IP address configured for direct mode",
        )
    return MatrixDeviceClient(
        device_ip=device.ip_address,
        username=device.api_username or "admin",
        encrypted_password=device.api_password_encrypted or "",
        use_https=device.use_https,
        api_port=device.api_port,
    )


def _effective_valid_till_date(valid_till: datetime | None, tenant: Tenant):
    from datetime import datetime as _dt, date as _date
    effective = valid_till if valid_till is not None else tenant.global_access_till
    if effective is None:
        return None
    if isinstance(effective, _dt):
        return effective.date()
    if isinstance(effective, _date):
        return effective
    return None


def _direct_capture_fingerprint(
    tenant: Tenant,
    device: Device,
    db: Session,
    finger_index: int,
    performed_by,
    valid_from: datetime | None,
    valid_till: datetime | None,
) -> dict:
    client = _make_direct_client(device)
    matrix_user_id = resolve_matrix_user_id(db, device.device_id, tenant.tenant_id)

    create_result = client.create_user(
        user_id=matrix_user_id,
        name=tenant.full_name,
        active=is_access_active(tenant),
        validity_end_date=_effective_valid_till_date(valid_till, tenant),
    )
    if not create_result["success"]:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Device rejected user creation: {create_result['response']}",
        )

    enroll_result = client.trigger_fingerprint_enrollment(matrix_user_id, finger_index)

    _upsert_mapping(tenant.tenant_id, device.device_id, db, synced=True,
                    valid_from=valid_from, valid_till=valid_till)
    _upsert_site_access_for_device(tenant.tenant_id, device, db, valid_from=valid_from, valid_till=valid_till)
    _log_assignment(tenant.tenant_id, device.device_id, "capture", db, performed_by=performed_by, synced=True)
    db.commit()

    return {
        "tenant_id": tenant.tenant_id,
        "device_id": device.device_id,
        "mode": "direct",
        "status": "enrollment_triggered" if enroll_result["success"] else "user_created",
        "enrollment_triggered": enroll_result["success"],
        "message": (
            "User created and fingerprint enrollment mode triggered. "
            "Have the user scan their finger at the device, then call "
            "POST /tenants/{tenant_id}/extract-fingerprint to store the template."
            if enroll_result["success"]
            else "User created on device but failed to trigger enrollment mode. Try again."
        ),
    }


def _direct_enroll(
    tenant: Tenant,
    device: Device,
    db: Session,
    _finger_index: int,
    performed_by,
    valid_from: datetime | None,
    valid_till: datetime | None,
) -> dict:
    client = _make_direct_client(device)
    matrix_user_id = resolve_matrix_user_id(db, device.device_id, tenant.tenant_id)
    supported = set(device.credential_types or ["finger"])
    card1, card2, user_pin = _get_stored_card_pin(tenant.tenant_id, db)

    create_result = client.create_user(
        user_id=matrix_user_id,
        name=tenant.full_name,
        active=is_access_active(tenant),
        validity_end_date=_effective_valid_till_date(valid_till, tenant),
        card1=card1 if "card" in supported else None,
        card2=card2 if "card" in supported else None,
        user_pin=user_pin if "pin" in supported else None,
    )
    if not create_result["success"]:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Device rejected user creation: {create_result['response']}",
        )

    fp_pushed = False
    if "finger" in supported:
        for fp in _get_all_fingerprints(tenant.tenant_id, db):
            result = client.import_fingerprint(matrix_user_id, fp.file_path, fp.slot_index)
            if result["success"]:
                fp_pushed = True

    face_pushed = False
    if "face" in supported:
        face_cred = _find_face_credential(tenant.tenant_id, db, face_no=1)
        if face_cred and face_cred.file_path:
            face_result = client.import_face_template(matrix_user_id, face_cred.file_path, 1)
            face_pushed = face_result["success"]

    _upsert_mapping(tenant.tenant_id, device.device_id, db, synced=True,
                    valid_from=valid_from, valid_till=valid_till)
    _upsert_site_access_for_device(tenant.tenant_id, device, db, valid_from=valid_from, valid_till=valid_till)
    _log_assignment(tenant.tenant_id, device.device_id, "enroll", db, performed_by=performed_by, synced=True)
    db.commit()

    return {
        "tenant_id": tenant.tenant_id,
        "device_id": device.device_id,
        "mode": "direct",
        "status": "success",
        "fingerprint_pushed": fp_pushed,
        "face_pushed": face_pushed,
        "message": "User created and credentials pushed to device.",
    }


def _direct_extract_fingerprint(
    tenant: Tenant,
    device: Device,
    db: Session,
    finger_index: int,
    performed_by,
) -> dict:
    client = _make_direct_client(device)
    matrix_user_id = resolve_matrix_user_id(db, device.device_id, tenant.tenant_id)

    content, file_path = client.extract_fingerprint(matrix_user_id, finger_index)
    if not content or not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No fingerprint found on device. Has the user scanned their finger yet?",
        )

    cred = (
        db.query(Credential)
        .filter(
            Credential.tenant_id == tenant.tenant_id,
            Credential.type == "finger",
            Credential.slot_index == finger_index,
        )
        .first()
    )
    if cred:
        cred.file_path = file_path
    else:
        db.add(Credential(
            tenant_id=tenant.tenant_id,
            type="finger",
            slot_index=finger_index,
            file_path=file_path,
        ))

    _upsert_mapping(tenant.tenant_id, device.device_id, db, synced=True)
    _log_assignment(tenant.tenant_id, device.device_id, "extract_fingerprint", db,
                    performed_by=performed_by, synced=True)
    db.commit()

    return {
        "tenant_id": tenant.tenant_id,
        "device_id": device.device_id,
        "mode": "direct",
        "status": "success",
        "finger_index": finger_index,
        "message": "Fingerprint template extracted from device and stored.",
    }


def _direct_unenroll(
    tenant: Tenant,
    device: Device,
    db: Session,
    performed_by,
) -> dict:
    client = _make_direct_client(device)
    matrix_user_id = resolve_matrix_user_id(db, device.device_id, tenant.tenant_id)

    client.delete_fingerprint(matrix_user_id)
    delete_result = client.delete_user(matrix_user_id)

    mapping = (
        db.query(DeviceUserMapping)
        .filter(
            DeviceUserMapping.tenant_id == tenant.tenant_id,
            DeviceUserMapping.device_id == device.device_id,
        )
        .first()
    )
    if mapping:
        db.delete(mapping)

    _log_assignment(tenant.tenant_id, device.device_id, "unenroll", db, performed_by=performed_by)
    db.commit()

    return {
        "tenant_id": tenant.tenant_id,
        "device_id": device.device_id,
        "mode": "direct",
        "status": "success" if delete_result["success"] else "partial",
        "message": (
            "User removed from device."
            if delete_result["success"]
            else f"Fingerprint deleted but user removal returned: {delete_result['response']}"
        ),
    }


def _direct_update(
    tenant: Tenant,
    device: Device,
    db: Session,
    performed_by,
    valid_from: datetime | None,
    valid_till: datetime | None,
) -> dict:
    client = _make_direct_client(device)
    matrix_user_id = resolve_matrix_user_id(db, device.device_id, tenant.tenant_id)
    supported = set(device.credential_types or ["finger"])
    card1, card2, user_pin = _get_stored_card_pin(tenant.tenant_id, db)

    create_result = client.create_user(
        user_id=matrix_user_id,
        name=tenant.full_name,
        active=is_access_active(tenant),
        validity_end_date=_effective_valid_till_date(valid_till, tenant),
        card1=card1 if "card" in supported else None,
        card2=card2 if "card" in supported else None,
        user_pin=user_pin if "pin" in supported else None,
    )

    fp_pushed = False
    if "finger" in supported:
        for fp in _get_all_fingerprints(tenant.tenant_id, db):
            result = client.import_fingerprint(matrix_user_id, fp.file_path, fp.slot_index)
            if result["success"]:
                fp_pushed = True

    face_pushed = False
    if "face" in supported:
        face_cred = _find_face_credential(tenant.tenant_id, db, face_no=1)
        if face_cred and face_cred.file_path:
            face_result = client.import_face_template(matrix_user_id, face_cred.file_path, 1)
            face_pushed = face_result["success"]

    _upsert_mapping(tenant.tenant_id, device.device_id, db, synced=create_result["success"],
                    valid_from=valid_from, valid_till=valid_till)
    _log_assignment(tenant.tenant_id, device.device_id, "update", db,
                    performed_by=performed_by, synced=create_result["success"])
    db.commit()

    return {
        "tenant_id": tenant.tenant_id,
        "device_id": device.device_id,
        "mode": "direct",
        "status": "success" if create_result["success"] else "failed",
        "fingerprint_pushed": fp_pushed,
        "face_pushed": face_pushed,
        "message": (
            "User synced to device."
            if create_result["success"]
            else f"Device returned: {create_result['response']}"
        ),
    }


def _log_assignment(
    tenant_id: int,
    device_id: int,
    action: str,
    db: Session,
    performed_by=None,
    reason: str | None = None,
    synced: bool = False,
) -> None:
    db.add(DeviceAssignmentLog(
        tenant_id=tenant_id,
        device_id=device_id,
        action=action,
        performed_by=performed_by,
        reason=reason,
        synced_to_device=synced,
    ))


def _sync_tenant_global_validity(
    tenant: Tenant,
    valid_from: datetime | None,
    valid_till: datetime | None,
) -> None:
    if valid_from is not None:
        tenant.global_access_from = valid_from
    if valid_till is not None:
        tenant.global_access_till = valid_till


# ---------------------------------------------------------------------------
# Public API — branches on communication_mode: push queues commands, direct calls device
# ---------------------------------------------------------------------------


def register_and_capture_fingerprint(
    tenant_id: int,
    device_id: int,
    db: Session,
    finger_index: int = 1,
    performed_by=None,
    valid_from: datetime | None = None,
    valid_till: datetime | None = None,
) -> dict:
    """Capture flow: create user on device + trigger fingerprint enrollment mode.

    Queues:
      1. config-id=10  → create/update user on device
      2. cmd-id=1      → ENROLL_CREDENTIAL (device prompts user for finger scan)
      3. Callback auto-queues cmd-id=3 (GET_CREDENTIAL) after scan completes

    The user must physically present their finger at the device.
    Poll /api/push/operations/{correlation_id} to track completion.
    """
    tenant = _get_tenant_or_404(tenant_id, db)
    device = _get_device_for_tenant_or_404(tenant, device_id, db)
    _sync_tenant_global_validity(tenant, valid_from, valid_till)

    if len(tenant.full_name) > 15:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Name '{tenant.full_name}' exceeds 15-character device limit.",
        )

    if device.communication_mode == "direct":
        return _direct_capture_fingerprint(
            tenant, device, db, finger_index, performed_by, valid_from, valid_till
        )

    correlation_id = _make_correlation_id(tenant_id, device_id)

    # Step 1: create/update user on device (config-id=10)
    # _enroll_finger_index private param tells the callback to queue ENROLL after user creation
    push_create_user(
        db, device_id, tenant, correlation_id,
        active=is_access_active(tenant),
        valid_till=valid_till,
        enroll_finger_index=finger_index,
    )

    _upsert_mapping(tenant_id, device_id, db, synced=False, valid_from=valid_from, valid_till=valid_till)
    _upsert_site_access_for_device(tenant_id, device, db, valid_from=valid_from, valid_till=valid_till)
    _log_assignment(tenant_id, device_id, "capture", db, performed_by=performed_by)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "mode": "push",
        "status": "queued",
        "correlation_id": correlation_id,
        "message": (
            "User creation queued. Device will prompt for finger scan on next poll. "
            "Poll GET /api/push/operations/{correlation_id} for status."
        ),
    }


def extract_fingerprint_from_device(
    tenant_id: int,
    device_id: int,
    db: Session,
    finger_index: int = 1,
    performed_by=None,
    valid_from: datetime | None = None,
    valid_till: datetime | None = None,
) -> dict:
    """Download an existing fingerprint template from a device and store it in DB.

    Use this when the user has already scanned their finger on the device
    but the template was not captured (e.g. device was enrolled manually).

    Queues cmd-id=3 (GET_CREDENTIAL).
    """
    tenant = _get_tenant_or_404(tenant_id, db)
    device = _get_device_for_tenant_or_404(tenant, device_id, db)
    _sync_tenant_global_validity(tenant, valid_from, valid_till)

    if device.communication_mode == "direct":
        return _direct_extract_fingerprint(tenant, device, db, finger_index, performed_by)

    correlation_id = _make_correlation_id(tenant_id, device_id)
    push_get_credential(db, device_id, tenant_id, finger_index, correlation_id)
    _upsert_mapping(tenant_id, device_id, db, synced=False, valid_from=valid_from, valid_till=valid_till)
    _log_assignment(tenant_id, device_id, "extract_fingerprint", db, performed_by=performed_by)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "mode": "push",
        "status": "queued",
        "correlation_id": correlation_id,
        "message": "GET_CREDENTIAL queued. Poll GET /api/push/operations/{correlation_id} for status.",
    }


def enroll_to_device(
    tenant_id: int,
    device_id: int,
    db: Session,
    finger_index: int = 1,
    performed_by=None,
    valid_from: datetime | None = None,
    valid_till: datetime | None = None,
    update_tenant_validity: bool = True,
) -> dict:
    """Enroll a tenant on a device — push stored fingerprint template to device.

    Queues:
      1. config-id=10  → create/update user on device
      2. cmd-id=4      → SET_CREDENTIAL (push fingerprint template)

    Requires a fingerprint to already be stored in DB (from a prior capture).
    No physical presence at the device is needed.
    """
    tenant = _get_tenant_or_404(tenant_id, db)
    device = _get_device_for_tenant_or_404(tenant, device_id, db)
    if update_tenant_validity:
        _sync_tenant_global_validity(tenant, valid_from, valid_till)

    if len(tenant.full_name) > 15:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Name '{tenant.full_name}' exceeds 15-character device limit.",
        )

    if device.communication_mode == "direct":
        return _direct_enroll(tenant, device, db, finger_index, performed_by, valid_from, valid_till)

    correlation_id = _make_correlation_id(tenant_id, device_id)
    supported = set(device.credential_types or ["finger"])
    card1, card2, user_pin = _get_stored_card_pin(tenant_id, db)

    push_create_user(
        db, device_id, tenant, correlation_id,
        active=is_access_active(tenant), valid_till=valid_till,
        card1=card1 if "card" in supported else None,
        card2=card2 if "card" in supported else None,
        user_pin=user_pin if "pin" in supported else None,
    )

    fp_queued = 0
    if "finger" in supported:
        for fp in _get_all_fingerprints(tenant_id, db):
            push_set_credential(db, device_id, tenant_id, fp.slot_index, fp.file_path, correlation_id)
            fp_queued += 1

    face_queued = False
    if "face" in supported:
        face_cred = _find_face_credential(tenant_id, db, face_no=1)
        if face_cred and face_cred.file_path:
            push_set_face(db, device_id, tenant_id, 1, face_cred.file_path, correlation_id)
            face_queued = True

    _upsert_mapping(tenant_id, device_id, db, synced=False, valid_from=valid_from, valid_till=valid_till)
    _upsert_site_access_for_device(tenant_id, device, db, valid_from=valid_from, valid_till=valid_till)
    _log_assignment(tenant_id, device_id, "enroll", db, performed_by=performed_by)
    db.commit()

    parts = []
    if fp_queued:
        parts.append(f"{fp_queued} finger(s)")
    if face_queued:
        parts.append("face")
    if card1 and "card" in supported:
        parts.append("card")
    if user_pin and "pin" in supported:
        parts.append("PIN")
    cred_summary = (", ".join(parts) + " queued") if parts else "no biometric stored — capture one first"
    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "mode": "push",
        "status": "queued",
        "correlation_id": correlation_id,
        "fingerprint_queued": fp_queued > 0,
        "fingers_queued": fp_queued,
        "face_queued": face_queued,
        "message": f"User creation + {cred_summary}. Poll GET /api/push/operations/{{correlation_id}} for status.",
    }


def enroll_to_devices_bulk(
    tenant_id: int,
    devices: "list[dict]",
    db: Session,
    finger_index: int = 1,
    performed_by=None,
) -> dict:
    """Enroll a tenant on multiple devices, pushing stored fingerprint to each.

    Args:
        devices: List of dicts with keys: device_id (required), valid_from, valid_till (optional).
    """
    _get_tenant_or_404(tenant_id, db)

    results: list[dict] = []
    succeeded = 0
    failed = 0

    for item in devices:
        did = item["device_id"]
        vf = item.get("valid_from")
        vt = item.get("valid_till")
        try:
            result = enroll_to_device(
                tenant_id, did, db,
                finger_index=finger_index,
                performed_by=performed_by,
                valid_from=vf,
                valid_till=vt,
                update_tenant_validity=False,
            )
            results.append({"device_id": did, "success": True,
                            "correlation_id": result.get("correlation_id"),
                            "fingerprint_queued": result.get("fingerprint_queued")})
            succeeded += 1
        except HTTPException as exc:
            db.rollback()
            results.append({"device_id": did, "success": False, "error": exc.detail})
            _log_assignment(tenant_id, did, "enroll", db, performed_by=performed_by, reason=exc.detail)
            db.flush()
            failed += 1

    db.commit()
    return {
        "tenant_id": tenant_id,
        "total": len(devices),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


def update_tenant_on_device(
    tenant_id: int,
    device_id: int,
    db: Session,
    performed_by=None,
    valid_from: datetime | None = None,
    valid_till: datetime | None = None,
) -> dict:
    """Re-sync tenant details and fingerprint on a device.

    Queues:
      1. config-id=10  → update user record on device (name, validity, active status)
      2. cmd-id=4      → SET_CREDENTIAL (re-push fingerprint if stored)

    Per-device validity is preserved unless explicitly overridden.
    """
    tenant = _get_tenant_or_404(tenant_id, db)
    device = _get_device_for_tenant_or_404(tenant, device_id, db)

    # Preserve existing per-device validity unless caller overrides
    existing_mapping = (
        db.query(DeviceUserMapping)
        .filter(DeviceUserMapping.tenant_id == tenant_id, DeviceUserMapping.device_id == device_id)
        .first()
    )
    effective_valid_till = valid_till if valid_till is not None else (
        existing_mapping.valid_till if existing_mapping else None
    )
    effective_valid_from = valid_from if valid_from is not None else (
        existing_mapping.valid_from if existing_mapping else None
    )

    if device.communication_mode == "direct":
        return _direct_update(
            tenant, device, db, performed_by, effective_valid_from, effective_valid_till
        )

    correlation_id = _make_correlation_id(tenant_id, device_id)
    supported = set(device.credential_types or ["finger"])
    card1, card2, user_pin = _get_stored_card_pin(tenant_id, db)

    push_create_user(
        db, device_id, tenant, correlation_id,
        active=is_access_active(tenant), valid_till=effective_valid_till,
        card1=card1 if "card" in supported else None,
        card2=card2 if "card" in supported else None,
        user_pin=user_pin if "pin" in supported else None,
    )

    fp_queued = 0
    if "finger" in supported:
        for fp in _get_all_fingerprints(tenant_id, db):
            push_set_credential(db, device_id, tenant_id, fp.slot_index, fp.file_path, correlation_id)
            fp_queued += 1

    face_queued = False
    if "face" in supported:
        face_cred = _find_face_credential(tenant_id, db, face_no=1)
        if face_cred and face_cred.file_path:
            push_set_face(db, device_id, tenant_id, 1, face_cred.file_path, correlation_id)
            face_queued = True

    _upsert_mapping(tenant_id, device_id, db, synced=False,
                    valid_from=effective_valid_from, valid_till=effective_valid_till)
    _log_assignment(tenant_id, device_id, "update", db, performed_by=performed_by)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "mode": "push",
        "status": "queued",
        "correlation_id": correlation_id,
        "fingerprint_queued": fp_queued > 0,
        "fingers_queued": fp_queued,
        "face_queued": face_queued,
        "message": "Sync commands queued. Poll GET /api/push/operations/{correlation_id} for status.",
    }


def update_tenant_on_devices_bulk(
    tenant_id: int,
    device_ids: list[int],
    db: Session,
    performed_by=None,
) -> dict:
    """Re-sync tenant details on multiple devices."""
    _get_tenant_or_404(tenant_id, db)

    results: list[dict] = []
    succeeded = 0
    failed = 0

    for did in device_ids:
        try:
            result = update_tenant_on_device(tenant_id, did, db, performed_by=performed_by)
            results.append({"device_id": did, "success": True,
                            "correlation_id": result.get("correlation_id")})
            succeeded += 1
        except HTTPException as exc:
            db.rollback()
            results.append({"device_id": did, "success": False, "error": exc.detail})
            _log_assignment(tenant_id, did, "update", db, performed_by=performed_by, reason=exc.detail)
            db.flush()
            failed += 1

    db.commit()
    return {
        "tenant_id": tenant_id,
        "total": len(device_ids),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


def unenroll_from_device(
    tenant_id: int,
    device_id: int,
    db: Session,
    performed_by=None,
) -> dict:
    """Remove a tenant from a single device.

    Queues:
      1. cmd-id=2  → DELETE_CREDENTIAL
      2. cmd-id=7  → DELETE_USER

    Callback removes the DeviceUserMapping after DELETE_USER succeeds.
    """
    tenant = _get_tenant_or_404(tenant_id, db)
    device = _get_device_for_tenant_or_404(tenant, device_id, db)

    if device.communication_mode == "direct":
        return _direct_unenroll(tenant, device, db, performed_by)

    correlation_id = _make_correlation_id(tenant_id, device_id)
    # DELETE_USER (cmd-id=7) removes the user and all their biometric/card data on
    # the device regardless of credential type (finger/face/card).  A separate
    # DELETE_CREDENTIAL is not needed and breaks on devices that don't support
    # the specific cred-type (e.g. VEGA FAX has no fingerprint slot).
    push_delete_user(db, device_id, tenant_id, correlation_id)
    _log_assignment(tenant_id, device_id, "unenroll", db, performed_by=performed_by)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "mode": "push",
        "status": "queued",
        "correlation_id": correlation_id,
        "message": "Unenrollment commands queued. Poll GET /api/push/operations/{correlation_id} for status.",
    }


def unenroll_from_devices_bulk(
    tenant_id: int,
    device_ids: list[int],
    db: Session,
    performed_by=None,
) -> dict:
    """Remove a tenant from multiple devices."""
    _get_tenant_or_404(tenant_id, db)

    results: list[dict] = []
    succeeded = 0
    failed = 0

    for did in device_ids:
        try:
            result = unenroll_from_device(tenant_id, did, db, performed_by=performed_by)
            results.append({"device_id": did, "success": True,
                            "correlation_id": result.get("correlation_id")})
            succeeded += 1
        except HTTPException as exc:
            db.rollback()
            results.append({"device_id": did, "success": False, "error": exc.detail})
            _log_assignment(tenant_id, did, "unenroll", db, performed_by=performed_by, reason=exc.detail)
            db.flush()
            failed += 1

    db.commit()
    return {
        "tenant_id": tenant_id,
        "total": len(device_ids),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


def enroll_to_site(
    tenant_id: int,
    site_id: int,
    db: Session,
    finger_index: int = 1,
    valid_from: "datetime | None" = None,
    valid_till: "datetime | None" = None,
    performed_by=None,
) -> dict:
    """Grant a tenant access to a site and enroll them on every active device in that site.

    In one call this:
      1. Upserts a TenantSiteAccess record (the DB permission record)
      2. For every active device in the site:
         a. Upserts a TenantDeviceAccess record (links device to site access)
         b. Queues config-id=10 + SET_CREDENTIAL push commands (actual enrollment)
            → DeviceUserMapping is created/updated per device

    Returns immediately with correlation_ids per device. Poll each via
    GET /api/push/operations/{correlation_id} to track completion.
    """
    tenant = _get_tenant_or_404(tenant_id, db)

    site = db.query(Site).filter(Site.site_id == site_id).first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Site {site_id} not found")
    if not site.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Site {site_id} is inactive")
    if site.company_id != tenant.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Site does not belong to tenant's company")

    # 1. Upsert TenantSiteAccess
    site_access = (
        db.query(TenantSiteAccess)
        .filter(TenantSiteAccess.tenant_id == tenant_id, TenantSiteAccess.site_id == site_id)
        .first()
    )
    if site_access:
        if valid_from is not None:
            site_access.valid_from = valid_from
        if valid_till is not None:
            site_access.valid_till = valid_till
    else:
        site_access = TenantSiteAccess(
            tenant_id=tenant_id,
            site_id=site_id,
            valid_from=valid_from,
            valid_till=valid_till,
        )
        db.add(site_access)

    db.flush()  # get site_access.site_access_id

    # 2. Get all active devices in the site
    devices = (
        db.query(Device)
        .filter(Device.site_id == site_id, Device.is_active == True)
        .all()
    )

    if not devices:
        db.commit()
        return {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "site_access_id": site_access.site_access_id,
            "total_devices": 0,
            "succeeded": 0,
            "failed": 0,
            "results": [],
            "message": "Site access recorded but no active devices found in this site.",
        }

    # 3. Enroll on each device
    results: list[dict] = []
    succeeded = 0
    failed = 0

    for device in devices:
        try:
            # Upsert TenantDeviceAccess (links device → site access in DB)
            dev_access = (
                db.query(TenantDeviceAccess)
                .filter(
                    TenantDeviceAccess.tenant_id == tenant_id,
                    TenantDeviceAccess.device_id == device.device_id,
                )
                .first()
            )
            if dev_access:
                dev_access.site_access_id = site_access.site_access_id
                if valid_from is not None:
                    dev_access.valid_from = valid_from
                if valid_till is not None:
                    dev_access.valid_till = valid_till
            else:
                db.add(TenantDeviceAccess(
                    tenant_id=tenant_id,
                    device_id=device.device_id,
                    site_access_id=site_access.site_access_id,
                    valid_from=valid_from,
                    valid_till=valid_till,
                ))

            # Queue push enrollment commands + upsert DeviceUserMapping
            correlation_id = _make_correlation_id(tenant_id, device.device_id)
            push_create_user(
                db, device.device_id, tenant, correlation_id,
                active=is_access_active(tenant), valid_till=valid_till,
            )
            credential = _find_fingerprint_credential(tenant_id, db, finger_index)
            fp_queued = False
            if credential and credential.file_path:
                push_set_credential(db, device.device_id, tenant_id, finger_index, credential.file_path, correlation_id)
                fp_queued = True

            _upsert_mapping(tenant_id, device.device_id, db, synced=False, valid_from=valid_from, valid_till=valid_till)
            _log_assignment(tenant_id, device.device_id, "enroll_site", db, performed_by=performed_by)

            results.append({
                "device_id": device.device_id,
                "success": True,
                "correlation_id": correlation_id,
                "fingerprint_queued": fp_queued,
            })
            succeeded += 1

        except Exception as exc:
            db.rollback()
            results.append({"device_id": device.device_id, "success": False, "error": str(exc)})
            failed += 1

    db.commit()

    return {
        "tenant_id": tenant_id,
        "site_id": site_id,
        "site_access_id": site_access.site_access_id,
        "total_devices": len(devices),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
        "message": (
            f"Site access recorded. Enrollment queued for {succeeded}/{len(devices)} device(s). "
            "Poll each correlation_id for completion status."
        ),
    }


def update_device_access_validity(
    tenant_id: int,
    device_id: int,
    db: Session,
    valid_from: datetime | None = None,
    valid_till: datetime | None = None,
    performed_by=None,
) -> dict:
    """Update the per-device validity window and re-sync the user config on the device.

    Lighter than a full re-enroll — no fingerprint re-push unless one is stored.
    Queues config-id=10 to update validity dates on the device.
    """
    return update_tenant_on_device(
        tenant_id=tenant_id,
        device_id=device_id,
        db=db,
        performed_by=performed_by,
        valid_from=valid_from,
        valid_till=valid_till,
    )


def set_card_credential(
    tenant_id: int,
    device_id: int,
    card1: str,
    db: Session,
    card2: str | None = None,
    performed_by=None,
    valid_from: datetime | None = None,
    valid_till: datetime | None = None,
) -> dict:
    """Store card credential and push to device via config-id=10.

    Works for standard RFID card devices and QR devices (QR encodes the card number).
    If a second card number is provided it is stored as card-2.
    """
    tenant = _get_tenant_or_404(tenant_id, db)
    device = _get_device_for_tenant_or_404(tenant, device_id, db)
    _sync_tenant_global_validity(tenant, valid_from, valid_till)

    _upsert_credential(tenant_id, db, "card", slot_index=1, raw_value=card1)
    if card2:
        _upsert_credential(tenant_id, db, "card", slot_index=2, raw_value=card2)

    correlation_id = _make_correlation_id(tenant_id, device_id)

    if device.communication_mode == "direct":
        client = _make_direct_client(device)
        matrix_user_id = resolve_matrix_user_id(db, device.device_id, tenant.tenant_id)
        result = client.create_user(
            user_id=matrix_user_id,
            name=tenant.full_name,
            active=is_access_active(tenant),
            validity_end_date=_effective_valid_till_date(valid_till, tenant),
            card1=card1,
            card2=card2,
        )
        _log_assignment(tenant_id, device_id, "update", db, performed_by=performed_by)
        db.commit()
        return {
            "tenant_id": tenant_id,
            "device_id": device_id,
            "mode": "direct",
            "status": "success" if result["success"] else "failed",
            "message": "Card credential set on device." if result["success"] else f"Device returned: {result['response']}",
        }

    push_create_user(
        db, device_id, tenant, correlation_id,
        active=is_access_active(tenant),
        valid_till=valid_till,
        card1=card1, card2=card2,
    )
    _log_assignment(tenant_id, device_id, "update", db, performed_by=performed_by)
    db.commit()
    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "mode": "push",
        "status": "queued",
        "correlation_id": correlation_id,
        "message": "Card credential queued for device update. Poll GET /api/push/operations/{correlation_id} for status.",
    }


def set_pin_credential(
    tenant_id: int,
    device_id: int,
    pin: str,
    db: Session,
    performed_by=None,
    valid_from: datetime | None = None,
    valid_till: datetime | None = None,
) -> dict:
    """Store PIN credential and push to device via config-id=10."""
    tenant = _get_tenant_or_404(tenant_id, db)
    device = _get_device_for_tenant_or_404(tenant, device_id, db)
    _sync_tenant_global_validity(tenant, valid_from, valid_till)

    _upsert_credential(tenant_id, db, "pin", slot_index=1, raw_value=pin)

    correlation_id = _make_correlation_id(tenant_id, device_id)

    if device.communication_mode == "direct":
        client = _make_direct_client(device)
        matrix_user_id = resolve_matrix_user_id(db, device.device_id, tenant.tenant_id)
        result = client.create_user(
            user_id=matrix_user_id,
            name=tenant.full_name,
            active=is_access_active(tenant),
            validity_end_date=_effective_valid_till_date(valid_till, tenant),
            user_pin=pin,
        )
        _log_assignment(tenant_id, device_id, "update", db, performed_by=performed_by)
        db.commit()
        return {
            "tenant_id": tenant_id,
            "device_id": device_id,
            "mode": "direct",
            "status": "success" if result["success"] else "failed",
            "message": "PIN set on device." if result["success"] else f"Device returned: {result['response']}",
        }

    push_create_user(
        db, device_id, tenant, correlation_id,
        active=is_access_active(tenant),
        valid_till=valid_till,
        user_pin=pin,
    )
    _log_assignment(tenant_id, device_id, "update", db, performed_by=performed_by)
    db.commit()
    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "mode": "push",
        "status": "queued",
        "correlation_id": correlation_id,
        "message": "PIN queued for device update. Poll GET /api/push/operations/{correlation_id} for status.",
    }


def register_and_capture_face(
    tenant_id: int,
    device_id: int,
    db: Session,
    face_no: int = 1,
    performed_by=None,
    valid_from: datetime | None = None,
    valid_till: datetime | None = None,
) -> dict:
    """Create user on device and trigger face enrollment mode.

    Push mode: queues config-id=10 (create user) + cmd-id=1/cred-type=6 (ENROLL face).
    Direct mode: calls device API to create user + trigger face scan mode.

    After the user looks at the device, call the extract-face endpoint (direct mode)
    or poll the correlation_id (push mode).
    """
    tenant = _get_tenant_or_404(tenant_id, db)
    device = _get_device_for_tenant_or_404(tenant, device_id, db)
    _sync_tenant_global_validity(tenant, valid_from, valid_till)

    if len(tenant.full_name) > 15:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Name '{tenant.full_name}' exceeds 15-character device limit.",
        )

    if device.communication_mode == "direct":
        client = _make_direct_client(device)
        matrix_user_id = resolve_matrix_user_id(db, device.device_id, tenant.tenant_id)

        create_result = client.create_user(
            user_id=matrix_user_id,
            name=tenant.full_name,
            active=is_access_active(tenant),
            validity_end_date=_effective_valid_till_date(valid_till, tenant),
        )
        if not create_result["success"]:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Device rejected user creation: {create_result['response']}",
            )

        enroll_result = client.trigger_face_enrollment(matrix_user_id, face_no)
        _upsert_mapping(tenant_id, device_id, db, synced=True, valid_from=valid_from, valid_till=valid_till)
        _upsert_site_access_for_device(tenant_id, device, db, valid_from=valid_from, valid_till=valid_till)
        _log_assignment(tenant_id, device_id, "capture", db, performed_by=performed_by, synced=True)
        db.commit()

        return {
            "tenant_id": tenant_id,
            "device_id": device_id,
            "mode": "direct",
            "status": "enrollment_triggered" if enroll_result["success"] else "user_created",
            "message": (
                "User created and face enrollment mode triggered. Have the user look at the device camera."
                if enroll_result["success"]
                else "User created but failed to trigger face enrollment mode. Try again."
            ),
        }

    correlation_id = _make_correlation_id(tenant_id, device_id)
    push_create_user(
        db, device_id, tenant, correlation_id,
        active=is_access_active(tenant),
        valid_till=valid_till,
        enroll_face_no=face_no,
    )
    _upsert_mapping(tenant_id, device_id, db, synced=False, valid_from=valid_from, valid_till=valid_till)
    _upsert_site_access_for_device(tenant_id, device, db, valid_from=valid_from, valid_till=valid_till)
    _log_assignment(tenant_id, device_id, "capture", db, performed_by=performed_by)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "mode": "push",
        "status": "queued",
        "correlation_id": correlation_id,
        "message": (
            "User creation queued. Device will prompt for face scan on next poll. "
            "Poll GET /api/push/operations/{correlation_id} for status."
        ),
    }


def register_and_capture_card(
    tenant_id: int,
    device_id: int,
    db: Session,
    card_no: int = 1,
    performed_by=None,
    valid_from=None,
    valid_till=None,
) -> dict:
    """Create user on device and trigger card enrollment mode.

    Push mode: queues config-id=10 (create user) then cmd-id=1/cred-type=1 (ENROLL card).
    The device beeps and waits for the user to tap their card. The card number is read
    by the device and sent back in updatecmd (card-1 field), then saved to the DB.

    Returns a correlation_id to poll for completion.
    """
    tenant = _get_tenant_or_404(tenant_id, db)
    device = _get_device_for_tenant_or_404(tenant, device_id, db)
    _sync_tenant_global_validity(tenant, valid_from, valid_till)

    if device.communication_mode != "push":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Card capture via device scan is only supported for push-mode devices. "
                   "Use set-card to assign a card number manually.",
        )

    correlation_id = _make_correlation_id(tenant_id, device_id)
    push_create_user(
        db, device_id, tenant, correlation_id,
        active=is_access_active(tenant),
        valid_till=valid_till,
        enroll_card_no=card_no,
    )
    _upsert_mapping(tenant_id, device_id, db, synced=False, valid_from=valid_from, valid_till=valid_till)
    _upsert_site_access_for_device(tenant_id, device, db, valid_from=valid_from, valid_till=valid_till)
    _log_assignment(tenant_id, device_id, "enroll", db, performed_by=performed_by)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "mode": "push",
        "status": "queued",
        "correlation_id": correlation_id,
        "message": (
            "User creation queued. Device will beep and wait for card tap on next poll. "
            "Poll GET /api/push/operations/{correlation_id} for status."
        ),
    }


def extract_face_from_device(
    tenant_id: int,
    device_id: int,
    db: Session,
    face_no: int = 1,
    performed_by=None,
) -> dict:
    """Download an existing face template from a device and store it in DB.

    Use this after the user has already scanned their face via capture-face.

    Push mode: queues cmd-id=3 / cred-type=4 (GET_CREDENTIAL for face).
    Direct mode: calls device API synchronously and saves the template file.
    """
    tenant = _get_tenant_or_404(tenant_id, db)
    device = _get_device_for_tenant_or_404(tenant, device_id, db)

    if device.communication_mode == "direct":
        client = _make_direct_client(device)
        matrix_user_id = resolve_matrix_user_id(db, device.device_id, tenant.tenant_id)

        content, file_path = client.extract_face_template(matrix_user_id, face_no)
        if not content or not file_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No face template found on device. Has the user scanned their face yet?",
            )

        _upsert_credential(tenant_id, db, "face", slot_index=face_no, file_path=file_path)
        _upsert_mapping(tenant_id, device_id, db, synced=True)
        _log_assignment(tenant_id, device_id, "extract_face", db, performed_by=performed_by, synced=True)
        db.commit()

        return {
            "tenant_id": tenant_id,
            "device_id": device_id,
            "mode": "direct",
            "status": "success",
            "face_no": face_no,
            "message": "Face template extracted from device and stored.",
        }

    correlation_id = _make_correlation_id(tenant_id, device_id)
    push_get_face(db, device_id, tenant_id, face_no, correlation_id)
    _upsert_mapping(tenant_id, device_id, db, synced=False)
    _log_assignment(tenant_id, device_id, "extract_face", db, performed_by=performed_by)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "mode": "push",
        "status": "queued",
        "correlation_id": correlation_id,
        "message": "GET_CREDENTIAL (face) queued. Poll GET /api/push/operations/{correlation_id} for status.",
    }


def enroll_new_tenant(
    payload,  # TenantEnrollRequest — imported at call site to avoid circular import
    company_id: UUID,
    db: Session,
    performed_by=None,
) -> dict:
    """Atomic single-step tenant creation + fingerprint capture on a device.

    Creates the tenant row in DB, queues user creation + fingerprint enrollment.
    Rolls back the tenant row if the device lookup fails.

    Queues:
      1. config-id=10  → create user on device
      2. cmd-id=1      → ENROLL_CREDENTIAL (device prompts for finger scan)
      3. Callback auto-queues GET_CREDENTIAL after scan
    """
    device = _get_device_or_404(payload.device_id, db)
    if device.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device does not belong to target company",
        )

    if len(payload.full_name) > 15:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Name '{payload.full_name}' exceeds 15-character device limit.",
        )

    ensure_company_user_quota(company_id, db)

    tenant = Tenant(
        company_id=company_id,
        group_id=validate_group_selection(company_id, getattr(payload, "group_id", None), db).group_id,
        external_id=payload.external_id,
        full_name=payload.full_name,
        email=payload.email,
        phone=getattr(payload, "phone", None),
        tenant_type=payload.tenant_type,
        is_active=True,
        global_access_from=payload.global_access_from,
        global_access_till=payload.global_access_till,
    )
    db.add(tenant)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A tenant with the same external_id already exists for this company.",
        )

    correlation_id = _make_correlation_id(tenant.tenant_id, device.device_id)
    push_create_user(
        db, device.device_id, tenant, correlation_id,
        active=True,
        enroll_finger_index=payload.finger_index,
    )
    _upsert_mapping(tenant.tenant_id, device.device_id, db, synced=False)
    _log_assignment(tenant.tenant_id, device.device_id, "enroll", db, performed_by=performed_by)

    if hasattr(payload, "site_id") and payload.site_id:
        db.add(TenantSiteAccess(
            tenant_id=tenant.tenant_id,
            site_id=payload.site_id,
            valid_from=payload.global_access_from,
            valid_till=payload.global_access_till,
        ))

    db.commit()
    db.refresh(tenant)

    return {
        "tenant_id": tenant.tenant_id,
        "full_name": tenant.full_name,
        "device_id": device.device_id,
        "status": "queued",
        "correlation_id": correlation_id,
        "message": (
            "Tenant created. User creation + fingerprint enrollment queued. "
            "Device will prompt for finger scan on next poll. "
            "Poll GET /api/push/operations/{correlation_id} for status."
        ),
    }
