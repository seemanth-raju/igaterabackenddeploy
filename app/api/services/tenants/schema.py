import zoneinfo
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.api.services.groups.schema import TenantGroupRead

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def _localize_naive_to_ist(dt: datetime | None) -> datetime | None:
    """Convert a naive (no-tzinfo) datetime to UTC assuming it was entered in IST.

    The frontend sends local IST times without a timezone offset.  PostgreSQL
    TIMESTAMPTZ treats naive datetimes as UTC, so '15:29' IST would be stored
    as '15:29 UTC' (= 21:29 IST) — wrong by 5 h 30 m.

    If a timezone-aware datetime is passed it is simply normalised to UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Assume IST — attach the offset then convert to UTC
        return dt.replace(tzinfo=_IST).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


# Use this type everywhere a user-visible datetime field is accepted
LocalDatetime = Annotated[datetime | None, AfterValidator(_localize_naive_to_ist)]


class TenantCreate(BaseModel):
    """Request body for POST /tenants — create a tenant (no device interaction)."""

    company_id: UUID | None = Field(
        default=None,
        description="Super-admin only. Target company for this tenant. Ignored for non-super-admin users.",
    )
    external_id: str | None = Field(default=None, max_length=50)
    full_name: str = Field(..., min_length=1, max_length=15, description="Max 15 chars — device hardware limit.")
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    tenant_type: str = Field(default="employee", max_length=50)
    is_active: bool = True
    global_access_from: LocalDatetime = None
    global_access_till: LocalDatetime = None
    group_id: int = Field(
        ...,
        description="Single required group assignment for this tenant.",
    )


class TenantUpdate(BaseModel):
    external_id: str | None = Field(default=None, max_length=50)
    full_name: str | None = Field(default=None, min_length=1, max_length=15)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    tenant_type: str | None = None
    is_active: bool | None = None
    is_access_enabled: bool | None = Field(default=None, description="Master access switch")
    global_access_from: LocalDatetime = None
    global_access_till: LocalDatetime = None
    group_id: int | None = Field(
        default=None,
        description="Single group assignment for this tenant. Omit to keep the current group; null is not allowed.",
    )


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: int
    company_id: str | None
    external_id: str | None
    full_name: str
    email: str | None
    phone: str | None
    tenant_type: str
    is_active: bool
    is_access_enabled: bool
    global_access_from: datetime | None
    global_access_till: datetime | None
    access_timezone: str
    created_at: datetime
    finger_count: int = Field(default=0, description="Number of fingerprint credentials stored")
    has_face: bool = Field(default=False, description="Face credential stored")
    has_card: bool = Field(default=False, description="Card credential stored")
    enrolled_device_count: int = 0
    group: TenantGroupRead | None = None


class CaptureRequest(BaseModel):
    """Request body for POST /tenants/{id}/capture-fingerprint."""

    device_id: int = Field(..., description="Device where the user will scan their finger.")
    finger_index: int = Field(default=1, ge=1, le=10, description="Finger slot (1 = right thumb).")
    valid_from: LocalDatetime = Field(
        default=None,
        description="Tenant global access start date. Also stored on this device mapping.",
    )
    valid_till: LocalDatetime = Field(
        default=None,
        description="Tenant global access end date. Also sent to this device as the expiry date.",
    )


class DeviceEnrollRequest(BaseModel):
    """Request body for POST /tenants/{id}/enroll."""

    device_id: int = Field(..., description="Target device.")
    finger_index: int = Field(default=1, ge=1, le=10)
    valid_from: LocalDatetime = Field(
        default=None,
        description="Tenant global access start date. Also stored on this device mapping.",
    )
    valid_till: LocalDatetime = Field(
        default=None,
        description="Tenant global access end date. Also sent to this device as the expiry date.",
    )


class BulkEnrollItem(BaseModel):
    """A single device entry in a bulk enroll request."""

    device_id: int
    valid_from: LocalDatetime = None
    valid_till: LocalDatetime = None


class BulkEnrollRequest(BaseModel):
    """Request body for POST /tenants/{id}/enroll-bulk."""

    devices: list[BulkEnrollItem] = Field(..., min_length=1)
    finger_index: int = Field(default=1, ge=1, le=10)


class SiteEnrollRequest(BaseModel):
    """Request body for POST /tenants/{id}/enroll-site."""

    site_id: int = Field(..., description="Site to grant access to. All active devices in this site will be enrolled.")
    finger_index: int = Field(default=1, ge=1, le=10)
    valid_from: LocalDatetime = Field(default=None, description="Access window start. Applied to site record and all device mappings.")
    valid_till: LocalDatetime = Field(default=None, description="Access window end. Applied to site record and all device mappings.")


class DeviceAccessUpdate(BaseModel):
    """Request body for PATCH /tenants/{id}/device-access/{device_id}."""

    valid_from: LocalDatetime = Field(
        default=None,
        description="New per-device access start date (None = clear override, use global).",
    )
    valid_till: LocalDatetime = Field(
        default=None,
        description="New per-device access end date (None = clear override, use global).",
    )


class DeviceAccessRead(BaseModel):
    """Per-device access record returned by GET /tenants/{id}/device-access."""

    model_config = ConfigDict(from_attributes=True)

    mapping_id: int
    device_id: int
    matrix_user_id: str
    valid_from: datetime | None
    valid_till: datetime | None
    is_synced: bool
    last_sync_at: datetime | None
    created_at: datetime
