from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CompanyCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    domain: str | None = Field(default=None, max_length=100)
    primary_email: EmailStr | None = None
    secondary_email: EmailStr | None = None
    max_users: int | None = Field(default=None, ge=0, description="Maximum tenant/access users allowed. Null means unlimited.")
    max_devices: int | None = Field(default=None, ge=0, description="Maximum devices allowed. Null means unlimited.")
    is_active: bool = True


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    domain: str | None = Field(default=None, max_length=100)
    primary_email: EmailStr | None = None
    secondary_email: EmailStr | None = None
    max_users: int | None = Field(default=None, ge=0, description="Maximum tenant/access users allowed. Null means unlimited.")
    max_devices: int | None = Field(default=None, ge=0, description="Maximum devices allowed. Null means unlimited.")
    is_active: bool | None = None


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: UUID
    name: str
    domain: str | None
    primary_email: str | None
    secondary_email: str | None
    max_users: int | None
    max_devices: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
