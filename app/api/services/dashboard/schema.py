from pydantic import BaseModel


class GroupMemberCount(BaseModel):
    group_name: str
    member_count: int


class EnrollmentStatus(BaseModel):
    enrolled: int
    no_biometrics: int


class UserTypeCount(BaseModel):
    tenant_type: str
    count: int


class DashboardSummary(BaseModel):
    total_users: int
    active_locations: int
    connected_devices: int
    total_groups: int
    members_per_group: list[GroupMemberCount]
    enrollment_status: EnrollmentStatus
    users_by_type: list[UserTypeCount]
