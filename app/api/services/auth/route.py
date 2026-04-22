from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, oauth2_scheme
from app.api.services.auth.schema import ChangePasswordRequest, LoginRequest, RefreshRequest, TokenResponse, UserMe, UserRegister
from app.api.services.auth.service import change_password, login, logout, refresh_tokens, register_user
from database.models import AppUser

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_user_me(user: AppUser) -> UserMe:
    return UserMe(
        user_id=user.user_id,
        company_id=user.company_id,
        role=user.role,
        username=user.username,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.post("/register", response_model=UserMe)
def register(
    payload: UserRegister,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> UserMe:
    user = register_user(payload, current_user, db)
    return _to_user_me(user)


@router.post("/login", response_model=TokenResponse)
def login_route(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    return login(payload, db)


@router.post("/token", response_model=TokenResponse)
async def token_route(request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    content_type = request.headers.get("content-type", "")
    username: str | None = None
    password: str | None = None

    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")
    elif "application/json" in content_type:
        body = await request.json()
        username = body.get("username")
        password = body.get("password")

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="username and password are required",
        )

    return login(LoginRequest(username=username, password=password), db)


@router.post("/refresh", response_model=TokenResponse)
def refresh_route(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    return refresh_tokens(payload, db)


@router.post("/logout")
def logout_route(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> dict[str, str]:
    logout(token, db)
    return {"message": "Logged out"}


@router.get("/me", response_model=UserMe)
def me_route(current_user: AppUser = Depends(get_current_user)) -> UserMe:
    return _to_user_me(current_user)


@router.post("/change-password", response_model=TokenResponse)
def change_password_route(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> TokenResponse:
    return change_password(current_user, payload, db)
