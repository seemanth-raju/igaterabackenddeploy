from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.services.users.schema import UserCreate, UserRead, UserUpdate
from app.api.services.users.service import create_user, deactivate_user, get_user_for_request, list_users, update_user
from database.models import AppUser

router = APIRouter(prefix="/users", tags=["users"])


def _to_user_read(user: AppUser) -> UserRead:
    return UserRead(
        user_id=user.user_id,
        company_id=user.company_id,
        role=user.role,
        username=user.username,
        full_name=user.full_name,
        is_active=user.is_active,
        last_login=user.last_login,
        created_at=user.created_at,
    )


@router.post("", response_model=UserRead)
def create_user_route(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> UserRead:
    user = create_user(payload, current_user, db)
    return _to_user_read(user)


@router.get("", response_model=list[UserRead])
def list_users_route(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> list[UserRead]:
    users = list_users(db, current_user=current_user, skip=skip, limit=limit)
    return [_to_user_read(user) for user in users]


@router.get("/{user_id}", response_model=UserRead)
def get_user_route(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> UserRead:
    user = get_user_for_request(str(user_id), current_user, db)
    return _to_user_read(user)


@router.patch("/{user_id}", response_model=UserRead)
def update_user_route(
    user_id: UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> UserRead:
    user = update_user(str(user_id), payload, current_user, db)
    return _to_user_read(user)


@router.delete("/{user_id}")
def deactivate_user_route(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, str]:
    deactivate_user(str(user_id), current_user, db)
    return {"message": "User deactivated"}
