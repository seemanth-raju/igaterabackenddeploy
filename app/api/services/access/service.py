from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.services.access.schema import (
    BulkAccessRequest,
    TenantDeviceAccessCreate,
    TenantDeviceAccessUpdate,
    TenantSiteAccessCreate,
    TenantSiteAccessUpdate,
)
from database.models import AppUser, Company, Device, Site, Tenant, TenantDeviceAccess, TenantSiteAccess, UserRole


_ACCESS_MANAGER_ROLES = {UserRole.super_admin.value, UserRole.company_admin.value}


def _ensure_access_manager(current_user: AppUser) -> None:
    if current_user.role not in _ACCESS_MANAGER_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _ensure_company_scope(company_id, current_user: AppUser) -> None:
    if current_user.role == UserRole.super_admin.value:
        return
    if current_user.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this company")


def _get_tenant(tenant_id: int, db: Session) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


def _get_site(site_id: int, db: Session) -> Site:
    site = db.query(Site).filter(Site.site_id == site_id).first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    return site


def _get_device(device_id: int, db: Session) -> Device:
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


def _ensure_same_company(company_id_a, company_id_b, detail: str) -> None:
    if company_id_a != company_id_b:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _authorize_site_access(site_access: TenantSiteAccess, current_user: AppUser, db: Session) -> None:
    _ensure_access_manager(current_user)
    tenant = _get_tenant(site_access.tenant_id, db)
    site = _get_site(site_access.site_id, db)
    _ensure_same_company(tenant.company_id, site.company_id, "Tenant and site belong to different companies")
    _ensure_company_scope(tenant.company_id, current_user)


def _authorize_device_access(device_access: TenantDeviceAccess, current_user: AppUser, db: Session) -> None:
    _ensure_access_manager(current_user)
    tenant = _get_tenant(device_access.tenant_id, db)
    device = _get_device(device_access.device_id, db)
    _ensure_same_company(tenant.company_id, device.company_id, "Tenant and device belong to different companies")
    _ensure_company_scope(tenant.company_id, current_user)


# ==================== SITE ACCESS ====================


def grant_site_access(payload: TenantSiteAccessCreate, current_user: AppUser, db: Session) -> TenantSiteAccess:
    _ensure_access_manager(current_user)
    tenant = _get_tenant(payload.tenant_id, db)
    if not tenant.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant is inactive")

    site = _get_site(payload.site_id, db)
    if not site.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Site is inactive")

    _ensure_same_company(tenant.company_id, site.company_id, "Tenant and site belong to different companies")
    _ensure_company_scope(tenant.company_id, current_user)

    company = db.query(Company).filter(Company.company_id == site.company_id).first()
    if company and not company.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company is inactive")

    site_access = TenantSiteAccess(
        tenant_id=payload.tenant_id,
        site_id=payload.site_id,
        valid_from=payload.valid_from,
        valid_till=payload.valid_till,
        auto_assign_all_devices=payload.auto_assign_all_devices,
    )
    db.add(site_access)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Site access already exists for this tenant",
        ) from exc
    db.refresh(site_access)

    if payload.auto_assign_all_devices:
        devices = db.query(Device).filter(Device.site_id == payload.site_id, Device.is_active == True).all()
        for device in devices:
            device_access = TenantDeviceAccess(
                tenant_id=payload.tenant_id,
                device_id=device.device_id,
                site_access_id=site_access.site_access_id,
                valid_from=payload.valid_from,
                valid_till=payload.valid_till,
            )
            db.add(device_access)
        db.commit()

    return site_access


