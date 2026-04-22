from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from database.models import UserRole


class UserCreate(BaseModel):
    company_id: UUID | None = None  # required for super_admin; auto-filled for company_admin
    username: str = Field(..., min_length=3, max_length=50)
    full_name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(..., min_length=8)
    role: UserRole = UserRole.staff


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    company_id: UUID | None
    role: str
    username: str | None
    full_name: str
    is_active: bool
    last_login: datetime | None
    created_at: datetime
