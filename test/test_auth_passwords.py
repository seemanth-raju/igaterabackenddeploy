from __future__ import annotations

import sys
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.services.auth import service as auth_service
from app.api.services.auth.schema import ChangePasswordRequest
from app.core.security import verify_password
from database.models import AppUser, AuthToken


def _eval_condition(item, condition) -> bool:
    attr = condition.left.key
    value = getattr(condition.right, "value", condition.right)
    operator_name = condition.operator.__name__
    current = getattr(item, attr)

    if operator_name == "eq":
        return current == value
    if operator_name == "is_":
        return current is value or current == value
    raise NotImplementedError(f"Unsupported operator: {operator_name}")


class FakeQuery:
    def __init__(self, items: list):
        self._items = list(items)

    def filter(self, *conditions):
        items = self._items
        for condition in conditions:
            items = [item for item in items if _eval_condition(item, condition)]
        return FakeQuery(items)

    def all(self):
        return list(self._items)


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


def _make_user(password: str) -> AppUser:
    return AppUser(
        user_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        username="alice",
        full_name="Alice Example",
        password_hash=auth_service.hash_password(password),
        is_active=True,
    )


def test_issue_tokens_persists_refresh_lifetime_but_returns_access_lifetime():
    db = FakeSession()
    user = _make_user("OldPassword123")

    before = datetime.now(UTC)
    response = auth_service._issue_tokens(user, db)
    after = datetime.now(UTC)

    assert len(db.store[AuthToken]) == 1
    token_row = db.store[AuthToken][0]

    assert response.expires_at >= before
    assert response.expires_at <= after + timedelta(hours=1)
    assert token_row.expires_at - response.expires_at > timedelta(days=1)


def test_change_password_revokes_existing_tokens_and_issues_new_pair():
    db = FakeSession()
    user = _make_user("OldPassword123")
    existing_token = AuthToken(
        user_id=user.user_id,
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=datetime.now(UTC) + timedelta(days=7),
        revoked=False,
    )
    db.add(existing_token)

    response = auth_service.change_password(
        user,
        ChangePasswordRequest(current_password="OldPassword123", new_password="NewPassword456"),
        db,
    )

    assert verify_password("NewPassword456", user.password_hash)
    assert not verify_password("OldPassword123", user.password_hash)
    assert existing_token.revoked is True

    active_tokens = [token for token in db.store[AuthToken] if token.revoked is False]
    assert len(active_tokens) == 1
    assert active_tokens[0].access_token == response.access_token
    assert active_tokens[0].refresh_token == response.refresh_token


def test_change_password_rejects_wrong_current_password():
    db = FakeSession()
    user = _make_user("OldPassword123")

    with pytest.raises(HTTPException) as exc_info:
        auth_service.change_password(
            user,
            ChangePasswordRequest(current_password="wrong-password", new_password="NewPassword456"),
            db,
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Current password is incorrect"
