from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if hashed_password.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
        except ValueError:
            return False
    if not settings.allow_legacy_plaintext_password_login:
        return False
    return hmac.compare_digest(plain_password, hashed_password)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_storage_candidates(token: str) -> list[str]:
    token_hash = hash_token(token)
    return [token_hash] if token_hash == token else [token_hash, token]


def encrypt_password(password: str) -> str:
    """Encrypt a password for device API storage."""
    if not password:
        return ""
    cipher = Fernet(settings.encryption_key.encode())
    return cipher.encrypt(password.encode()).decode()


def decrypt_password(encrypted_password: str) -> str:
    """Decrypt a device API password."""
    if not encrypted_password:
        return ""
    cipher = Fernet(settings.encryption_key.encode())
    return cipher.decrypt(encrypted_password.encode()).decode()


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expires_delta = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    expire = datetime.now(UTC) + expires_delta
    payload: dict[str, Any] = {"sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expires_delta = expires_delta or timedelta(days=settings.refresh_token_expire_days)
    expire = datetime.now(UTC) + expires_delta
    payload: dict[str, Any] = {"sub": subject, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