def list_site_accesses(
    db: Session,
    current_user: AppUser,
    tenant_id: int | None = None,
    site_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[TenantSiteAccess]:
    _ensure_access_manager(current_user)
    query = db.query(TenantSiteAccess).join(Tenant, Tenant.tenant_id == TenantSiteAccess.tenant_id)
    if current_user.role != UserRole.super_admin.value:
        query = query.filter(Tenant.company_id == current_user.company_id)
    if tenant_id is not None:
        query = query.filter(TenantSiteAccess.tenant_id == tenant_id)
    if site_id is not None:
        query = query.filter(TenantSiteAccess.site_id == site_id)
    return query.offset(skip).limit(limit).all()


def get_site_access(site_access_id: int, current_user: AppUser, db: Session) -> TenantSiteAccess:
    site_access = db.query(TenantSiteAccess).filter(TenantSiteAccess.site_access_id == site_access_id).first()
    if not site_access:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site access not found")
    _authorize_site_access(site_access, current_user, db)
    return site_access


def update_site_access(site_access_id: int, payload: TenantSiteAccessUpdate, current_user: AppUser, db: Session) -> TenantSiteAccess:
    site_access = get_site_access(site_access_id, current_user, db)
    if payload.valid_from is not None:
        site_access.valid_from = payload.valid_from
    if payload.valid_till is not None:
        site_access.valid_till = payload.valid_till
    if payload.auto_assign_all_devices is not None:
        site_access.auto_assign_all_devices = payload.auto_assign_all_devices
    db.commit()
    db.refresh(site_access)
    return site_access


def revoke_site_access(site_access_id: int, current_user: AppUser, db: Session) -> None:
    site_access = get_site_access(site_access_id, current_user, db)
    db.query(TenantDeviceAccess).filter(TenantDeviceAccess.site_access_id == site_access_id).delete()
    db.delete(site_access)
    db.commit()


# ==================== DEVICE ACCESS ====================


def grant_device_access(payload: TenantDeviceAccessCreate, current_user: AppUser, db: Session) -> TenantDeviceAccess:
    _ensure_access_manager(current_user)
    tenant = _get_tenant(payload.tenant_id, db)
    if not tenant.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant is inactive")

    device = _get_device(payload.device_id, db)
    if not device.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device is inactive")

    _ensure_same_company(tenant.company_id, device.company_id, "Tenant and device belong to different companies")
    _ensure_company_scope(tenant.company_id, current_user)

    company = db.query(Company).filter(Company.company_id == device.company_id).first()
    if company and not company.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company is inactive")

    if payload.site_access_id is not None:
        site_access = db.query(TenantSiteAccess).filter(TenantSiteAccess.site_access_id == payload.site_access_id).first()
        if not site_access:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site access not found")
        if site_access.tenant_id != payload.tenant_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Site access does not belong to this tenant")
        if device.site_id != site_access.site_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Device does not belong to the site linked by site_access_id",
            )

    device_access = TenantDeviceAccess(
        tenant_id=payload.tenant_id,
        device_id=payload.device_id,
        site_access_id=payload.site_access_id,
        valid_from=payload.valid_from,
        valid_till=payload.valid_till,
    )
    db.add(device_access)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device access already exists for this tenant",
        ) from exc
    db.refresh(device_access)
    return device_access


def list_device_accesses(
    db: Session,
    current_user: AppUser,
    tenant_id: int | None = None,
    device_id: int | None = None,
    site_access_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[TenantDeviceAccess]:
    _ensure_access_manager(current_user)
    query = db.query(TenantDeviceAccess).join(Tenant, Tenant.tenant_id == TenantDeviceAccess.tenant_id)
    if current_user.role != UserRole.super_admin.value:
        query = query.filter(Tenant.company_id == current_user.company_id)
    if tenant_id is not None:
        query = query.filter(TenantDeviceAccess.tenant_id == tenant_id)
    if device_id is not None:
        query = query.filter(TenantDeviceAccess.device_id == device_id)
    if site_access_id is not None:
        query = query.filter(TenantDeviceAccess.site_access_id == site_access_id)
    return query.offset(skip).limit(limit).all()


def get_device_access(device_access_id: int, current_user: AppUser, db: Session) -> TenantDeviceAccess:
    device_access = (
        db.query(TenantDeviceAccess)
        .filter(TenantDeviceAccess.device_access_id == device_access_id)
        .first()
    )
    if not device_access:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device access not found")
    _authorize_device_access(device_access, current_user, db)
    return device_access


def update_device_access(
    device_access_id: int,
    payload: TenantDeviceAccessUpdate,
    current_user: AppUser,
    db: Session,
) -> TenantDeviceAccess:
    device_access = get_device_access(device_access_id, current_user, db)
    if payload.valid_from is not None:
        device_access.valid_from = payload.valid_from
    if payload.valid_till is not None:
        device_access.valid_till = payload.valid_till
    db.commit()
    db.refresh(device_access)
    return device_access


def revoke_device_access(device_access_id: int, current_user: AppUser, db: Session) -> None:
    device_access = get_device_access(device_access_id, current_user, db)
    db.delete(device_access)
    db.commit()


# ==================== BULK ====================


def grant_bulk_access(payload: BulkAccessRequest, current_user: AppUser, db: Session) -> dict:
    _ensure_access_manager(current_user)
    tenant = _get_tenant(payload.tenant_id, db)
    _ensure_company_scope(tenant.company_id, current_user)

    site_accesses_created = 0
    device_accesses_created = 0
    site_failures: list[dict] = []
    device_failures: list[dict] = []

    for site_id in payload.site_ids:
        try:
            grant_site_access(TenantSiteAccessCreate(
                tenant_id=payload.tenant_id,
                site_id=site_id,
                valid_from=payload.valid_from,
                valid_till=payload.valid_till,
                auto_assign_all_devices=payload.auto_assign_devices,
            ), current_user, db)
            site_accesses_created += 1
        except HTTPException as exc:
            site_failures.append({"site_id": site_id, "error": exc.detail})

    for device_id in payload.device_ids:
        try:
            grant_device_access(TenantDeviceAccessCreate(
                tenant_id=payload.tenant_id,
                device_id=device_id,
                valid_from=payload.valid_from,
                valid_till=payload.valid_till,
            ), current_user, db)
            device_accesses_created += 1
        except HTTPException as exc:
            device_failures.append({"device_id": device_id, "error": exc.detail})

    return {
        "tenant_id": payload.tenant_id,
        "site_accesses_created": site_accesses_created,
        "device_accesses_created": device_accesses_created,
        "site_failures": site_failures,
        "device_failures": device_failures,
        "message": "Bulk access grant complete",
    }
