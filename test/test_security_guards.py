from __future__ import annotations

import sys
import uuid
from collections import defaultdict
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.services.access.schema import TenantSiteAccessCreate
from app.api.services.access import service as access_service
from app.api.services.auth import service as auth_service
from app.api.services.auth.schema import UserRegister
from app.api.services.device_mapping import service as mapping_service
from app.api.services.logs import route as logs_route
from database.models import AppUser, Company, Device, DeviceUserMapping, Site, Tenant, UserRole


def _eval_condition(item, condition) -> bool:
    attr = condition.left.key
    value = getattr(condition.right, "value", condition.right)
    operator_name = condition.operator.__name__
    current = getattr(item, attr)

    if isinstance(current, uuid.UUID) and isinstance(value, str):
        value = uuid.UUID(value)

    if operator_name == "eq":
        return current == value
    raise NotImplementedError(f"Unsupported operator: {operator_name}")


class FakeQuery:
    def __init__(self, items: list):
        self._items = list(items)

    def filter(self, *conditions):
        items = self._items
        for condition in conditions:
            items = [item for item in items if _eval_condition(item, condition)]
        return FakeQuery(items)

    def first(self):
        return self._items[0] if self._items else None


class FakeSession:
    def __init__(self):
        self.store: dict[type, list] = defaultdict(list)

    def add(self, obj):
        model = type(obj)
        if obj not in self.store[model]:
            self.store[model].append(obj)

    def query(self, model):
        return FakeQuery(self.store[model])


def _make_user(role: UserRole, company_id=None) -> AppUser:
    return AppUser(
        user_id=uuid.uuid4(),
        company_id=company_id or uuid.uuid4(),
        username=role.value,
        full_name=f"{role.value} user",
        password_hash="hash",
        role=role.value,
        is_active=True,
    )


def test_access_grant_rejects_cross_company_link():
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    current_user = _make_user(UserRole.company_admin, company_id=company_a)
    db = FakeSession()
    db.add(Tenant(tenant_id=1, company_id=company_a, full_name="Tenant A", is_active=True))
    db.add(Site(site_id=7, company_id=company_b, name="Site B", is_active=True))

    with pytest.raises(HTTPException) as exc_info:
        access_service.grant_site_access(
            TenantSiteAccessCreate(tenant_id=1, site_id=7),
            current_user,
            db,
        )

    assert exc_info.value.status_code == 400
    assert "different companies" in exc_info.value.detail


def test_device_mapping_scope_blocks_other_companies():
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    current_user = _make_user(UserRole.company_admin, company_id=company_b)
    db = FakeSession()
    db.add(Tenant(tenant_id=1, company_id=company_a, full_name="Tenant A", is_active=True))
    db.add(Device(device_id=9, company_id=company_a, device_serial_number="SER-9", vendor="Matrix"))
    db.add(DeviceUserMapping(mapping_id=5, tenant_id=1, device_id=9, matrix_user_id="1001"))

    with pytest.raises(HTTPException) as exc_info:
        mapping_service.get_mapping(5, db, current_user)

    assert exc_info.value.status_code == 403


def test_logs_diagnostic_requires_admin_role():
    current_user = _make_user(UserRole.staff)

    with pytest.raises(HTTPException) as exc_info:
        logs_route.diagnostic(device_id=1, db=object(), current_user=current_user)

    assert exc_info.value.status_code == 403


def test_register_user_generates_username_and_delegates_to_user_service(monkeypatch):
    company_id = uuid.uuid4()
    requested_company_id = uuid.uuid4()
    current_user = _make_user(UserRole.company_admin, company_id=company_id)
    db = FakeSession()
    db.add(Company(company_id=company_id, name="Acme", is_active=True))
    db.add(Company(company_id=requested_company_id, name="Other", is_active=True))

    captured = {}

    def fake_create_user(payload, actor, session):
        captured["payload"] = payload
        captured["actor"] = actor
        captured["session"] = session
        return AppUser(
            user_id=uuid.uuid4(),
            company_id=payload.company_id,
            username=payload.username,
            full_name=payload.full_name,
            password_hash="hash",
            role=payload.role.value,
            is_active=True,
        )

    monkeypatch.setattr(auth_service, "_generate_unique_username", lambda role, _: "STFABCDE")
    monkeypatch.setattr(auth_service, "create_user", fake_create_user)

    user = auth_service.register_user(
        UserRegister(company_id=requested_company_id, full_name="Jane Smith", password="Password123", role=UserRole.staff),
        current_user,
        db,
    )

    assert user.username == "STFABCDE"
    assert captured["payload"].company_id == company_id
    assert captured["payload"].username == "STFABCDE"
    assert captured["actor"] is current_user
    assert captured["session"] is db
