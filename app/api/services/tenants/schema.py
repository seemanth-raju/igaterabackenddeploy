import re
import zoneinfo
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from app.api.services.groups.schema import TenantGroupRead

_EXTERNAL_ID_RE = re.compile(r"^[A-Za-z0-9]{1,15}$")


def _validate_external_id(v: str | None) -> str | None:
    if v is None:
        return v
    if not _EXTERNAL_ID_RE.match(v):
        raise ValueError(
            "Reference ID format is wrong. "
            "Only letters and numbers are allowed, no spaces or special characters, max 15 characters."
        )
    return v

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
    external_id: str | None = Field(default=None, max_length=15, description="Reference ID used as the user-id on devices (e.g. employee number). Max 15 chars, letters and numbers only, no spaces or special characters. Auto-generated from tenant_id if omitted. Must be unique per company.")
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

    @field_validator("external_id")
    @classmethod
    def validate_external_id(cls, v: str | None) -> str | None:
        return _validate_external_id(v)


class TenantUpdate(BaseModel):
    external_id: str | None = Field(default=None, max_length=15)

    @field_validator("external_id")
    @classmethod
    def validate_external_id(cls, v: str | None) -> str | None:
        return _validate_external_id(v)
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


class SetCardRequest(BaseModel):
    """Request body for POST /tenants/{id}/set-card."""

    device_id: int = Field(..., description="Target device.")
    card1: str = Field(..., description="Primary card number (RFID / QR-encoded value).")
    card2: str | None = Field(default=None, description="Secondary card number (optional).")
    valid_from: LocalDatetime = Field(default=None, description="Access window start — stored globally and sent to device.")
    valid_till: LocalDatetime = Field(default=None, description="Access window end — stored globally and sent to device.")


class SetPinRequest(BaseModel):
    """Request body for POST /tenants/{id}/set-pin."""

    device_id: int = Field(..., description="Target device.")
    pin: str = Field(..., min_length=4, max_length=8, description="4–8 digit PIN.")
    valid_from: LocalDatetime = Field(default=None, description="Access window start — stored globally and sent to device.")
    valid_till: LocalDatetime = Field(default=None, description="Access window end — stored globally and sent to device.")


class CaptureFaceRequest(BaseModel):
    """Request body for POST /tenants/{id}/capture-face."""

    device_id: int = Field(..., description="Device where the user will scan their face.")
    face_no: int = Field(default=1, ge=1, le=30, description="Face slot (1–30).")
    valid_from: LocalDatetime = Field(default=None)
    valid_till: LocalDatetime = Field(default=None)


class CaptureCardRequest(BaseModel):
    """Request body for POST /tenants/{id}/capture-card."""

    device_id: int = Field(..., description="Device where the user will tap their card.")
    card_no: int = Field(default=1, ge=1, le=2, description="Card slot (1 or 2).")
    valid_from: LocalDatetime = Field(default=None)
    valid_till: LocalDatetime = Field(default=None)


class ExtractFaceRequest(BaseModel):
    """Request body for POST /tenants/{id}/extract-face."""

    device_id: int = Field(..., description="Device the user has already scanned their face on.")
    face_no: int = Field(default=1, ge=1, le=30, description="Face slot (1–30).")


class ExtractCardRequest(BaseModel):
    """Request body for POST /tenants/{id}/extract-card."""

    device_id: int = Field(..., description="Device the user has already tapped their card on.")
    card_no: int = Field(default=1, ge=1, le=2, description="Card slot (1 or 2).")
