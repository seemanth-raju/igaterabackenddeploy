from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.services.device_mapping.schema import SyncStatusUpdate
from database.models import AppUser, Device, DeviceUserMapping, Tenant, UserRole


_MAPPING_MANAGER_ROLES = {UserRole.super_admin.value, UserRole.company_admin.value}


def _ensure_mapping_manager(current_user: AppUser) -> None:
    if current_user.role not in _MAPPING_MANAGER_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _ensure_mapping_scope(mapping: DeviceUserMapping, current_user: AppUser, db: Session) -> None:
    _ensure_mapping_manager(current_user)
    device = db.query(Device).filter(Device.device_id == mapping.device_id).first()
    tenant = db.query(Tenant).filter(Tenant.tenant_id == mapping.tenant_id).first()
    if not device or not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Related device or tenant not found")
    if tenant.company_id != device.company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mapping crosses company boundaries")
    if current_user.role != UserRole.super_admin.value and device.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this company")


def list_mappings(
    db: Session,
    current_user: AppUser,
    tenant_id: int | None = None,
    device_id: int | None = None,
    is_synced: bool | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[DeviceUserMapping]:
    """List device user mappings with filters."""
    query = db.query(DeviceUserMapping)
    _ensure_mapping_manager(current_user)

    if current_user.role != UserRole.super_admin.value:
        query = query.join(Device, Device.device_id == DeviceUserMapping.device_id).filter(
            Device.company_id == current_user.company_id
        )

    if tenant_id is not None:
        query = query.filter(DeviceUserMapping.tenant_id == tenant_id)

    if device_id is not None:
        query = query.filter(DeviceUserMapping.device_id == device_id)

    if is_synced is not None:
        query = query.filter(DeviceUserMapping.is_synced == is_synced)

    return query.order_by(DeviceUserMapping.created_at.desc()).offset(skip).limit(limit).all()


def get_mapping(mapping_id: int, db: Session, current_user: AppUser) -> DeviceUserMapping:
    """Get a specific device user mapping."""
    mapping = db.query(DeviceUserMapping).filter(DeviceUserMapping.mapping_id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device user mapping not found")
    _ensure_mapping_scope(mapping, current_user, db)
    return mapping


def get_mapping_by_tenant_device(tenant_id: int, device_id: int, db: Session) -> DeviceUserMapping | None:
    """Get mapping by tenant and device."""
    return (
        db.query(DeviceUserMapping)
        .filter(DeviceUserMapping.tenant_id == tenant_id, DeviceUserMapping.device_id == device_id)
        .first()
    )


def update_sync_status(mapping_id: int, payload: SyncStatusUpdate, db: Session, current_user: AppUser) -> DeviceUserMapping:
    """Update sync status of a mapping."""
    mapping = get_mapping(mapping_id, db, current_user)

    mapping.is_synced = payload.is_synced
    mapping.last_sync_attempt_at = func.current_timestamp()

    if payload.is_synced:
        mapping.last_sync_at = func.current_timestamp()
        mapping.sync_error = None
    else:
        mapping.sync_error = payload.sync_error

    if payload.device_response is not None:
        mapping.device_response = payload.device_response

    mapping.sync_attempt_count += 1

    db.commit()
    db.refresh(mapping)
    return mapping


def delete_mapping(mapping_id: int, db: Session, current_user: AppUser) -> None:
    """Delete a device user mapping."""
    mapping = get_mapping(mapping_id, db, current_user)
    db.delete(mapping)
    db.commit()


def get_unsynced_mappings(db: Session, current_user: AppUser, limit: int = 50) -> list[DeviceUserMapping]:
    """Get all unsynced mappings for background sync jobs."""
    _ensure_mapping_manager(current_user)
    query = db.query(DeviceUserMapping).filter(DeviceUserMapping.is_synced == False)
    if current_user.role != UserRole.super_admin.value:
        query = query.join(Device, Device.device_id == DeviceUserMapping.device_id).filter(
            Device.company_id == current_user.company_id
        )
    return query.limit(limit).all()
