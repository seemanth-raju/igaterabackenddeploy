from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.services.dashboard.schema import (
    DashboardSummary,
    EnrollmentStatus,
    GroupMemberCount,
    UserTypeCount,
)
from database.models import AppUser, Credential, Device, Site, Tenant, TenantGroup, UserRole

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardSummary)
def get_dashboard(
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> DashboardSummary:
    if current_user.role != UserRole.super_admin.value:
        company_id = current_user.company_id
    elif company_id is None:
        company_id = current_user.company_id

    total_users = (
        db.query(func.count(Tenant.tenant_id))
        .filter(Tenant.company_id == company_id)
        .scalar() or 0
    )
    active_locations = (
        db.query(func.count(Site.site_id))
        .filter(Site.company_id == company_id, Site.is_active == True)
        .scalar() or 0
    )
    connected_devices = (
        db.query(func.count(Device.device_id))
        .filter(Device.company_id == company_id, Device.is_active == True)
        .scalar() or 0
    )
    total_groups = (
        db.query(func.count(TenantGroup.group_id))
        .filter(TenantGroup.company_id == company_id, TenantGroup.is_active == True)
        .scalar() or 0
    )

    # Members per group (bar chart)
    group_rows = (
        db.query(TenantGroup.name, func.count(Tenant.tenant_id))
        .outerjoin(Tenant, Tenant.group_id == TenantGroup.group_id)
        .filter(TenantGroup.company_id == company_id, TenantGroup.is_active == True)
        .group_by(TenantGroup.group_id, TenantGroup.name)
        .order_by(TenantGroup.name)
        .all()
    )
    members_per_group = [
        GroupMemberCount(group_name=name, member_count=cnt) for name, cnt in group_rows
    ]

    # Enrollment status (donut chart): tenants with vs without any credential
    enrolled = (
        db.query(func.count(func.distinct(Credential.tenant_id)))
        .join(Tenant, Tenant.tenant_id == Credential.tenant_id)
        .filter(Tenant.company_id == company_id)
        .scalar() or 0
    )
    no_biometrics = total_users - enrolled

    # Users by type (donut chart)
    type_rows = (
        db.query(Tenant.tenant_type, func.count(Tenant.tenant_id))
        .filter(Tenant.company_id == company_id)
        .group_by(Tenant.tenant_type)
        .all()
    )
    users_by_type = [
        UserTypeCount(tenant_type=str(t_type or "unknown"), count=cnt)
        for t_type, cnt in type_rows
    ]

    return DashboardSummary(
        total_users=total_users,
        active_locations=active_locations,
        connected_devices=connected_devices,
        total_groups=total_groups,
        members_per_group=members_per_group,
        enrollment_status=EnrollmentStatus(enrolled=enrolled, no_biometrics=no_biometrics),
        users_by_type=users_by_type,
    )
