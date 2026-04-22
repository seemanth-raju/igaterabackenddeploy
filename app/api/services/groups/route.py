from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.services.groups.schema import GroupCreate, GroupEnrollDevicesRequest, GroupEnrollSiteRequest, GroupMemberRead, GroupRead, GroupUpdate, TenantGroupRead
from app.api.services.groups.service import (
    add_tenant_to_group,
    create_group,
    delete_group,
    enroll_group_to_devices,
    enroll_group_to_site,
    get_group,
    list_group_members,
    list_groups,
    remove_tenant_from_group,
    update_group,
)
from database.models import AppUser, UserRole

router = APIRouter(prefix="/groups", tags=["groups"])


def _to_group_read(group, member_count: int = 0) -> GroupRead:
    return GroupRead(
        group_id=group.group_id,
        company_id=group.company_id,
        name=group.name,
        code=group.code,
        email=group.email,
        short_name=group.short_name,
        description=group.description,
        is_default=group.is_default,
        is_active=group.is_active,
        created_at=group.created_at,
        updated_at=group.updated_at,
        member_count=member_count,
    )


@router.post("", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
def create_group_route(
    payload: GroupCreate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> GroupRead:
    group = create_group(payload, current_user, db)
    return _to_group_read(group)


@router.get("", response_model=list[GroupRead])
def list_groups_route(
    company_id: UUID | None = Query(default=None),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[GroupRead]:
    rows = list_groups(
        db,
        current_user,
        company_id=company_id,
        search=search,
    )
    return [_to_group_read(group, member_count) for group, member_count in rows]


@router.get("/{group_id}", response_model=GroupRead)
def get_group_route(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> GroupRead:
    group = get_group(group_id, db)
    if current_user.role != UserRole.super_admin.value and group.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this company")
    return _to_group_read(group, len(list_group_members(group_id, current_user, db)))


@router.patch("/{group_id}", response_model=GroupRead)
def update_group_route(
    group_id: int,
    payload: GroupUpdate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> GroupRead:
    group = update_group(group_id, payload, current_user, db)
    return _to_group_read(group, len(list_group_members(group_id, current_user, db)))


@router.delete("/{group_id}")
def delete_group_route(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, str]:
    delete_group(group_id, current_user, db)
    return {"message": "Group deleted"}


@router.get("/{group_id}/members", response_model=list[GroupMemberRead])
def list_group_members_route(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[GroupMemberRead]:
    return list_group_members(group_id, current_user, db)


@router.post("/{group_id}/members/{tenant_id}", response_model=TenantGroupRead | None)
def add_group_member_route(
    group_id: int,
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> TenantGroupRead | None:
    return add_tenant_to_group(group_id, tenant_id, current_user, db)


@router.post("/{group_id}/enroll-site")
def enroll_group_site_route(
    group_id: int,
    payload: GroupEnrollSiteRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    """Enroll every active tenant in a group to a site and all its devices.

    Internally calls `enroll-site` per tenant — creates TenantSiteAccess + TenantDeviceAccess
    records and queues push enrollment commands for every active device in the site.

    Returns a per-tenant summary. Each tenant entry contains:
    - `correlation_ids` — one per device, to track async push enrollment status.
    - Poll each via `GET /api/push/operations/{correlation_id}`.
    """
    return enroll_group_to_site(
        group_id=group_id,
        site_id=payload.site_id,
        finger_index=payload.finger_index,
        valid_from=payload.valid_from,
        valid_till=payload.valid_till,
        current_user=current_user,
        db=db,
    )


@router.post("/{group_id}/enroll-devices")
def enroll_group_devices_route(
    group_id: int,
    payload: GroupEnrollDevicesRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    """Enroll every active tenant in a group to a specific list of devices.

    Internally calls `enroll-bulk` per tenant — pushes each tenant's stored fingerprint
    template to every listed device. Tenants without a stored fingerprint still get created
    on the device but without a fingerprint credential.

    Returns a per-tenant summary. Each tenant entry contains:
    - `correlation_ids` — one per device, to track async push enrollment status.
    - Poll each via `GET /api/push/operations/{correlation_id}`.
    """
    return enroll_group_to_devices(
        group_id=group_id,
        device_ids=payload.device_ids,
        finger_index=payload.finger_index,
        valid_from=payload.valid_from,
        valid_till=payload.valid_till,
        current_user=current_user,
        db=db,
    )


@router.delete("/{group_id}/members/{tenant_id}", response_model=TenantGroupRead | None)
def remove_group_member_route(
    group_id: int,
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> TenantGroupRead | None:
    return remove_tenant_from_group(group_id, tenant_id, current_user, db)
