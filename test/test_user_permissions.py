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

from app.api.services.users.schema import UserUpdate
from app.api.services.users import service as user_service
from database.models import AppUser, UserRole


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

    def commit(self):
        return None

    def refresh(self, obj):
        return None


def _make_user(role: UserRole, company_id, *, user_id=None, username=None) -> AppUser:
    return AppUser(
        user_id=user_id or uuid.uuid4(),
        company_id=company_id,
        username=username or role.value,
        full_name=f"{role.value} user",
        password_hash="hash",
        role=role.value,
        is_active=True,
    )


def test_non_admin_can_only_fetch_self():
    company_id = uuid.uuid4()
    self_user = _make_user(UserRole.viewer, company_id, username="self")
    other_user = _make_user(UserRole.staff, company_id, username="other")
    db = FakeSession()
    db.add(self_user)
    db.add(other_user)

    result = user_service.get_user_for_request(str(self_user.user_id), self_user, db)
    assert result.user_id == self_user.user_id

    with pytest.raises(HTTPException) as exc_info:
        user_service.get_user_for_request(str(other_user.user_id), self_user, db)

    assert exc_info.value.status_code == 403


def test_company_admin_cannot_update_super_admin():
    company_id = uuid.uuid4()
    admin = _make_user(UserRole.company_admin, company_id, username="admin")
    target = _make_user(UserRole.super_admin, company_id, username="super")
    db = FakeSession()
    db.add(admin)
    db.add(target)

    with pytest.raises(HTTPException) as exc_info:
        user_service.update_user(
            str(target.user_id),
            UserUpdate(full_name="Updated Name"),
            admin,
            db,
        )

    assert exc_info.value.status_code == 403


def test_company_admin_can_update_staff_in_same_company():
    company_id = uuid.uuid4()
    admin = _make_user(UserRole.company_admin, company_id, username="admin")
    target = _make_user(UserRole.staff, company_id, username="staff")
    db = FakeSession()
    db.add(admin)
    db.add(target)

    updated = user_service.update_user(
        str(target.user_id),
        UserUpdate(full_name="Updated Staff"),
        admin,
        db,
    )

    assert updated.full_name == "Updated Staff"
