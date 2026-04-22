from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.api.services.sites.schema import SiteCreate, SiteUpdate
from database.models import Company, Site


def _check_company_active(company_id: UUID, db: Session) -> None:
    company = db.query(Company).filter(Company.company_id == company_id).first()
    if company and not company.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company is inactive")


def create_site(payload: SiteCreate, company_id: UUID, db: Session) -> Site:
    _check_company_active(company_id, db)
    site = Site(
        company_id=company_id,
        name=payload.name,
        timezone=payload.timezone,
        address=payload.address,
        is_active=payload.is_active,
    )
    db.add(site)
    db.commit()
    db.refresh(site)
    return site


def list_sites(db: Session, company_id: UUID | None = None, skip: int = 0, limit: int = 50) -> list[Site]:
    query = db.query(Site)
    if company_id is not None:
        query = query.filter(Site.company_id == company_id)
    return query.order_by(Site.created_at.desc()).offset(skip).limit(limit).all()


def get_site(site_id: int, db: Session) -> Site:
    site = db.query(Site).filter(Site.site_id == site_id).first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    return site


def update_site(site_id: int, payload: SiteUpdate, db: Session) -> Site:
    site = get_site(site_id, db)

    if payload.name is not None:
        site.name = payload.name
    if payload.timezone is not None:
        site.timezone = payload.timezone
    if payload.address is not None:
        site.address = payload.address
    if payload.is_active is not None:
        site.is_active = payload.is_active

    db.commit()
    db.refresh(site)
    return site


def delete_site(site_id: int, db: Session) -> None:
    site = get_site(site_id, db)
    db.delete(site)
    db.commit()
