from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.api.services.companies.schema import CompanyCreate, CompanyUpdate
from database.models import Company, Device, Tenant


DELETE_COMPANY_VALIDATION_LOGS_SQL = """
WITH company_devices AS (
    SELECT device_id
    FROM public.device
    WHERE company_id = CAST(:company_id AS uuid)
),
company_sites AS (
    SELECT site_id
    FROM public.site
    WHERE company_id = CAST(:company_id AS uuid)
),
company_tenants AS (
    SELECT tenant_id
    FROM public.tenant
    WHERE company_id = CAST(:company_id AS uuid)
),
company_events AS (
    SELECT event_id
    FROM public.access_event
    WHERE company_id = CAST(:company_id AS uuid)
       OR device_id IN (SELECT device_id FROM company_devices)
       OR tenant_id IN (SELECT tenant_id FROM company_tenants)
)
DELETE FROM public.access_validation_log
WHERE access_event_id IN (SELECT event_id FROM company_events)
   OR device_id IN (SELECT device_id FROM company_devices)
   OR site_id IN (SELECT site_id FROM company_sites)
   OR tenant_id IN (SELECT tenant_id FROM company_tenants)
"""


DELETE_COMPANY_ACCESS_EVENTS_SQL = """
WITH company_devices AS (
    SELECT device_id
    FROM public.device
    WHERE company_id = CAST(:company_id AS uuid)
),
company_tenants AS (
    SELECT tenant_id
    FROM public.tenant
    WHERE company_id = CAST(:company_id AS uuid)
)
DELETE FROM public.access_event
WHERE company_id = CAST(:company_id AS uuid)
   OR device_id IN (SELECT device_id FROM company_devices)
   OR tenant_id IN (SELECT tenant_id FROM company_tenants)
"""


def _enforce_quota(*, limit: int | None, current_count: int, increment: int, detail: str) -> None:
    if limit is None:
        return
    if current_count + increment > limit:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def ensure_company_user_quota(company_id: UUID, db: Session, *, increment: int = 1) -> None:
    company = get_company(company_id, db)
    current_count = db.query(Tenant).filter(Tenant.company_id == company_id).count()
    _enforce_quota(
        limit=company.max_users,
        current_count=current_count,
        increment=increment,
        detail=f"Company user limit reached ({current_count}/{company.max_users})",
    )


def ensure_company_device_quota(company_id: UUID, db: Session, *, increment: int = 1) -> None:
    company = get_company(company_id, db)
    current_count = db.query(Device).filter(Device.company_id == company_id).count()
    _enforce_quota(
        limit=company.max_devices,
        current_count=current_count,
        increment=increment,
        detail=f"Company device limit reached ({current_count}/{company.max_devices})",
    )


def create_company(payload: CompanyCreate, db: Session) -> Company:
    if payload.domain:
        existing_domain = db.query(Company).filter(Company.domain == payload.domain).first()
        if existing_domain:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Domain already exists")

    company = Company(
        name=payload.name,
        domain=payload.domain,
        primary_email=str(payload.primary_email) if payload.primary_email else None,
        secondary_email=str(payload.secondary_email) if payload.secondary_email else None,
        max_users=payload.max_users,
        max_devices=payload.max_devices,
        is_active=payload.is_active,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def list_companies(db: Session, skip: int = 0, limit: int = 50, search: str | None = None) -> list[Company]:
    query = db.query(Company)
    if search:
        like_value = f"%{search}%"
        query = query.filter(or_(Company.name.ilike(like_value), Company.domain.ilike(like_value)))

    return query.order_by(Company.created_at.desc()).offset(skip).limit(limit).all()


def get_company(company_id: UUID, db: Session) -> Company:
    company = db.query(Company).filter(Company.company_id == company_id).first()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company


def update_company(company_id: UUID, payload: CompanyUpdate, db: Session) -> Company:
    company = get_company(company_id, db)

    if payload.domain is not None:
        existing_domain = (
            db.query(Company)
            .filter(Company.domain == payload.domain, Company.company_id != company_id)
            .first()
        )
        if existing_domain:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Domain already exists")

    if payload.name is not None:
        company.name = payload.name
    if payload.domain is not None:
        company.domain = payload.domain
    if payload.primary_email is not None:
        company.primary_email = str(payload.primary_email)
    if payload.secondary_email is not None:
        company.secondary_email = str(payload.secondary_email)
    if "max_users" in payload.model_fields_set:
        company.max_users = payload.max_users
    if "max_devices" in payload.model_fields_set:
        company.max_devices = payload.max_devices
    if payload.is_active is not None:
        company.is_active = payload.is_active

    company.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(company)
    return company


def delete_company(company_id: UUID, db: Session) -> None:
    company = get_company(company_id, db)
    params = {"company_id": str(company_id)}
    db.execute(text(DELETE_COMPANY_VALIDATION_LOGS_SQL), params)
    db.execute(text(DELETE_COMPANY_ACCESS_EVENTS_SQL), params)
    db.delete(company)
    db.commit()
