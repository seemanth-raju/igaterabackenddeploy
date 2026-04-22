from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TenantSiteAccessCreate(BaseModel):
    tenant_id: int
    site_id: int
    valid_from: datetime | None = Field(default=None)
    valid_till: datetime | None = Field(default=None)
    auto_assign_all_devices: bool = Field(
        default=False, description="Auto-grant access to all devices at this site"
    )


class TenantSiteAccessUpdate(BaseModel):
    valid_from: datetime | None = None
    valid_till: datetime | None = None
    auto_assign_all_devices: bool | None = None


class TenantSiteAccessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    site_access_id: int
    tenant_id: int
    site_id: int
    valid_from: datetime | None
    valid_till: datetime | None
    auto_assign_all_devices: bool


class TenantDeviceAccessCreate(BaseModel):
    tenant_id: int
    device_id: int
    site_access_id: int | None = Field(default=None)
    valid_from: datetime | None = Field(default=None)
    valid_till: datetime | None = Field(default=None)


class TenantDeviceAccessUpdate(BaseModel):
    valid_from: datetime | None = None
    valid_till: datetime | None = None


class TenantDeviceAccessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_access_id: int
    tenant_id: int
    device_id: int
    site_access_id: int | None
    valid_from: datetime | None
    valid_till: datetime | None


class BulkAccessRequest(BaseModel):
    tenant_id: int
    site_ids: list[int] = Field(default_factory=list)
    device_ids: list[int] = Field(default_factory=list)
    valid_from: datetime | None = None
    valid_till: datetime | None = None
    auto_assign_devices: bool = Field(default=False)
