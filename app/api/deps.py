from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token, token_storage_candidates
from database.models import AppUser, AuthToken
from database.session import SessionLocal

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _resolve_current_user(token: str | None, db: Session, *, allow_missing: bool) -> AppUser | None:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        if allow_missing:
            return None
        raise credentials_exception
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except Exception as exc:  # noqa: BLE001
        raise credentials_exception from exc

    token_row = (
        db.query(AuthToken)
        .filter(AuthToken.access_token.in_(token_storage_candidates(token)), AuthToken.revoked.is_(False))
        .first()
    )
    if not token_row:
        raise credentials_exception

    user = db.query(AppUser).filter(AppUser.user_id == user_id).first()
    if not user or not user.is_active:
        raise credentials_exception
    return user


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> AppUser:
    user = _resolve_current_user(token, db, allow_missing=False)
    assert user is not None
    return user


def get_current_user_optional(
    token: str | None = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> AppUser | None:
    return _resolve_current_user(token, db, allow_missing=True)
