from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.services.users.schema import UserCreate, UserUpdate
from app.core.security import hash_password
from database.models import AppUser, AuthToken, Company, UserRole

# Which roles each role is allowed to create
_ALLOWED_TO_CREATE: dict[str, set[str]] = {
    UserRole.super_admin.value: {r.value for r in UserRole},
    UserRole.company_admin.value: {UserRole.staff.value, UserRole.viewer.value},
    UserRole.staff.value: set(),
    UserRole.viewer.value: set(),
}

_ADMIN_ROLES = {UserRole.super_admin.value, UserRole.company_admin.value}


def _revoke_user_tokens(user_id, db: Session) -> None:
    token_rows = db.query(AuthToken).filter(AuthToken.user_id == user_id, AuthToken.revoked.is_(False)).all()
    for token_row in token_rows:
        token_row.revoked = True


def _ensure_admin(current_user: AppUser) -> None:
    if current_user.role not in _ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _ensure_same_company_or_super_admin(current_user: AppUser, target_user: AppUser) -> None:
    if current_user.role == UserRole.super_admin.value:
        return
    if current_user.company_id != target_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this user")


def _ensure_manageable_target(current_user: AppUser, target_user: AppUser) -> None:
    _ensure_admin(current_user)
    _ensure_same_company_or_super_admin(current_user, target_user)

    if current_user.role == UserRole.company_admin.value and target_user.role not in _ALLOWED_TO_CREATE[current_user.role]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to manage this user")


def create_user(payload: UserCreate, current_user: AppUser, db: Session) -> AppUser:
    # Role-based creation guard
    target_role = payload.role.value
    allowed = _ALLOWED_TO_CREATE.get(current_user.role, set())
    if target_role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Your role ({current_user.role}) is not allowed to create '{target_role}' users",
        )

    # Company scoping: company_admin is always locked to their own company
    if current_user.role == UserRole.company_admin.value:
        company_id = current_user.company_id
    else:
        if not payload.company_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="company_id is required for super_admin")
        company_id = payload.company_id

    company = db.query(Company).filter(Company.company_id == company_id).first()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    # Username uniqueness (case-insensitive)
    existing = db.query(AppUser).filter(func.lower(AppUser.username) == payload.username.lower()).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Username '{payload.username}' is already taken")

    user = AppUser(
        company_id=company_id,
        role=target_role,
        username=payload.username,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_users(db: Session, current_user: AppUser, skip: int = 0, limit: int = 50) -> list[AppUser]:
    _ensure_admin(current_user)
    q = db.query(AppUser)
    if current_user.role != UserRole.super_admin.value:
        q = q.filter(AppUser.company_id == current_user.company_id)
    return q.order_by(AppUser.created_at.desc()).offset(skip).limit(limit).all()


def get_user(user_id: str, db: Session) -> AppUser:
    user = db.query(AppUser).filter(AppUser.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def get_user_for_request(user_id: str, current_user: AppUser, db: Session) -> AppUser:
    user = get_user(user_id, db)
    if current_user.role in _ADMIN_ROLES:
        _ensure_same_company_or_super_admin(current_user, user)
        return user
    if current_user.user_id == user.user_id:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this user")


def update_user(user_id: str, payload: UserUpdate, current_user: AppUser, db: Session) -> AppUser:
    user = get_user(user_id, db)
    _ensure_manageable_target(current_user, user)

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.role is not None:
        if current_user.role == UserRole.company_admin.value and payload.role.value not in _ALLOWED_TO_CREATE[current_user.role]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to assign this role")
        user.role = payload.role.value
    if payload.is_active is not None:
        if current_user.user_id == user.user_id and payload.is_active is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account")
        user.is_active = payload.is_active
    if payload.password:
        user.password_hash = hash_password(payload.password)

    db.commit()
    db.refresh(user)
    return user


def deactivate_user(user_id: str, current_user: AppUser, db: Session) -> None:
    user = get_user(user_id, db)
    _ensure_manageable_target(current_user, user)
    if current_user.user_id == user.user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account")
    user.is_active = False
    _revoke_user_tokens(user.user_id, db)
    db.commit()
