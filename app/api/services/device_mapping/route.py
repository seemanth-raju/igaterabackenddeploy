from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.services.device_mapping.schema import DeviceUserMappingRead, SyncStatusUpdate
from app.api.services.device_mapping.service import (
    delete_mapping,
    get_mapping,
    get_unsynced_mappings,
    list_mappings,
    update_sync_status,
)
from database.models import AppUser

router = APIRouter(prefix="/device-mappings", tags=["device-mappings"])


def _to_mapping_read(mapping) -> DeviceUserMappingRead:
    return DeviceUserMappingRead(
        mapping_id=mapping.mapping_id,
        tenant_id=mapping.tenant_id,
        device_id=mapping.device_id,
        matrix_user_id=mapping.matrix_user_id,
        valid_from=mapping.valid_from,
        valid_till=mapping.valid_till,
        is_synced=mapping.is_synced,
        last_sync_at=mapping.last_sync_at,
        last_sync_attempt_at=mapping.last_sync_attempt_at,
        sync_attempt_count=mapping.sync_attempt_count,
        sync_error=mapping.sync_error,
        device_response=mapping.device_response,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


@router.get("", response_model=list[DeviceUserMappingRead])
def list_mappings_route(
    tenant_id: int | None = Query(default=None),
    device_id: int | None = Query(default=None),
    is_synced: bool | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[DeviceUserMappingRead]:
    """List all device user mappings with optional filters."""
    mappings = list_mappings(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        device_id=device_id,
        is_synced=is_synced,
        skip=skip,
        limit=limit,
    )
    return [_to_mapping_read(m) for m in mappings]


@router.get("/unsynced", response_model=list[DeviceUserMappingRead])
def get_unsynced_mappings_route(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[DeviceUserMappingRead]:
    """Get all unsynced mappings (for background sync jobs)."""
    mappings = get_unsynced_mappings(db, current_user=current_user, limit=limit)
    return [_to_mapping_read(m) for m in mappings]


@router.get("/{mapping_id}", response_model=DeviceUserMappingRead)
def get_mapping_route(
    mapping_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> DeviceUserMappingRead:
    """Get a specific device user mapping."""
    mapping = get_mapping(mapping_id, db, current_user)
    return _to_mapping_read(mapping)


@router.patch("/{mapping_id}/sync-status", response_model=DeviceUserMappingRead)
def update_sync_status_route(
    mapping_id: int,
    payload: SyncStatusUpdate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> DeviceUserMappingRead:
    """Update sync status of a mapping."""
    mapping = update_sync_status(mapping_id, payload, db, current_user)
    return _to_mapping_read(mapping)


@router.delete("/{mapping_id}")
def delete_mapping_route(
    mapping_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a device user mapping."""
    delete_mapping(mapping_id, db, current_user)
    return {"message": "Device user mapping deleted successfully"}
