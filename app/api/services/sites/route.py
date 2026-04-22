
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.services.sites.schema import SiteCreate, SiteRead, SiteUpdate
from app.api.services.sites.service import create_site, delete_site, get_site, list_sites, update_site
from database.models import AppUser, UserRole

router = APIRouter(prefix="/sites", tags=["sites"])

_SITE_MANAGER_ROLES = {UserRole.super_admin.value, UserRole.company_admin.value}


def _resolve_company_id(requested: UUID | None, current_user: AppUser) -> UUID:
    """Super-admins may supply an explicit company_id; everyone else is scoped to their own."""
    if current_user.role == UserRole.super_admin.value and requested is not None:
        return requested
    return current_user.company_id


def _to_site_read(site) -> SiteRead:
    return SiteRead(
        site_id=site.site_id,
        company_id=str(site.company_id),
        name=site.name,
        timezone=site.timezone,
        address=site.address,
        is_active=site.is_active,
        created_at=site.created_at,
    )


def _require_site_manager(current_user: AppUser) -> None:
    if current_user.role not in _SITE_MANAGER_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


@router.post("", response_model=SiteRead)
def create_site_route(
    payload: SiteCreate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> SiteRead:
    _require_site_manager(current_user)
    site = create_site(payload, _resolve_company_id(payload.company_id, current_user), db)
    return _to_site_read(site)


@router.get("", response_model=list[SiteRead])
def list_sites_route(
    company_id: UUID | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[SiteRead]:
    if current_user.role != UserRole.super_admin.value:
        # For non-super admins, force filtering by their own company
        company_id = current_user.company_id

    # If super admin and no company_id provided, it lists all sites (optional behavior, or we can enforce filtering)
    # The requirement said "get enpoint shoudl retunr sites under the user company id only"
    # and "if the user is super admin then he can see sites with compnay ids for that create an endpoint which return sites by taking company id as input"

    sites = list_sites(db, company_id=company_id, skip=skip, limit=limit)
    return [_to_site_read(site) for site in sites]


@router.get("/{site_id}", response_model=SiteRead)
def get_site_route(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> SiteRead:
    site = get_site(site_id, db)
    if current_user.role != UserRole.super_admin.value and site.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this site")
    return _to_site_read(site)


@router.patch("/{site_id}", response_model=SiteRead)
def update_site_route(
    site_id: int,
    payload: SiteUpdate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> SiteRead:
    # Verify access first
    _require_site_manager(current_user)
    site = get_site(site_id, db)
    if current_user.role != UserRole.super_admin.value and site.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update this site")

    site = update_site(site_id, payload, db)
    return _to_site_read(site)


@router.delete("/{site_id}")
def delete_site_route(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, str]:
    # Verify access first
    _require_site_manager(current_user)
    site = get_site(site_id, db)
    if current_user.role != UserRole.super_admin.value and site.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this site")

    delete_site(site_id, db)
    return {"message": "Site deleted"}
