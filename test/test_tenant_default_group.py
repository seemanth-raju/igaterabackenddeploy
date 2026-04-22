from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.services.tenants import service as tenant_service
from app.api.services.tenants.schema import TenantCreate, TenantUpdate


def test_create_tenant_requires_explicit_group():
    with pytest.raises(Exception):
        TenantCreate(full_name="Alice")


def test_create_tenant_uses_selected_group(monkeypatch):
    company_id = uuid.uuid4()
    db = MagicMock()

    monkeypatch.setattr(
        tenant_service,
        "validate_group_selection",
        lambda company_id, group_id, db: SimpleNamespace(group_id=7),
    )

    tenant = tenant_service.create_tenant(TenantCreate(full_name="Alice", group_id=7), company_id, db)

    assert tenant.group_id == 7
    db.add.assert_called_once_with(tenant)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(tenant)


def test_update_tenant_rejects_null_group(monkeypatch):
    company_id = uuid.uuid4()
    tenant = SimpleNamespace(
        tenant_id=42,
        company_id=company_id,
        group_id=11,
        external_id=None,
        full_name="Alice",
        email=None,
        phone=None,
        tenant_type="employee",
        is_active=True,
        is_access_enabled=True,
        global_access_from=None,
        global_access_till=None,
    )
    db = MagicMock()

    monkeypatch.setattr(tenant_service, "get_tenant", lambda tenant_id, db: tenant)

    with pytest.raises(tenant_service.HTTPException) as exc_info:
        tenant_service.update_tenant(42, TenantUpdate(group_id=None), db)

    assert exc_info.value.status_code == 400
    assert "group_id cannot be null" in exc_info.value.detail
    db.commit.assert_not_called()
