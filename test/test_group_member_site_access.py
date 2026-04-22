from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.services.groups import service as group_service
from app.api.services.tenants import enrollment as enrollment_service
from database.models import Site, Tenant, TenantSiteAccess


class QueryStub:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


def test_group_members_include_site_accesses(monkeypatch):
    group = SimpleNamespace(group_id=4, company_id="company-1")
    tenant = SimpleNamespace(
        tenant_id=42,
        full_name="Jane",
        email="jane@example.com",
        phone=None,
        tenant_type="employee",
        is_active=True,
    )
    site_access = SimpleNamespace(
        site_access_id=10,
        tenant_id=42,
        valid_from=None,
        valid_till=None,
        auto_assign_all_devices=True,
    )
    site = SimpleNamespace(site_id=2, name="Head Office")

    db = MagicMock()

    def fake_query(*models):
        if models == (Tenant,):
            return QueryStub([tenant])
        if models == (TenantSiteAccess, Site):
            return QueryStub([(site_access, site)])
        raise AssertionError(f"Unexpected query models: {models}")

    db.query.side_effect = fake_query
    monkeypatch.setattr(group_service, "get_group", lambda group_id, db: group)
    monkeypatch.setattr(group_service, "_assert_company_scope", lambda company_id, current_user: None)

    rows = group_service.list_group_members(4, SimpleNamespace(), db)

    assert rows[0].tenant_id == 42
    assert rows[0].site_accesses[0].site_id == 2
    assert rows[0].site_accesses[0].site_name == "Head Office"
    assert rows[0].site_accesses[0].auto_assign_all_devices is True


def test_enrollment_validity_updates_tenant_global_dates():
    start = datetime(2026, 4, 7, tzinfo=timezone.utc)
    end = datetime(2027, 4, 7, tzinfo=timezone.utc)
    tenant = SimpleNamespace(global_access_from=None, global_access_till=None)

    enrollment_service._sync_tenant_global_validity(tenant, start, end)

    assert tenant.global_access_from == start
    assert tenant.global_access_till == end
