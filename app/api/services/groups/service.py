from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.services.groups.schema import GroupMemberRead, GroupMemberSiteAccessRead, TenantGroupRead
from database.models import AppUser, Site, Tenant, TenantGroup, TenantSiteAccess, UserRole

_GROUP_MANAGER_ROLES = {UserRole.super_admin.value, UserRole.company_admin.value}


def resolve_company_id(requested: UUID | None, current_user: AppUser) -> UUID:
    if current_user.role == UserRole.super_admin.value and requested is not None:
        return requested
    return current_user.company_id


def _assert_company_scope(company_id: UUID, current_user: AppUser) -> None:
    if current_user.role != UserRole.super_admin.value and current_user.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this company")


def _ensure_group_manager(current_user: AppUser) -> None:
    if current_user.role not in _GROUP_MANAGER_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _get_tenant_or_404(tenant_id: int, db: Session) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


def get_group(group_id: int, db: Session) -> TenantGroup:
    group = db.query(TenantGroup).filter(TenantGroup.group_id == group_id).first()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


def _validate_group_uniqueness(
    *,
    db: Session,
    company_id: UUID,
    name: str,
    code: str,
    exclude_group_id: int | None = None,
) -> None:
    query = db.query(TenantGroup).filter(TenantGroup.company_id == company_id)
    if exclude_group_id is not None:
        query = query.filter(TenantGroup.group_id != exclude_group_id)

    duplicate = query.filter(
        or_(
            func.lower(TenantGroup.name) == name.lower(),
            func.lower(TenantGroup.code) == code.lower(),
        )
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Group name or code already exists for this company",
        )


def _enforce_single_default(company_id: UUID, keep_group_id: int, db: Session) -> None:
    (
        db.query(TenantGroup)
        .filter(TenantGroup.company_id == company_id, TenantGroup.group_id != keep_group_id)
        .update({"is_default": False}, synchronize_session=False)
    )


def ensure_default_group(company_id: UUID, db: Session) -> TenantGroup:
    groups = db.query(TenantGroup).filter(TenantGroup.company_id == company_id).all()

    for group in groups:
        if group.is_default:
            if not group.is_active:
                group.is_active = True
            return group

    for group in groups:
        name = (group.name or "").strip().lower()
        code = (group.code or "").strip().lower()
        if name == "default" or code == "default":
            group.is_default = True
            group.is_active = True
            db.flush()
            _enforce_single_default(company_id, group.group_id, db)
            return group

    group = TenantGroup(
        company_id=company_id,
        parent_group_id=None,
        name="Default",
        code="DEFAULT",
        short_name="Default",
        description="Auto-created default group",
        is_default=True,
        is_active=True,
    )
    db.add(group)
    db.flush()
    _enforce_single_default(company_id, group.group_id, db)
    return group


def create_group(payload, current_user: AppUser, db: Session) -> TenantGroup:
    _ensure_group_manager(current_user)
    company_id = resolve_company_id(payload.company_id, current_user)
    _assert_company_scope(company_id, current_user)

    name = _normalize_text(payload.name)
    code = _normalize_text(payload.code)
    if not name or not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name and code are required")

    _validate_group_uniqueness(db=db, company_id=company_id, name=name, code=code)

    group = TenantGroup(
        company_id=company_id,
        parent_group_id=None,
        name=name,
        code=code,
        email=_normalize_text(payload.email),
        short_name=_normalize_text(payload.short_name),
        description=_normalize_text(payload.description),
        is_default=payload.is_default,
        is_active=payload.is_active,
    )
    db.add(group)
    try:
        db.flush()
        if group.is_default:
            _enforce_single_default(group.company_id, group.group_id, db)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not create group") from exc
    db.refresh(group)
    return group


def list_groups(
    db: Session,
    current_user: AppUser,
    company_id: UUID | None = None,
    search: str | None = None,
) -> list[tuple[TenantGroup, int]]:
    if current_user.role != UserRole.super_admin.value:
        company_id = current_user.company_id

    query = (
        db.query(TenantGroup, func.count(Tenant.tenant_id))
        .outerjoin(Tenant, Tenant.group_id == TenantGroup.group_id)
    )
    if company_id is not None:
        query = query.filter(TenantGroup.company_id == company_id)
    if search:
        like_value = f"%{search}%"
        query = query.filter(or_(TenantGroup.name.ilike(like_value), TenantGroup.code.ilike(like_value)))

    return (
        query.group_by(TenantGroup.group_id)
        .order_by(TenantGroup.name.asc())
        .all()
    )


