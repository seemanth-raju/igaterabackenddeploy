from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DeviceUserMappingRead(BaseModel):
    """Schema for reading device user mapping."""

    model_config = ConfigDict(from_attributes=True)

    mapping_id: int
    tenant_id: int
    device_id: int
    matrix_user_id: str
    valid_from: datetime | None
    valid_till: datetime | None
    is_synced: bool
    last_sync_at: datetime | None
    last_sync_attempt_at: datetime | None
    sync_attempt_count: int
    sync_error: str | None
    device_response: dict
    created_at: datetime
    updated_at: datetime


class SyncStatusUpdate(BaseModel):
    """Update sync status of a device user mapping."""

    is_synced: bool
    sync_error: str | None = None
    device_response: dict | None = None
