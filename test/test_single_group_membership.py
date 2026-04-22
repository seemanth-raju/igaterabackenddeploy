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

from app.api.services.groups import service as group_service


def test_sync_tenant_group_replaces_existing_assignment(monkeypatch):
    company_id = uuid.uuid4()
    tenant = SimpleNamespace(tenant_id=42, company_id=company_id, group_id=7)
    current_user = SimpleNamespace(user_id="admin-1", company_id=company_id)
    desired_group = SimpleNamespace(group_id=11, company_id=company_id)
    db = MagicMock()

    monkeypatch.setattr(group_service, "_get_tenant_or_404", lambda tenant_id, db: tenant)
    monkeypatch.setattr(group_service, "_assert_company_scope", lambda company_id, current_user: None)
    monkeypatch.setattr(group_service, "validate_group_selection", lambda company_id, group_id, db: desired_group)
    monkeypatch.setattr(
        group_service,
        "get_tenant_group",
        lambda tenant_id, db: SimpleNamespace(group_id=11, name="HR", code="hr", short_name="HR"),
    )

    result = group_service.sync_tenant_group(42, 11, current_user, db)

    assert tenant.group_id == 11
    db.add.assert_not_called()
    db.delete.assert_not_called()
    db.commit.assert_called_once()
    assert result.group_id == 11


def test_validate_group_selection_requires_explicit_group():
    with pytest.raises(group_service.HTTPException) as exc_info:
        group_service.validate_group_selection(uuid.uuid4(), None, MagicMock())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "group_id is required"


def test_remove_tenant_from_group_requires_reassignment(monkeypatch):
    company_id = uuid.uuid4()
    tenant = SimpleNamespace(tenant_id=42, company_id=company_id, group_id=11)
    current_user = SimpleNamespace(user_id="admin-1", company_id=company_id)
    group = SimpleNamespace(group_id=11, company_id=company_id, is_default=False)
    db = MagicMock()

    monkeypatch.setattr(group_service, "get_group", lambda group_id, db: group)
    monkeypatch.setattr(group_service, "_get_tenant_or_404", lambda tenant_id, db: tenant)
    monkeypatch.setattr(group_service, "_assert_company_scope", lambda company_id, current_user: None)

    with pytest.raises(group_service.HTTPException) as exc_info:
        group_service.remove_tenant_from_group(11, 42, current_user, db)

    assert exc_info.value.status_code == 400
    assert "Tenants must always belong to a group" in exc_info.value.detail
    db.commit.assert_not_called()


def test_remove_tenant_from_other_group_returns_current_group_when_not_a_member(monkeypatch):
    company_id = uuid.uuid4()
    tenant = SimpleNamespace(tenant_id=42, company_id=company_id, group_id=5)
    current_user = SimpleNamespace(user_id="admin-1", company_id=company_id)
    group = SimpleNamespace(group_id=11, company_id=company_id, is_default=False)
    db = MagicMock()
    current_group = SimpleNamespace(group_id=5, name="HR", code="hr", short_name="HR")

    monkeypatch.setattr(group_service, "get_group", lambda group_id, db: group)
    monkeypatch.setattr(group_service, "_get_tenant_or_404", lambda tenant_id, db: tenant)
    monkeypatch.setattr(group_service, "_assert_company_scope", lambda company_id, current_user: None)
    monkeypatch.setattr(group_service, "get_tenant_group", lambda tenant_id, db: current_group)

    result = group_service.remove_tenant_from_group(11, 42, current_user, db)

    assert result is current_group
    db.commit.assert_not_called()
