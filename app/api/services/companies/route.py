from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.services.companies.schema import CompanyCreate, CompanyRead, CompanyUpdate
from app.api.services.companies.service import (
    create_company,
    delete_company,
    get_company,
    list_companies,
    update_company,
)
from database.models import AppUser, UserRole

router = APIRouter(prefix="/companies", tags=["companies"])


def _require_super_admin(current_user: AppUser) -> None:
    if current_user.role != UserRole.super_admin.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

def _to_company_read(company) -> CompanyRead:
    return CompanyRead(
        company_id=company.company_id,
        name=company.name,
        domain=company.domain,
        primary_email=company.primary_email,
        secondary_email=company.secondary_email,
        max_users=company.max_users,
        max_devices=company.max_devices,
        is_active=company.is_active,
        created_at=company.created_at,
        updated_at=company.updated_at,
    )


@router.post("", response_model=CompanyRead)
def create_company_route(
    payload: CompanyCreate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> CompanyRead:
    _require_super_admin(current_user)
    company = create_company(payload, db)
    return _to_company_read(company)


@router.get("", response_model=list[CompanyRead])
def list_companies_route(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[CompanyRead]:
    _require_super_admin(current_user)
    companies = list_companies(db, skip=skip, limit=limit, search=search)
    return [_to_company_read(company) for company in companies]


@router.get("/{company_id}", response_model=CompanyRead)
def get_company_route(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> CompanyRead:
    _require_super_admin(current_user)
    company = get_company(company_id, db)
    return _to_company_read(company)


@router.patch("/{company_id}", response_model=CompanyRead)
def update_company_route(
    company_id: UUID,
    payload: CompanyUpdate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> CompanyRead:
    _require_super_admin(current_user)
    company = update_company(company_id, payload, db)
    return _to_company_read(company)


@router.delete("/{company_id}")
def delete_company_route(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, str]:
    _require_super_admin(current_user)
    delete_company(company_id, db)
    return {"message": "Company deleted"}