def update_group(group_id: int, payload, current_user: AppUser, db: Session) -> TenantGroup:
    _ensure_group_manager(current_user)
    group = get_group(group_id, db)
    _assert_company_scope(group.company_id, current_user)

    updated = payload.model_fields_set
    name = _normalize_text(payload.name) if "name" in updated else group.name
    code = _normalize_text(payload.code) if "code" in updated else group.code
    if not name or not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name and code are required")

    _validate_group_uniqueness(
        db=db,
        company_id=group.company_id,
        name=name,
        code=code,
        exclude_group_id=group_id,
    )
    group.parent_group_id = None
    if "name" in updated:
        group.name = name
    if "code" in updated:
        group.code = code
    if "email" in updated:
        group.email = _normalize_text(payload.email)
    if "short_name" in updated:
        group.short_name = _normalize_text(payload.short_name)
    if "description" in updated:
        group.description = _normalize_text(payload.description)
    if "is_default" in updated and payload.is_default is not None:
        group.is_default = payload.is_default
    if "is_active" in updated and payload.is_active is not None:
        group.is_active = payload.is_active

    try:
        db.flush()
        if group.is_default:
            _enforce_single_default(group.company_id, group.group_id, db)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not update group") from exc
    db.refresh(group)
    return group


def delete_group(group_id: int, current_user: AppUser, db: Session) -> None:
    _ensure_group_manager(current_user)
    group = get_group(group_id, db)
    _assert_company_scope(group.company_id, current_user)

    tenant_ids = (
        db.query(Tenant.tenant_id)
        .filter(Tenant.group_id == group_id)
        .distinct()
        .all()
    )
    if tenant_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Group cannot be deleted while it still has users. Reassign or delete those users first.",
        )

    db.delete(group)
    db.commit()


def get_tenant_group(tenant_id: int, db: Session) -> TenantGroupRead | None:
    tenant = _get_tenant_or_404(tenant_id, db)
    if tenant.group_id is None:
        return None
    row = get_group(tenant.group_id, db)
    return TenantGroupRead(
        group_id=row.group_id,
        name=row.name,
        code=row.code,
        short_name=row.short_name,
    )


def list_group_members(group_id: int, current_user: AppUser, db: Session) -> list[GroupMemberRead]:
    group = get_group(group_id, db)
    _assert_company_scope(group.company_id, current_user)

    tenants = (
        db.query(Tenant)
        .filter(Tenant.group_id == group_id)
        .order_by(Tenant.full_name.asc())
        .all()
    )
    tenant_ids = [tenant.tenant_id for tenant in tenants]
    site_accesses_by_tenant: dict[int, list[GroupMemberSiteAccessRead]] = {}

    if tenant_ids:
        site_rows = (
            db.query(TenantSiteAccess, Site)
            .join(Site, Site.site_id == TenantSiteAccess.site_id)
            .filter(
                TenantSiteAccess.tenant_id.in_(tenant_ids),
                Site.company_id == group.company_id,
            )
            .order_by(Site.name.asc())
            .all()
        )
        for site_access, site in site_rows:
            site_accesses_by_tenant.setdefault(site_access.tenant_id, []).append(
                GroupMemberSiteAccessRead(
                    site_access_id=site_access.site_access_id,
                    site_id=site.site_id,
                    site_name=site.name,
                    valid_from=site_access.valid_from,
                    valid_till=site_access.valid_till,
                    auto_assign_all_devices=site_access.auto_assign_all_devices,
                )
            )

    return [
        GroupMemberRead(
            tenant_id=tenant.tenant_id,
            full_name=tenant.full_name,
            email=tenant.email,
            phone=tenant.phone,
            tenant_type=tenant.tenant_type,
            is_active=tenant.is_active,
            site_accesses=site_accesses_by_tenant.get(tenant.tenant_id, []),
        )
        for tenant in tenants
    ]


def validate_group_selection(company_id: UUID, group_id: int | None, db: Session) -> TenantGroup | None:
    if group_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="group_id is required")

    group = db.query(TenantGroup).filter(TenantGroup.group_id == group_id).first()
    if not group:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Group not found")
    if group.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Group belongs to another company")
    if not group.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Group is inactive")
    return group


def add_tenant_to_group(group_id: int, tenant_id: int, current_user: AppUser, db: Session) -> TenantGroupRead | None:
    _ensure_group_manager(current_user)
    group = get_group(group_id, db)
    tenant = _get_tenant_or_404(tenant_id, db)

    _assert_company_scope(group.company_id, current_user)
    if tenant.company_id != group.company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant belongs to another company")

    return sync_tenant_group(tenant_id, group_id, current_user, db)


def remove_tenant_from_group(group_id: int, tenant_id: int, current_user: AppUser, db: Session) -> TenantGroupRead | None:
    _ensure_group_manager(current_user)
    group = get_group(group_id, db)
    _assert_company_scope(group.company_id, current_user)
    tenant = _get_tenant_or_404(tenant_id, db)
    if tenant.group_id == group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenants must always belong to a group. Assign the tenant to another group instead.",
        )
    return get_tenant_group(tenant_id, db)


