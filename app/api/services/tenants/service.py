import logging
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.services.companies.service import ensure_company_user_quota
from app.api.services.groups.service import validate_group_selection
from app.api.services.tenants.schema import TenantCreate, TenantUpdate
from database.models import AccessEvent, Credential, DeviceUserMapping, Tenant

log = logging.getLogger(__name__)


def _resolve_group_id(company_id: UUID | None, group_id: int | None, db: Session) -> int | None:
    if group_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="group_id is required")
    if company_id is None:
        return group_id
    group = validate_group_selection(company_id, group_id, db)
    return group.group_id if group is not None else None


def create_tenant(payload: TenantCreate, company_id: UUID, db: Session) -> Tenant:
    ensure_company_user_quota(company_id, db)
    tenant = Tenant(
        company_id=company_id,
        group_id=_resolve_group_id(company_id, payload.group_id, db),
        external_id=payload.external_id,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        tenant_type=payload.tenant_type,
        is_active=payload.is_active,
        global_access_from=payload.global_access_from,
        global_access_till=payload.global_access_till,
    )

    db.add(tenant)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant with same external_id already exists for this company",
        ) from exc
    db.refresh(tenant)
    return tenant


def list_tenants(
    db: Session,
    company_id: UUID | None = None,
    skip: int = 0,
    limit: int = 50,
    search: str | None = None,
    group_id: int | None = None,
) -> list[Tenant]:
    query = db.query(Tenant)

    if company_id is not None:
        query = query.filter(Tenant.company_id == company_id)

    if group_id is not None:
        query = query.filter(Tenant.group_id == group_id)

    if search:
        like_value = f"%{search}%"
        query = query.filter(Tenant.full_name.ilike(like_value))

    return query.order_by(Tenant.created_at.desc()).offset(skip).limit(limit).all()


def get_tenant(tenant_id: int, db: Session) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


def update_tenant(tenant_id: int, payload: TenantUpdate, db: Session) -> Tenant:
    tenant = get_tenant(tenant_id, db)

    updated = payload.model_fields_set

    if "external_id" in updated:
        tenant.external_id = payload.external_id
    if "group_id" in updated:
        if payload.group_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="group_id cannot be null. Assign the tenant to another group instead.",
            )
        tenant.group_id = _resolve_group_id(tenant.company_id, payload.group_id, db)
    if "full_name" in updated and payload.full_name is not None:
        tenant.full_name = payload.full_name
    if "email" in updated:
        tenant.email = payload.email
    if "phone" in updated:
        tenant.phone = payload.phone
    if "tenant_type" in updated and payload.tenant_type is not None:
        tenant.tenant_type = payload.tenant_type
    if "is_active" in updated and payload.is_active is not None:
        tenant.is_active = payload.is_active
    if "is_access_enabled" in updated and payload.is_access_enabled is not None:
        tenant.is_access_enabled = payload.is_access_enabled
    # Date fields: allow explicit null to clear them
    if "global_access_from" in updated:
        tenant.global_access_from = payload.global_access_from
    if "global_access_till" in updated:
        tenant.global_access_till = payload.global_access_till

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant with same external_id already exists for this company",
        ) from exc
    db.refresh(tenant)
    return tenant


def delete_tenant(tenant_id: int, db: Session) -> None:
    tenant = get_tenant(tenant_id, db)
    db.delete(tenant)
    db.commit()


def delete_tenant_with_related_data(tenant_id: int, db: Session, *, performed_by=None) -> None:
    """Delete a tenant plus device enrollments and stored credential files.

    AccessEvent rows are preserved by the database via ON DELETE SET NULL.
    """
    tenant = get_tenant(tenant_id, db)
    credential_paths = [
        file_path
        for file_path, in (
            db.query(Credential.file_path)
            .filter(Credential.tenant_id == tenant_id, Credential.file_path.is_not(None))
            .all()
        )
        if file_path
    ]

    from app.api.services.tenants.enrollment import unenroll_from_devices_bulk

    mappings = db.query(DeviceUserMapping).filter(DeviceUserMapping.tenant_id == tenant_id).all()
    if mappings:
        unenroll_from_devices_bulk(
            tenant_id=tenant_id,
            device_ids=[mapping.device_id for mapping in mappings],
            db=db,
            performed_by=performed_by,
        )

    try:
        # Null out tenant_id on access events to preserve the audit trail.
        # The model declares ON DELETE SET NULL but the live DB constraint may not
        # have been migrated yet, so we do it explicitly here to be safe.
        db.query(AccessEvent).filter(AccessEvent.tenant_id == tenant_id).update(
            {AccessEvent.tenant_id: None}, synchronize_session=False
        )
        db.delete(tenant)
        db.commit()
    except Exception:
        db.rollback()
        raise

    for file_path in dict.fromkeys(credential_paths):
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
        except OSError:
            log.warning("Could not delete credential file for tenant %s: %s", tenant_id, file_path)
