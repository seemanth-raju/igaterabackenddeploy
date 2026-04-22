"""Storage path utilities."""

from pathlib import Path

from app.core.config import settings


def get_project_root() -> Path:
    return Path(__file__).parent.parent.parent


def get_fingerprint_storage_path() -> Path:
    path = get_project_root() / settings.fingerprint_storage_path
    path.mkdir(parents=True, exist_ok=True)
    return path
