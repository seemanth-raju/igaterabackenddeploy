from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_current_user_optional, get_db
from app.api.services.devices.schema import (
    DeviceCreate,
    DeviceImportRequest,
    DeviceImportResponse,
    DeviceRead,
    DeviceUpdate,
)
from app.api.services.devices.service import (
    create_device,
    delete_device,
    get_device,
    import_enrollment_device,
    import_from_upload,
    list_devices,
    resolve_company_id,
    resolve_upload_import_company_id,
    update_device,
)
from app.api.services.groups.schema import TenantGroupRead
from app.core.config import settings
from app.services.matrix import MatrixDeviceClient
from database.models import AppUser, UserRole
from sqlalchemy import func

router = APIRouter(prefix="/devices", tags=["devices"])


def _to_device_read(device) -> DeviceRead:
    return DeviceRead(
        device_id=device.device_id,
        company_id=str(device.company_id) if device.company_id else None,
        site_id=device.site_id,
        device_serial_number=device.device_serial_number,
        vendor=device.vendor,
        model_name=device.model_name,
        ip_address=device.ip_address,
        mac_address=device.mac_address,
        api_username=device.api_username,
        api_port=device.api_port,
        use_https=device.use_https,
        is_active=device.is_active,
        communication_mode=device.communication_mode,
        status=device.status,
        config=device.config,
        created_at=device.created_at,
    )


def _to_group_read(group) -> TenantGroupRead:
    return TenantGroupRead(
        group_id=group.group_id,
        name=group.name,
        code=group.code,
        short_name=group.short_name,
    )


def _to_import_response(result: dict) -> DeviceImportResponse:
    return DeviceImportResponse(
        device=_to_device_read(result["device"]),
        device_created=result["device_created"],
        group=_to_group_read(result["group"]),
        reported_user_count=result["reported_user_count"],
        imported_user_count=result["imported_user_count"],
        created_tenants=result["created_tenants"],
        updated_tenants=result["updated_tenants"],
        created_mappings=result["created_mappings"],
        updated_mappings=result["updated_mappings"],
        created_device_accesses=result["created_device_accesses"],
        created_site_accesses=result["created_site_accesses"],
        imported_fingerprint_count=result["imported_fingerprint_count"],
        users_with_fingerprints=result["users_with_fingerprints"],
        warnings=result["warnings"],
        users=result["users"],
    )


def _check_device_access(device, current_user: AppUser) -> None:
    """Raise 403 if the user does not own this device."""
    if current_user.role != UserRole.super_admin.value and device.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this device")


def _require_device_manager(current_user: AppUser) -> None:
    if current_user.role not in (UserRole.super_admin.value, UserRole.company_admin.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _heartbeat_online(last_heartbeat) -> bool:
    if last_heartbeat is None:
        return False
    heartbeat = last_heartbeat
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - heartbeat).total_seconds()
    return age_seconds <= settings.push_api_device_offline_seconds


