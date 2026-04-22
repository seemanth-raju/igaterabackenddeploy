from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GroupCreate(BaseModel):
    company_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=100)
    code: str = Field(..., min_length=1, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    short_name: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=250)
    is_default: bool = False
    is_active: bool = True


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    short_name: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=250)
    is_default: bool | None = None
    is_active: bool | None = None


class GroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    group_id: int
    company_id: UUID
    name: str
    code: str
    email: str | None
    short_name: str | None
    description: str | None
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    member_count: int = 0


class TenantGroupRead(BaseModel):
    group_id: int
    name: str
    code: str
    short_name: str | None


class GroupMemberSiteAccessRead(BaseModel):
    site_access_id: int
    site_id: int
    site_name: str
    valid_from: datetime | None
    valid_till: datetime | None
    auto_assign_all_devices: bool


class GroupMemberRead(BaseModel):
    tenant_id: int
    full_name: str
    email: str | None
    phone: str | None
    tenant_type: str
    is_active: bool
    site_accesses: list[GroupMemberSiteAccessRead] = Field(default_factory=list)


class GroupEnrollSiteRequest(BaseModel):
    site_id: int
    finger_index: int = Field(default=1, ge=1, le=10)
    valid_from: datetime | None = None
    valid_till: datetime | None = None


class GroupEnrollDevicesRequest(BaseModel):
    device_ids: list[int] = Field(..., min_length=1)
    finger_index: int = Field(default=1, ge=1, le=10)
    valid_from: datetime | None = None
    valid_till: datetime | None = None
