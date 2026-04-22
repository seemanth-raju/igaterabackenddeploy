from datetime import UTC, datetime, timedelta
import secrets
import string

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.services.auth.schema import ChangePasswordRequest, LoginRequest, RefreshRequest, TokenResponse, UserRegister
from app.api.services.users.schema import UserCreate
from app.api.services.users.service import create_user
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, hash_password, hash_token, token_storage_candidates, verify_password
from database.models import AppUser, AuthToken, Company, UserRole


_USERNAME_PREFIXES: dict[str, str] = {
    UserRole.super_admin.value: "SUP",
    UserRole.company_admin.value: "ADM",
    UserRole.staff.value: "STF",
    UserRole.viewer.value: "VWR",
}


def _generate_candidate_username(role: str) -> str:
    prefix = _USERNAME_PREFIXES.get(role, "USR")
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(5))
    return f"{prefix}{suffix}"


def _generate_unique_username(role: str, db: Session) -> str:
    for _ in range(20):
        candidate = _generate_candidate_username(role)
        existing = db.query(AppUser).filter(func.lower(AppUser.username) == candidate.lower()).first()
        if not existing:
            return candidate
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to generate unique username")


def register_user(payload: UserRegister, current_user: AppUser, db: Session) -> AppUser:
    company_id = current_user.company_id if current_user.role == UserRole.company_admin.value else payload.company_id
    company = db.query(Company).filter(Company.company_id == company_id).first()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    return create_user(
        UserCreate(
            company_id=company_id,
            username=_generate_unique_username(payload.role.value, db),
            full_name=payload.full_name,
            password=payload.password,
            role=payload.role,
        ),
        current_user,
        db,
    )


def _access_token_expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)


def _refresh_token_expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)


def _revoke_user_tokens(user_id, db: Session) -> None:
    token_rows = db.query(AuthToken).filter(AuthToken.user_id == user_id, AuthToken.revoked.is_(False)).all()
    for token_row in token_rows:
        token_row.revoked = True


def _issue_tokens(user: AppUser, db: Session) -> TokenResponse:
    access_token = create_access_token(str(user.user_id))
    refresh_token = create_refresh_token(str(user.user_id))
    access_expires_at = _access_token_expires_at()
    refresh_expires_at = _refresh_token_expires_at()

    token_row = AuthToken(
        user_id=user.user_id,
        access_token=hash_token(access_token),
        refresh_token=hash_token(refresh_token),
        expires_at=refresh_expires_at,
        revoked=False,
    )
    db.add(token_row)
    db.commit()

    return TokenResponse(access_token=access_token, refresh_token=refresh_token, expires_at=access_expires_at)


def login(payload: LoginRequest, db: Session) -> TokenResponse:
    identifier = payload.username.strip().lower()
    user = db.query(AppUser).filter(func.lower(AppUser.username) == identifier).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.password_hash.startswith("$2"):
        user.password_hash = hash_password(payload.password)

    user.last_login = datetime.now(UTC)
    db.commit()

    return _issue_tokens(user, db)


def refresh_tokens(payload: RefreshRequest, db: Session) -> TokenResponse:
    token_row = (
        db.query(AuthToken)
        .filter(AuthToken.refresh_token.in_(token_storage_candidates(payload.refresh_token)), AuthToken.revoked.is_(False))
        .first()
    )
    if not token_row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if token_row.expires_at <= datetime.now(UTC):
        token_row.revoked = True
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    user = db.query(AppUser).filter(AppUser.user_id == token_row.user_id, AppUser.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    token_row.revoked = True
    db.commit()

    return _issue_tokens(user, db)


def change_password(current_user: AppUser, payload: ChangePasswordRequest, db: Session) -> TokenResponse:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the current password",
        )

    current_user.password_hash = hash_password(payload.new_password)
    _revoke_user_tokens(current_user.user_id, db)
    db.commit()

    return _issue_tokens(current_user, db)


def logout(access_token: str, db: Session) -> None:
    token_row = db.query(AuthToken).filter(AuthToken.access_token.in_(token_storage_candidates(access_token))).first()
    if token_row:
        token_row.revoked = True
        db.commit()