@router.post("", response_model=DeviceRead)
def create_device_route(
    payload: DeviceCreate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> DeviceRead:
    _require_device_manager(current_user)
    device = create_device(payload, resolve_company_id(payload.company_id, current_user), db)
    return _to_device_read(device)


@router.post("/import-enrollment", response_model=DeviceImportResponse, status_code=status.HTTP_201_CREATED)
def import_enrollment_device_route(
    payload: DeviceImportRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> DeviceImportResponse:
    result = import_enrollment_device(payload, current_user, db)
    return _to_import_response(result)


@router.post("/upload-import", response_model=DeviceImportResponse, status_code=status.HTTP_201_CREATED)
async def upload_import_device_route(
    group_id: int = Form(..., description="Group ID to place all imported tenants into"),
    site_id: int = Form(..., description="Site the device belongs to — all tenants get site access"),
    company_id: UUID | None = Form(default=None, description="Super-admin only — target company UUID"),
    device_ip: str | None = Form(default=None),
    device_mac: str | None = Form(default=None, description="Device MAC address (used for deduplication)"),
    device_serial: str | None = Form(default=None),
    device_vendor: str | None = Form(default=None),
    device_model: str | None = Form(default=None),
    users_excel: UploadFile = File(..., description="Excel (.xlsx) with columns: user_id, full_name, ref_user_id, is_active, valid_till"),
    fingerprints: list[UploadFile] = File(default=[], description="Fingerprint template files named {user_id}_finger_{index}.dat"),
    db: Session = Depends(get_db),
    current_user: AppUser | None = Depends(get_current_user_optional),
) -> DeviceImportResponse:
    """Upload-based migration — cloud-safe alternative to /import-enrollment.

    Use this when your backend is in the cloud and cannot reach the device directly.
    The Streamlit extractor app runs on the customer's local network, extracts users
    and fingerprint templates from the device, then uploads them here.

    **Excel format** (first row = headers):
    | user_id | full_name | ref_user_id | is_active | valid_till | user_index |

    **Fingerprint files:** binary `.dat` files named `{user_id}_finger_{finger_index}.dat`
    (e.g. `42_finger_1.dat`). Pass multiple files under the `fingerprints` field.
    """
    comp_id = resolve_upload_import_company_id(company_id, current_user, db)

    excel_bytes = await users_excel.read()
    fp_files = [
        (fp.filename or f"unknown_{i}.dat", await fp.read())
        for i, fp in enumerate(fingerprints)
    ]

    result = import_from_upload(
        group_id=group_id,
        site_id=site_id,
        company_id=comp_id,
        excel_bytes=excel_bytes,
        fingerprint_files=fp_files,
        device_ip=device_ip,
        device_mac=device_mac,
        device_serial=device_serial,
        device_vendor=device_vendor,
        device_model=device_model,
        db=db,
    )
    return _to_import_response(result)


@router.get("", response_model=list[DeviceRead])
def list_devices_route(
    company_id: UUID | None = Query(default=None),
    site_id: int | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=1000),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[DeviceRead]:
    if current_user.role != UserRole.super_admin.value:
        company_id = current_user.company_id

    devices = list_devices(db, company_id=company_id, site_id=site_id, skip=skip, limit=limit, search=search)
    return [_to_device_read(device) for device in devices]


@router.get("/{device_id}", response_model=DeviceRead)
def get_device_route(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> DeviceRead:
    device = get_device(device_id, db)
    _check_device_access(device, current_user)
    return _to_device_read(device)


@router.patch("/{device_id}", response_model=DeviceRead)
def update_device_route(
    device_id: int,
    payload: DeviceUpdate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> DeviceRead:
    _require_device_manager(current_user)
    device = get_device(device_id, db)
    _check_device_access(device, current_user)
    device = update_device(device_id, payload, db)
    return _to_device_read(device)


@router.post("/{device_id}/ping")
def ping_device_route(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    """Check device health.

    Direct devices are pinged over the network. Push devices cannot be pinged
    from the backend, so their status is derived from the last Push API heartbeat.
    """
    _require_device_manager(current_user)
    device = get_device(device_id, db)
    _check_device_access(device, current_user)

    if device.communication_mode == "push":
        is_online = _heartbeat_online(device.last_heartbeat) and bool(device.is_active)
        device.status = "online" if is_online else "offline"
        db.commit()
        return {
            "device_id": device_id,
            "communication_mode": device.communication_mode,
            "online": is_online,
            "status": device.status,
            "last_heartbeat": device.last_heartbeat,
            "offline_after_seconds": settings.push_api_device_offline_seconds,
            "checked_via": "push_heartbeat",
        }

    if not device.ip_address:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Device has no IP address configured")

    try:
        client = MatrixDeviceClient(
            device_ip=device.ip_address,
            username=device.api_username or "admin",
            encrypted_password=device.api_password_encrypted or "",
            use_https=device.use_https,
            api_port=device.api_port,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    is_online = client.ping()

    device.status = "online" if is_online else "offline"
    if is_online:
        device.last_heartbeat = db.query(func.current_timestamp()).scalar()
    db.commit()

    return {
        "device_id": device_id,
        "communication_mode": device.communication_mode,
        "ip_address": device.ip_address,
        "online": is_online,
        "status": device.status,
        "last_heartbeat": device.last_heartbeat,
        "checked_via": "direct_ping",
    }


@router.post("/{device_id}/push-extract")
def push_extract_device_route(
    device_id: int,
    finger_index: int = 1,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    """**Push-mode migration.** Queue GET_CREDENTIAL for every tenant already mapped to this device.

    Use this when a push-mode device has users enrolled (e.g. from a previous system or
    manually on the device) and you want to pull all their biometric templates into the DB.

    - Requires all tenants to already have a `DeviceUserMapping` for this device.
    - For brand-new direct-mode devices with unknown users, use `POST /devices/import-enrollment` instead.

    Returns immediately with one `correlation_id` per tenant.
    Poll each via `GET /api/push/operations/{correlation_id}` to track extraction status.
    """
    import uuid as _uuid
    from app.api.services.push.commands import push_get_credential
    from database.models import DeviceUserMapping

    _require_device_manager(current_user)
    device = get_device(device_id, db)
    _check_device_access(device, current_user)

    if device.communication_mode != "push":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This endpoint is for push-mode devices only. "
                "Use POST /devices/import-enrollment for direct-mode devices."
            ),
        )

    mappings = (
        db.query(DeviceUserMapping)
        .filter(DeviceUserMapping.device_id == device_id)
        .all()
    )
    if not mappings:
        return {
            "device_id": device_id,
            "queued": 0,
            "results": [],
            "message": "No tenants are mapped to this device. Enroll tenants first via POST /tenants/{id}/capture-fingerprint.",
        }

    results = []
    for mapping in mappings:
        correlation_id = f"extract-{mapping.tenant_id}-{device_id}-{_uuid.uuid4().hex[:8]}"
        push_get_credential(db, device_id, mapping.tenant_id, finger_index, correlation_id)
        results.append({
            "tenant_id": mapping.tenant_id,
            "matrix_user_id": mapping.matrix_user_id,
            "correlation_id": correlation_id,
        })

    db.commit()

    return {
        "device_id": device_id,
        "queued": len(results),
        "finger_index": finger_index,
        "results": results,
        "message": (
            f"GET_CREDENTIAL queued for {len(results)} tenant(s). "
            "Device will extract templates on next poll (~5s). "
            "Poll each correlation_id via GET /api/push/operations/{correlation_id} for status."
        ),
    }


@router.delete("/{device_id}")
def delete_device_route(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, str]:
    _require_device_manager(current_user)
    device = get_device(device_id, db)
    _check_device_access(device, current_user)
    delete_device(device_id, db)
    return {"message": "Device deleted"}
