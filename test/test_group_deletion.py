from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.services.groups import service as group_service
from app.api.services.tenants import enrollment as enrollment_service
from app.api.services.tenants import service as tenant_service


class QueryStub:
    def __init__(self, *, all_result=None, delete_result=0):
        self._all_result = all_result or []
        self._delete_result = delete_result
        self.delete_sync = None

    def filter(self, *args, **kwargs):
        return self

    def distinct(self):
        return self

    def all(self):
        return self._all_result

    def delete(self, synchronize_session=False):
        self.delete_sync = synchronize_session
        return self._delete_result


def test_delete_tenant_with_related_data_unenrolls_and_removes_logs_and_files(monkeypatch):
    handle, raw_path = tempfile.mkstemp(dir=ROOT)
    os.close(handle)
    credential_file = Path(raw_path)
    credential_file.write_bytes(b"fingerprint")

    tenant = SimpleNamespace(tenant_id=42)
    mappings = [SimpleNamespace(device_id=7), SimpleNamespace(device_id=9)]
    credential_query = QueryStub(all_result=[(str(credential_file),)])
    mapping_query = QueryStub(all_result=mappings)

    db = MagicMock()
    db.query.side_effect = [credential_query, mapping_query]

    monkeypatch.setattr(tenant_service, "get_tenant", lambda tenant_id, db: tenant)

    unenroll_calls: list[dict] = []

    def fake_unenroll_from_devices_bulk(*, tenant_id, device_ids, db, performed_by):
        unenroll_calls.append(
            {
                "tenant_id": tenant_id,
                "device_ids": device_ids,
                "performed_by": performed_by,
            }
        )
        return {"succeeded": len(device_ids), "failed": 0}

    monkeypatch.setattr(enrollment_service, "unenroll_from_devices_bulk", fake_unenroll_from_devices_bulk)

    try:
        tenant_service.delete_tenant_with_related_data(42, db, performed_by="user-1")
    finally:
        if credential_file.exists():
            credential_file.unlink()

    assert unenroll_calls == [
        {
            "tenant_id": 42,
            "device_ids": [7, 9],
            "performed_by": "user-1",
        }
    ]
    db.delete.assert_called_once_with(tenant)
    db.commit.assert_called_once()
    assert not credential_file.exists()


def test_delete_group_rejects_when_members_exist(monkeypatch):
    company_id = uuid.uuid4()
    current_user = SimpleNamespace(user_id="admin-1", company_id=company_id)
    group = SimpleNamespace(group_id=11, company_id=company_id)
    membership_query = QueryStub(all_result=[(42,), (51,)])

    db = MagicMock()
    db.query.side_effect = [membership_query]

    monkeypatch.setattr(group_service, "get_group", lambda group_id, db: group)
    monkeypatch.setattr(group_service, "_assert_company_scope", lambda company_id, current_user: None)

    try:
        group_service.delete_group(11, current_user, db)
        raise AssertionError("Expected delete_group to reject non-empty groups")
    except group_service.HTTPException as exc:
        assert exc.status_code == 400
        assert "still has users" in exc.detail

    db.delete.assert_not_called()
    db.commit.assert_not_called()


def test_delete_group_deletes_empty_group(monkeypatch):
    company_id = uuid.uuid4()
    current_user = SimpleNamespace(user_id="admin-1", company_id=company_id)
    group = SimpleNamespace(group_id=11, company_id=company_id)
    membership_query = QueryStub(all_result=[])

    db = MagicMock()
    db.query.side_effect = [membership_query]

    monkeypatch.setattr(group_service, "get_group", lambda group_id, db: group)
    monkeypatch.setattr(group_service, "_assert_company_scope", lambda company_id, current_user: None)

    group_service.delete_group(11, current_user, db)

    db.delete.assert_called_once_with(group)
    db.commit.assert_called_once()
