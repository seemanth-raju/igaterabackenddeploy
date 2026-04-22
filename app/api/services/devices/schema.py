from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.services.groups.schema import TenantGroupRead



class DeviceCreate(BaseModel):
    company_id: UUID | None = Field(
        default=None,
        description="Target company UUID. **Super-admin only** — ignored for all other roles.",
        examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )
    site_id: int | None = None
    device_serial_number: str | None = Field(default=None, max_length=100)
    vendor: str = Field(..., min_length=2, max_length=50)
    model_name: str | None = Field(default=None, max_length=100)
    ip_address: str | None = Field(default=None, max_length=45)
    mac_address: str | None = Field(default=None, max_length=17)
    api_username: str | None = Field(default=None, max_length=100)
    api_password: str | None = None
    api_port: int = Field(default=80, ge=1, le=65535)
    use_https: bool = False
    is_active: bool = True
    communication_mode: str = Field(default="direct", pattern="^(direct|push)$", description="'direct' for server-calls-device, 'push' for device-polls-server")
    push_token: str | None = Field(default=None, min_length=8, description="Shared secret for push-mode device auth (write-only, stored as hash)")
    status: str = Field(default="offline", max_length=20)
    config: dict = Field(default_factory=dict)


class DeviceUpdate(BaseModel):
    site_id: int | None = None
    device_serial_number: str | None = Field(default=None, min_length=1, max_length=100)
    vendor: str | None = Field(default=None, min_length=2, max_length=50)
    model_name: str | None = Field(default=None, max_length=100)
    ip_address: str | None = Field(default=None, max_length=45)
    mac_address: str | None = Field(default=None, max_length=17)
    api_username: str | None = Field(default=None, max_length=100)
    api_password: str | None = None
    api_port: int | None = Field(default=None, ge=1, le=65535)
    use_https: bool | None = None
    is_active: bool | None = None
    communication_mode: str | None = Field(default=None, pattern="^(direct|push)$")
    push_token: str | None = Field(default=None, min_length=8, description="Shared secret for push-mode device auth (write-only)")
    status: str | None = Field(default=None, max_length=20)
    config: dict | None = None


class DeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_id: int
    company_id: str | None
    site_id: int | None
    device_serial_number: str
    vendor: str
    model_name: str | None
    ip_address: str | None
    mac_address: str | None
    api_username: str | None
    api_port: int
    use_https: bool
    is_active: bool
    communication_mode: str
    status: str
    config: dict
    created_at: datetime


class DeviceImportRequest(BaseModel):
    company_id: UUID | None = Field(
        default=None,
        description="Target company UUID. Super-admin only; ignored for other roles.",
    )
    site_id: int = Field(..., description="Site the extraction device belongs to. All imported tenants will be granted access to this site.")
    device_serial_number: str | None = Field(
        default=None,
        max_length=100,
        description="Optional serial override. Defaults to MAC without separators.",
    )
    vendor: str | None = Field(default=None, min_length=2, max_length=50)
    model_name: str | None = Field(default=None, max_length=100)
    ip_address: str = Field(..., min_length=1, max_length=45)
    mac_address: str = Field(..., min_length=12, max_length=17)
    group_id: int = Field(..., description="Existing active group that imported users will be assigned to.")
    api_username: str | None = Field(default=None, min_length=1, max_length=100)
    api_password: str = Field(..., min_length=1)
    api_port: int | None = Field(default=None, ge=1, le=65535)
    use_https: bool | None = None
    communication_mode: str | None = Field(default=None, pattern="^(direct|push)$")


class ImportedTenantRead(BaseModel):
    tenant_id: int
    matrix_user_id: str
    external_id: str | None
    full_name: str
    is_active: bool
    valid_till: datetime | None = None
    finger_count: int = 0
    tenant_created: bool
    mapping_created: bool


class DeviceImportResponse(BaseModel):
    device: DeviceRead
    device_created: bool
    group: TenantGroupRead
    reported_user_count: int
    imported_user_count: int
    created_tenants: int
    updated_tenants: int
    created_mappings: int
    updated_mappings: int
    created_device_accesses: int
    created_site_accesses: int
    imported_fingerprint_count: int = 0
    users_with_fingerprints: int = 0
    warnings: list[str] = Field(default_factory=list)
    users: list[ImportedTenantRead] = Field(default_factory=list)
