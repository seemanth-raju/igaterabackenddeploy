from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from database.models import UserRole


class UserRegister(BaseModel):
    company_id: UUID
    full_name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(..., min_length=8)
    role: UserRole = UserRole.staff


class LoginRequest(BaseModel):
    username: str  # the generated username e.g. STF7XK3M
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


class UserMe(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    company_id: UUID | None
    role: str
    username: str | None
    full_name: str
    is_active: bool
    created_at: datetime
