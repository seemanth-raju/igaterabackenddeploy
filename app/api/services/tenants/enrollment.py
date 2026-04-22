"""Tenant device enrollment — push-only mode.

All operations queue commands/configs into DeviceCommand / DeviceConfig tables.
The device picks them up on its next poll (/push/poll → /push/getcmd → /push/updatecmd).

Enrollment flow:
  1. POST /tenants/{id}/capture-fingerprint
       → queues config-id=10 (create user) + cmd-id=1 (ENROLL_CREDENTIAL)
       → device prompts user for finger scan
       → callback auto-queues GET_CREDENTIAL to fetch & store template in DB

  2. POST /tenants/{id}/enroll  (after fingerprint is stored)
       → queues config-id=10 (create user) + cmd-id=4 (SET_CREDENTIAL)
       → pushes stored fingerprint template to target device(s)

  3. DELETE /tenants/{id}/unenroll
       → queues cmd-id=2 (DELETE_CREDENTIAL) + cmd-id=7 (DELETE_USER)

All responses return immediately with a correlation_id.
Poll GET /api/push/operations/{correlation_id} to track status.
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
    push_delete_credential,
    push_delete_user,
    push_get_credential,
    push_set_credential,
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
# Public API — all push-only, all return correlation_id immediately
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
    _get_device_for_tenant_or_404(tenant, device_id, db)
    _sync_tenant_global_validity(tenant, valid_from, valid_till)

    if len(tenant.full_name) > 15:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Name '{tenant.full_name}' exceeds 15-character device limit.",
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
    _log_assignment(tenant_id, device_id, "capture", db, performed_by=performed_by)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
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
    _get_device_for_tenant_or_404(tenant, device_id, db)
    _sync_tenant_global_validity(tenant, valid_from, valid_till)

    correlation_id = _make_correlation_id(tenant_id, device_id)
    push_get_credential(db, device_id, tenant_id, finger_index, correlation_id)
    _upsert_mapping(tenant_id, device_id, db, synced=False, valid_from=valid_from, valid_till=valid_till)
    _log_assignment(tenant_id, device_id, "extract_fingerprint", db, performed_by=performed_by)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
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
    _get_device_for_tenant_or_404(tenant, device_id, db)
    if update_tenant_validity:
        _sync_tenant_global_validity(tenant, valid_from, valid_till)

    if len(tenant.full_name) > 15:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Name '{tenant.full_name}' exceeds 15-character device limit.",
        )

    correlation_id = _make_correlation_id(tenant_id, device_id)

    push_create_user(db, device_id, tenant, correlation_id, active=is_access_active(tenant), valid_till=valid_till)

    credential = _find_fingerprint_credential(tenant_id, db, finger_index)
    fp_queued = False
    if credential and credential.file_path:
        push_set_credential(db, device_id, tenant_id, finger_index, credential.file_path, correlation_id)
        fp_queued = True

    _upsert_mapping(tenant_id, device_id, db, synced=False, valid_from=valid_from, valid_till=valid_till)
    _log_assignment(tenant_id, device_id, "enroll", db, performed_by=performed_by)
    db.commit()

    msg = (
        "User creation + fingerprint push queued. Poll GET /api/push/operations/{correlation_id} for status."
        if fp_queued
        else (
            "User creation queued but NO fingerprint was pushed — none stored in DB. "
            "Capture a fingerprint first via POST /tenants/{tenant_id}/capture-fingerprint."
        )
    )
    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "status": "queued",
        "correlation_id": correlation_id,
        "fingerprint_queued": fp_queued,
        "message": msg,
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
    _get_device_for_tenant_or_404(tenant, device_id, db)

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

    correlation_id = _make_correlation_id(tenant_id, device_id)

    push_create_user(db, device_id, tenant, correlation_id,
                     active=is_access_active(tenant), valid_till=effective_valid_till)

    credential = _find_fingerprint_credential(tenant_id, db)
    fp_queued = False
    if credential and credential.file_path:
        push_set_credential(db, device_id, tenant_id, 1, credential.file_path, correlation_id)
        fp_queued = True

    _upsert_mapping(tenant_id, device_id, db, synced=False,
                    valid_from=effective_valid_from, valid_till=effective_valid_till)
    _log_assignment(tenant_id, device_id, "update", db, performed_by=performed_by)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
        "status": "queued",
        "correlation_id": correlation_id,
        "fingerprint_queued": fp_queued,
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
    _get_device_for_tenant_or_404(tenant, device_id, db)

    correlation_id = _make_correlation_id(tenant_id, device_id)
    push_delete_credential(db, device_id, tenant_id, cred_type="1", correlation_id=correlation_id)
    push_delete_user(db, device_id, tenant_id, correlation_id)
    _log_assignment(tenant_id, device_id, "unenroll", db, performed_by=performed_by)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "device_id": device_id,
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
