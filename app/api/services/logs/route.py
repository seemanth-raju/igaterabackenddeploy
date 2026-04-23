"""Access logs API endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.services.logs.service import (
    build_event_export_rows,
    delete_event,
    export_events,
    get_event,
    list_events,
    reset_cursor,
    sync_logs_from_device,
    update_event,
)
from database.models import AccessEvent, AppUser, Device, UserRole

router = APIRouter(prefix="/logs", tags=["logs"])


def _company_filter(current_user: AppUser) -> str | None:
    if current_user.role == "super_admin":
        return None
    return str(current_user.company_id)


def _require_log_admin(current_user: AppUser) -> None:
    if current_user.role not in (UserRole.super_admin.value, UserRole.company_admin.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _ensure_company_scope(current_user: AppUser, company_id) -> None:
    if current_user.role == UserRole.super_admin.value:
        return
    if company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this company")


def _get_scoped_device(device_id: int, current_user: AppUser, db: Session, *, require_admin: bool) -> Device:
    if require_admin:
        _require_log_admin(current_user)
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    _ensure_company_scope(current_user, device.company_id)
    return device


def _get_scoped_event(event_id: int, current_user: AppUser, db: Session, *, require_admin: bool) -> AccessEvent:
    if require_admin:
        _require_log_admin(current_user)
    event = get_event(event_id, db)
    company_id = event.company_id
    if company_id is None and event.device_id is not None:
        device = db.query(Device).filter(Device.device_id == event.device_id).first()
        if device:
            company_id = device.company_id
    if company_id is None and current_user.role != UserRole.super_admin.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this event")
    if company_id is not None:
        _ensure_company_scope(current_user, company_id)
    return event


@router.get("")
def get_logs(
    device_id: int | None = None,
    tenant_id: int | None = None,
    group_id: int | None = None,
    event_type: str | None = None,
    access_granted: bool | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=500),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[dict]:
    events = list_events(
        db,
        company_id=_company_filter(current_user),
        device_id=device_id,
        tenant_id=tenant_id,
        group_id=group_id,
        event_type=event_type,
        access_granted=access_granted,
        from_time=from_time,
        to_time=to_time,
        skip=skip,
        limit=limit,
    )
    return [_serialize(e) for e in events]


@router.get("/export")
def export_logs(
    device_id: int | None = None,
    tenant_id: int | None = None,
    group_id: int | None = None,
    event_type: str | None = None,
    access_granted: bool | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    export_format: str = Query(default="xlsx", alias="format", pattern="^(xlsx|pdf|docx)$"),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    events = list_events(
        db,
        company_id=_company_filter(current_user),
        device_id=device_id,
        tenant_id=tenant_id,
        group_id=group_id,
        event_type=event_type,
        access_granted=access_granted,
        from_time=from_time,
        to_time=to_time,
        skip=0,
        limit=10000,
    )
    export_rows = build_event_export_rows(db, events)
    file_bytes, media_type, filename = export_events(export_rows, export_format)
    return StreamingResponse(
        iter([file_bytes]),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/diagnostic/{device_id}")
def diagnostic(
    device_id: int,
    seq: int = 1,
    rollover: int = 0,
    count: int = Query(default=10, le=100),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    from app.services.matrix import MatrixDeviceClient
    device = _get_scoped_device(device_id, current_user, db, require_admin=True)
    if not device.ip_address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found or no IP")
    client = MatrixDeviceClient(
        device_ip=device.ip_address,
        username=device.api_username or "admin",
        encrypted_password=device.api_password_encrypted or "",
        use_https=device.use_https,
    )
    raw = client.fetch_events(rollover_count=rollover, seq_number=seq, no_of_events=count)
    return {"device_id": device_id, "seq": seq, "rollover": rollover, "events": raw}


@router.post("/sync/{device_id}")
def sync_device_logs(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    _get_scoped_device(device_id, current_user, db, require_admin=True)
    result = sync_logs_from_device(device_id, db)
    result.pop("_new_events", None)
    result.pop("_company_id", None)
    return result


@router.post("/reset-cursor/{device_id}")
def reset_log_cursor(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    _get_scoped_device(device_id, current_user, db, require_admin=True)
    return reset_cursor(device_id, db)


@router.get("/{event_id}")
def get_log(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    return _serialize(_get_scoped_event(event_id, current_user, db, require_admin=False))


@router.patch("/{event_id}")
def patch_log(
    event_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    _get_scoped_event(event_id, current_user, db, require_admin=True)
    return _serialize(update_event(event_id, body, db))


@router.delete("/{event_id}", status_code=204)
def remove_log(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> Response:
    _get_scoped_event(event_id, current_user, db, require_admin=True)
    delete_event(event_id, db)
    return Response(status_code=204)


def _serialize(e) -> dict:
    raw = e.raw_data or {}
    return {
        "event_id": e.event_id,
        "company_id": str(e.company_id) if e.company_id else None,
        "device_id": e.device_id,
        "tenant_id": e.tenant_id,
        "event_type": e.event_type,
        "event_time": e.event_time.isoformat() if e.event_time else None,
        "access_granted": e.access_granted,
        "auth_used": e.auth_used,
        "direction": e.direction,
        "cosec_event_id": e.cosec_event_id,
        "detail_1": raw.get("detail_1"),
        "notes": e.notes,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }
