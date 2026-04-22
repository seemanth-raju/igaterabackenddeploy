from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.services.access.schema import (
    BulkAccessRequest,
    TenantDeviceAccessCreate,
    TenantDeviceAccessRead,
    TenantDeviceAccessUpdate,
    TenantSiteAccessCreate,
    TenantSiteAccessRead,
    TenantSiteAccessUpdate,
)
from app.api.services.access.service import (
    get_device_access,
    get_site_access,
    grant_bulk_access,
    grant_device_access,
    grant_site_access,
    list_device_accesses,
    list_site_accesses,
    revoke_device_access,
    revoke_site_access,
    update_device_access,
    update_site_access,
)
from database.models import AppUser

router = APIRouter(prefix="/access", tags=["access"])


def _to_site_access_read(site_access) -> TenantSiteAccessRead:
    return TenantSiteAccessRead(
        site_access_id=site_access.site_access_id,
        tenant_id=site_access.tenant_id,
        site_id=site_access.site_id,
        valid_from=site_access.valid_from,
        valid_till=site_access.valid_till,
        auto_assign_all_devices=site_access.auto_assign_all_devices,
    )


def _to_device_access_read(device_access) -> TenantDeviceAccessRead:
    return TenantDeviceAccessRead(
        device_access_id=device_access.device_access_id,
        tenant_id=device_access.tenant_id,
        device_id=device_access.device_id,
        site_access_id=device_access.site_access_id,
        valid_from=device_access.valid_from,
        valid_till=device_access.valid_till,
    )


# ==================== SITE ACCESS ====================


@router.post("/site", response_model=TenantSiteAccessRead, status_code=status.HTTP_201_CREATED)
def grant_site_access_route(
    payload: TenantSiteAccessCreate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> TenantSiteAccessRead:
    """Grant a tenant access to a site. Set auto_assign_all_devices=true to also grant device access."""
    site_access = grant_site_access(payload, current_user, db)
    return _to_site_access_read(site_access)


@router.get("/site", response_model=list[TenantSiteAccessRead])
def list_site_accesses_route(
    tenant_id: int | None = Query(default=None),
    site_id: int | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[TenantSiteAccessRead]:
    site_accesses = list_site_accesses(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        site_id=site_id,
        skip=skip,
        limit=limit,
    )
    return [_to_site_access_read(sa) for sa in site_accesses]


@router.get("/site/{site_access_id}", response_model=TenantSiteAccessRead)
def get_site_access_route(
    site_access_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> TenantSiteAccessRead:
    site_access = get_site_access(site_access_id, current_user, db)
    return _to_site_access_read(site_access)


@router.patch("/site/{site_access_id}", response_model=TenantSiteAccessRead)
def update_site_access_route(
    site_access_id: int,
    payload: TenantSiteAccessUpdate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> TenantSiteAccessRead:
    site_access = update_site_access(site_access_id, payload, current_user, db)
    return _to_site_access_read(site_access)


@router.delete("/site/{site_access_id}")
def revoke_site_access_route(
    site_access_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, str]:
    revoke_site_access(site_access_id, current_user, db)
    return {"message": "Site access revoked successfully"}


# ==================== DEVICE ACCESS ====================


@router.post("/device", response_model=TenantDeviceAccessRead, status_code=status.HTTP_201_CREATED)
def grant_device_access_route(
    payload: TenantDeviceAccessCreate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> TenantDeviceAccessRead:
    """Grant a tenant access to a specific device."""
    device_access = grant_device_access(payload, current_user, db)
    return _to_device_access_read(device_access)


@router.get("/device", response_model=list[TenantDeviceAccessRead])
def list_device_accesses_route(
    tenant_id: int | None = Query(default=None),
    device_id: int | None = Query(default=None),
    site_access_id: int | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[TenantDeviceAccessRead]:
    device_accesses = list_device_accesses(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        device_id=device_id,
        site_access_id=site_access_id,
        skip=skip,
        limit=limit,
    )
    return [_to_device_access_read(da) for da in device_accesses]


@router.get("/device/{device_access_id}", response_model=TenantDeviceAccessRead)
def get_device_access_route(
    device_access_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> TenantDeviceAccessRead:
    device_access = get_device_access(device_access_id, current_user, db)
    return _to_device_access_read(device_access)


@router.patch("/device/{device_access_id}", response_model=TenantDeviceAccessRead)
def update_device_access_route(
    device_access_id: int,
    payload: TenantDeviceAccessUpdate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> TenantDeviceAccessRead:
    device_access = update_device_access(device_access_id, payload, current_user, db)
    return _to_device_access_read(device_access)


@router.delete("/device/{device_access_id}")
def revoke_device_access_route(
    device_access_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, str]:
    revoke_device_access(device_access_id, current_user, db)
    return {"message": "Device access revoked successfully"}


# ==================== BULK ====================


@router.post("/bulk", status_code=status.HTTP_201_CREATED)
def grant_bulk_access_route(
    payload: BulkAccessRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    """Grant access to multiple sites and/or devices at once."""
    return grant_bulk_access(payload, current_user, db)
