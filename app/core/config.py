from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from uuid import UUID


class Settings(BaseSettings):
    app_name: str = "Veda API"
    app_env: str = "development"
    app_debug: bool = False
    create_tables: bool = False

    database_url: str = "postgresql+psycopg2://user:password@localhost:5432/veda_db"

    # Required — no default. Set JWT_SECRET_KEY in .env
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Required — no default. Set ENCRYPTION_KEY in .env (valid Fernet key).
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str

    # Background worker intervals (seconds)
    log_sync_interval_seconds: int = 60
    validity_sync_interval_seconds: int = 60

    # Explicit origins required — wildcard is rejected at startup.
    # Example: CORS_ORIGINS=["http://localhost:3000","https://app.example.com"]
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Push API settings
    push_api_device_offline_seconds: int = 120
    push_api_default_poll_interval: int = 5

    # Local path for storing extracted fingerprint templates
    fingerprint_storage_path: str = "storage/fingerprints"

    # Streamlit/local-network migration uploads
    allow_anonymous_migration_uploads: bool = False
    anonymous_migration_default_company_id: UUID | None = None

    # Matrix devices should be LAN targets, not arbitrary backend-reachable URLs.
    matrix_device_allowed_cidrs: list[str] = [
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
    ]
    matrix_device_verify_tls: bool = True

    # Temporary migration escape hatch for old plaintext app_user.password_hash rows.
    allow_legacy_plaintext_password_login: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("jwt_secret_key")
    @classmethod
    def _jwt_secret_not_default(cls, v: str) -> str:
        if v in ("change-this-secret", "secret", ""):
            raise ValueError("JWT_SECRET_KEY must be set to a strong random value in .env")
        return v

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_cors(cls, v: list[str]) -> list[str]:
        if "*" in v:
            raise ValueError(
                "CORS_ORIGINS must not contain '*'. List explicit allowed origins in .env."
            )
        return v


settings = Settings()