def enroll_group_to_site(
    group_id: int,
    site_id: int,
    finger_index: int,
    valid_from: "datetime | None",
    valid_till: "datetime | None",
    current_user: AppUser,
    db: Session,
) -> dict:
    """Enroll all active tenants in a group to a site and every device in that site."""
    from app.api.services.tenants.enrollment import enroll_to_site
    from datetime import datetime

    _ensure_group_manager(current_user)
    group = get_group(group_id, db)
    _assert_company_scope(group.company_id, current_user)

    tenants = (
        db.query(Tenant)
        .filter(Tenant.group_id == group_id, Tenant.is_active == True)
        .order_by(Tenant.full_name)
        .all()
    )
    if not tenants:
        return {
            "group_id": group_id,
            "group_name": group.name,
            "site_id": site_id,
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "results": [],
            "message": "No active tenants found in this group.",
        }

    results = []
    succeeded = 0
    failed = 0

    for tenant in tenants:
        try:
            result = enroll_to_site(
                tenant_id=tenant.tenant_id,
                site_id=site_id,
                db=db,
                finger_index=finger_index,
                valid_from=valid_from,
                valid_till=valid_till,
                performed_by=current_user.user_id,
            )
            results.append({
                "tenant_id": tenant.tenant_id,
                "full_name": tenant.full_name,
                "success": True,
                "site_access_id": result.get("site_access_id"),
                "total_devices": result.get("total_devices"),
                "enrolled_devices": result.get("succeeded"),
                "correlation_ids": [
                    r.get("correlation_id") for r in result.get("results", []) if r.get("success") and r.get("correlation_id")
                ],
            })
            succeeded += 1
        except HTTPException as exc:
            results.append({
                "tenant_id": tenant.tenant_id,
                "full_name": tenant.full_name,
                "success": False,
                "error": exc.detail,
            })
            failed += 1

    return {
        "group_id": group_id,
        "group_name": group.name,
        "site_id": site_id,
        "total": len(tenants),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
        "message": f"Group enrollment complete. {succeeded}/{len(tenants)} tenant(s) enrolled to site {site_id}.",
    }


def enroll_group_to_devices(
    group_id: int,
    device_ids: list[int],
    finger_index: int,
    valid_from: "datetime | None",
    valid_till: "datetime | None",
    current_user: AppUser,
    db: Session,
) -> dict:
    """Enroll all active tenants in a group to specific devices."""
    from app.api.services.tenants.enrollment import enroll_to_devices_bulk

    _ensure_group_manager(current_user)
    group = get_group(group_id, db)
    _assert_company_scope(group.company_id, current_user)

    tenants = (
        db.query(Tenant)
        .filter(Tenant.group_id == group_id, Tenant.is_active == True)
        .order_by(Tenant.full_name)
        .all()
    )
    if not tenants:
        return {
            "group_id": group_id,
            "group_name": group.name,
            "device_ids": device_ids,
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "results": [],
            "message": "No active tenants found in this group.",
        }

    devices_payload = [{"device_id": did, "valid_from": valid_from, "valid_till": valid_till} for did in device_ids]
    results = []
    succeeded = 0
    failed = 0

    for tenant in tenants:
        try:
            result = enroll_to_devices_bulk(
                tenant_id=tenant.tenant_id,
                devices=devices_payload,
                db=db,
                finger_index=finger_index,
                performed_by=current_user.user_id,
            )
            results.append({
                "tenant_id": tenant.tenant_id,
                "full_name": tenant.full_name,
                "success": True,
                "enrolled_devices": result.get("succeeded"),
                "failed_devices": result.get("failed"),
                "correlation_ids": [
                    r.get("correlation_id") for r in result.get("results", []) if r.get("success") and r.get("correlation_id")
                ],
            })
            succeeded += 1
        except HTTPException as exc:
            results.append({
                "tenant_id": tenant.tenant_id,
                "full_name": tenant.full_name,
                "success": False,
                "error": exc.detail,
            })
            failed += 1

    return {
        "group_id": group_id,
        "group_name": group.name,
        "device_ids": device_ids,
        "total": len(tenants),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
        "message": f"Group enrollment complete. {succeeded}/{len(tenants)} tenant(s) processed for {len(device_ids)} device(s).",
    }


def sync_tenant_group(tenant_id: int, group_id: int | None, current_user: AppUser, db: Session) -> TenantGroupRead | None:
    _ensure_group_manager(current_user)
    tenant = _get_tenant_or_404(tenant_id, db)
    if tenant.company_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant is missing company_id")
    _assert_company_scope(tenant.company_id, current_user)

    desired_group = validate_group_selection(tenant.company_id, group_id, db)
    tenant.group_id = desired_group.group_id if desired_group is not None else None

    db.commit()
    return get_tenant_group(tenant_id, db)
