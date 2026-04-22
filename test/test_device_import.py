from __future__ import annotations

import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import shutil
from uuid import uuid4

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.services.devices.schema import DeviceImportRequest
from app.api.services.devices import service as devices_service
from app.api.services.push.commands import push_create_user
from app.services.matrix.device_client import MatrixDeviceClient
from database.models import (
    AppUser,
    Company,
    Credential,
    Device,
    DeviceConfig,
    DeviceUserMapping,
    Site,
    Tenant,
    TenantDeviceAccess,
    TenantGroup,
    TenantSiteAccess,
    UserRole,
)


def _eval_condition(item, condition) -> bool:
    attr = condition.left.key
    value = getattr(condition.right, "value", None)
    operator_name = condition.operator.__name__
    current = getattr(item, attr, None)
    if operator_name == "eq":
        return current == value
    if operator_name == "ne":
        return current != value
    if operator_name == "is_":
        return current is value
    if operator_name == "is_not":
        return current is not value
    raise NotImplementedError(f"Unsupported operator: {operator_name}")


class FakeQuery:
    def __init__(self, items: list):
        self._items = list(items)

    def filter(self, *conditions):
        items = self._items
        for cond in conditions:
            items = [item for item in items if _eval_condition(item, cond)]
        return FakeQuery(items)

    def first(self):
        return self._items[0] if self._items else None

    def all(self):
        return list(self._items)

    def update(self, values: dict, synchronize_session=False):
        for item in self._items:
            for key, value in values.items():
                setattr(item, key, value)
        return len(self._items)


class FakeSession:
    def __init__(self):
        self._store: dict[type, list] = defaultdict(list)
        self._ids: dict[type, int] = defaultdict(int)

    def _next_id(self, model: type) -> int:
        self._ids[model] += 1
        return self._ids[model]

    def add(self, obj):
        if obj not in self._store[type(obj)]:
            self._store[type(obj)].append(obj)
        self._apply_defaults(obj)

    def query(self, model):
        return FakeQuery(self._store[model])

    def commit(self):
        self.flush()

    def rollback(self):
        pass

    def flush(self):
        for items in self._store.values():
            for obj in items:
                self._apply_defaults(obj)

    def refresh(self, obj):
        self._apply_defaults(obj)

    def _apply_defaults(self, obj):
        if isinstance(obj, Device):
            if obj.device_id is None:
                obj.device_id = self._next_id(Device)
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)
            if obj.config is None:
                obj.config = {}
        elif isinstance(obj, Tenant):
            if obj.tenant_id is None:
                obj.tenant_id = self._next_id(Tenant)
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)
        elif isinstance(obj, TenantGroup):
            if obj.group_id is None:
                obj.group_id = self._next_id(TenantGroup)
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)
            if obj.updated_at is None:
                obj.updated_at = datetime.now(timezone.utc)
        elif isinstance(obj, DeviceUserMapping):
            if obj.mapping_id is None:
                obj.mapping_id = self._next_id(DeviceUserMapping)
        elif isinstance(obj, TenantSiteAccess):
            if obj.site_access_id is None:
                obj.site_access_id = self._next_id(TenantSiteAccess)
        elif isinstance(obj, TenantDeviceAccess):
            if obj.device_access_id is None:
                obj.device_access_id = self._next_id(TenantDeviceAccess)
        elif isinstance(obj, DeviceConfig):
            if obj.config_entry_id is None:
                obj.config_entry_id = self._next_id(DeviceConfig)
            if obj.params is None:
                obj.params = {}
            if obj.status is None:
                obj.status = "pending"
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)
        elif isinstance(obj, Credential):
            if obj.credential_id is None:
                obj.credential_id = self._next_id(Credential)
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)


class FakeMatrixClient:
    def ping(self) -> bool:
        return True

    def get_user_count(self) -> int:
        return 2

    def list_user_profiles(self, reported_total: int | None = None) -> list[dict]:
        return [
            {
                "user_id": "26",
                "user_index": "1",
                "ref_user_id": "26",
                "name": "seemanth",
                "user_active": "1",
                "validity_enable": "1",
                "validity_date_dd": "28",
                "validity_date_mm": "5",
                "validity_date_yyyy": "2026",
            },
            {
                "user_id": "33",
                "user_index": "2",
                "ref_user_id": "33",
                "name": "test",
                "user_active": "1",
                "validity_enable": "1",
                "validity_date_dd": "8",
                "validity_date_mm": "7",
                "validity_date_yyyy": "2026",
            },
        ]

    def list_fingerprint_templates(self, user_id: str, max_finger_index: int = 10) -> dict[int, bytes]:
        return {}


class FakeMatrixClientWithoutCount(FakeMatrixClient):
    def get_user_count(self) -> int:
        return -1


class FakeMatrixClientWithFingerprints(FakeMatrixClient):
    def list_fingerprint_templates(self, user_id: str, max_finger_index: int = 10) -> dict[int, bytes]:
        if user_id == "26":
            return {1: b"\x00\x01\x02" * 120}
        if user_id == "33":
            return {1: b"\x03\x04\x05" * 120}
        return {}


def test_import_enrollment_device_creates_device_group_tenants_and_mappings(monkeypatch):
    db = FakeSession()
    company_id = uuid4()
    current_user = AppUser(
        user_id=uuid4(),
        company_id=company_id,
        role=UserRole.company_admin.value,
        username="admin",
        full_name="Admin",
        password_hash="x",
        is_active=True,
    )

    db.add(Company(company_id=company_id, name="Acme", is_active=True))
    db.add(Site(site_id=7, company_id=company_id, name="HQ", timezone="UTC", is_active=True))
    group = TenantGroup(company_id=company_id, name="Imported", code="imported", is_active=True, is_default=False)
    db.add(group)

    monkeypatch.setattr(devices_service, "_build_matrix_client", lambda payload: FakeMatrixClient())
    monkeypatch.setattr(devices_service, "encrypt_password", lambda value: f"enc:{value}")

    payload = DeviceImportRequest(
        ip_address="192.168.1.201",
        mac_address="aa-bb-cc-dd-ee-ff",
        group_id=group.group_id,
        api_password="12345",
        site_id=7,
    )

    result = devices_service.import_enrollment_device(payload, current_user, db)

    assert result["device_created"] is True
    assert result["reported_user_count"] == 2
    assert result["imported_user_count"] == 2
    assert result["created_tenants"] == 2
    assert result["created_mappings"] == 2
    assert result["created_device_accesses"] == 2
    assert result["created_site_accesses"] == 2
    assert result["warnings"] == []

    device = result["device"]
    assert device.mac_address == "AA:BB:CC:DD:EE:FF"
    assert device.device_serial_number == "AABBCCDDEEFF"
    assert device.api_password_encrypted == "enc:12345"

    selected_group = result["group"]
    assert selected_group.group_id == group.group_id
    assert selected_group.name == "Imported"

    tenants = db.query(Tenant).all()
    assert {tenant.external_id for tenant in tenants} == {"26", "33"}
    assert {tenant.group_id for tenant in tenants} == {group.group_id}

    mappings = db.query(DeviceUserMapping).all()
    assert {mapping.matrix_user_id for mapping in mappings} == {"26", "33"}
    assert all(mapping.device_id == device.device_id for mapping in mappings)
    assert all(mapping.is_synced is True for mapping in mappings)

    assert len(db.query(TenantSiteAccess).all()) == 2
    assert len(db.query(TenantDeviceAccess).all()) == 2


def test_import_enrollment_device_falls_back_when_count_endpoint_is_unavailable(monkeypatch):
    db = FakeSession()
    company_id = uuid4()
    current_user = AppUser(
        user_id=uuid4(),
        company_id=company_id,
        role=UserRole.company_admin.value,
        username="admin",
        full_name="Admin",
        password_hash="x",
        is_active=True,
    )

    db.add(Company(company_id=company_id, name="Acme", is_active=True))
    db.add(Site(site_id=7, company_id=company_id, name="HQ", timezone="UTC", is_active=True))
    group = TenantGroup(company_id=company_id, name="Imported", code="imported", is_active=True, is_default=False)
    db.add(group)

    monkeypatch.setattr(devices_service, "_build_matrix_client", lambda payload: FakeMatrixClientWithoutCount())
    monkeypatch.setattr(devices_service, "encrypt_password", lambda value: f"enc:{value}")

    payload = DeviceImportRequest(
        ip_address="192.168.1.201",
        mac_address="aa-bb-cc-dd-ee-ff",
        group_id=group.group_id,
        api_password="12345",
        site_id=7,
    )

    result = devices_service.import_enrollment_device(payload, current_user, db)

    assert result["reported_user_count"] == 2
    assert result["imported_user_count"] == 2
    assert result["created_tenants"] == 2
    assert (
        "Device user count endpoint was unavailable; users were imported by scanning device records."
        in result["warnings"]
    )


def test_import_enrollment_device_imports_fingerprints(monkeypatch):
    db = FakeSession()
    company_id = uuid4()
    current_user = AppUser(
        user_id=uuid4(),
        company_id=company_id,
        role=UserRole.company_admin.value,
        username="admin",
        full_name="Admin",
        password_hash="x",
        is_active=True,
    )

    db.add(Company(company_id=company_id, name="Acme", is_active=True))
    db.add(Site(site_id=7, company_id=company_id, name="HQ", timezone="UTC", is_active=True))
    group = TenantGroup(company_id=company_id, name="Imported", code="imported", is_active=True, is_default=False)
    db.add(group)

    monkeypatch.setattr(devices_service, "_build_matrix_client", lambda payload: FakeMatrixClientWithFingerprints())
    monkeypatch.setattr(devices_service, "encrypt_password", lambda value: f"enc:{value}")
    temp_dir = ROOT / "test-artifacts" / "device-import-fingerprints"
    temp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(devices_service, "get_fingerprint_storage_path", lambda: temp_dir)

    payload = DeviceImportRequest(
        ip_address="192.168.1.201",
        mac_address="aa-bb-cc-dd-ee-ff",
        group_id=group.group_id,
        api_password="12345",
        site_id=7,
    )

    try:
        result = devices_service.import_enrollment_device(payload, current_user, db)

        assert result["imported_fingerprint_count"] == 2
        assert result["users_with_fingerprints"] == 2
        assert [user["finger_count"] for user in result["users"]] == [1, 1]

        credentials = db.query(Credential).all()
        assert len(credentials) == 2
        assert {credential.tenant_id for credential in credentials} == {1, 2}
        assert all(credential.type == "finger" for credential in credentials)
        assert all(Path(credential.file_path).exists() for credential in credentials)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_anonymous_upload_import_uses_single_active_company(monkeypatch):
    db = FakeSession()
    company_id = uuid4()
    db.add(Company(company_id=company_id, name="Acme", is_active=True))

    monkeypatch.setattr(
        devices_service.settings,
        "allow_anonymous_migration_uploads",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        devices_service.settings,
        "anonymous_migration_default_company_id",
        None,
        raising=False,
    )

    resolved = devices_service.resolve_upload_import_company_id(None, None, db)

    assert resolved == company_id


def test_anonymous_upload_import_requires_company_id_with_multiple_companies(monkeypatch):
    db = FakeSession()
    db.add(Company(company_id=uuid4(), name="Acme", is_active=True))
    db.add(Company(company_id=uuid4(), name="Beta", is_active=True))

    monkeypatch.setattr(
        devices_service.settings,
        "allow_anonymous_migration_uploads",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        devices_service.settings,
        "anonymous_migration_default_company_id",
        None,
        raising=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        devices_service.resolve_upload_import_company_id(None, None, db)

    assert exc_info.value.status_code == 400
    assert "company_id is required" in exc_info.value.detail


def test_push_create_user_reuses_existing_matrix_user_id_on_other_devices():
    db = FakeSession()
    tenant = Tenant(
        tenant_id=42,
        company_id=uuid4(),
        full_name="Alice",
        is_active=True,
        is_access_enabled=True,
    )
    db.add(tenant)
    db.add(DeviceUserMapping(tenant_id=42, device_id=1, matrix_user_id="26", is_synced=True))

    queued = push_create_user(db, device_id=2, tenant=tenant, correlation_id="sync-42")

    assert queued.params["user-id"] == "26"
    assert queued.params["ref-user-id"] == "26"


def test_matrix_client_list_user_profiles_stops_when_reported_count_is_collected(monkeypatch):
    client = MatrixDeviceClient("192.168.1.10", "admin", password="secret")
    calls: list[int] = []

    monkeypatch.setattr(client, "get_user_count", lambda: 2)

    def fake_get_user_by_index(index: int) -> dict | None:
        calls.append(index)
        if index == 1:
            return {"user_id": "26", "ref_user_id": "26", "name": "alpha"}
        if index == 2:
            return {"user_id": "33", "ref_user_id": "33", "name": "beta"}
        return None

    monkeypatch.setattr(client, "get_user_by_index", fake_get_user_by_index)

    profiles = client.list_user_profiles()

    assert [profile["user_id"] for profile in profiles] == ["26", "33"]
    assert calls == [1, 2]


def test_matrix_client_list_user_profiles_falls_back_to_index_scan_without_count(monkeypatch):
    client = MatrixDeviceClient("192.168.1.10", "admin", password="secret")
    calls: list[int] = []

    monkeypatch.setattr(client, "get_user_count", lambda: -1)

    def fake_get_user_by_index(index: int) -> dict | None:
        calls.append(index)
        if index == 1:
            return {"user_id": "26", "ref_user_id": "26", "name": "alpha"}
        if index == 2:
            return {"user_id": "33", "ref_user_id": "33", "name": "beta"}
        return None

    monkeypatch.setattr(client, "get_user_by_index", fake_get_user_by_index)

    profiles = client.list_user_profiles()

    assert [profile["user_id"] for profile in profiles] == ["26", "33"]
    assert calls[:4] == [1, 2, 3, 4]
    assert len(calls) == 53


def test_matrix_client_list_user_profiles_falls_back_to_user_id_scan(monkeypatch):
    client = MatrixDeviceClient("192.168.1.10", "admin", password="secret")
    index_calls: list[int] = []
    user_id_calls: list[int] = []

    monkeypatch.setattr(client, "get_user_count", lambda: -1)

    def fake_get_user_by_index(index: int) -> dict | None:
        index_calls.append(index)
        return None

    def fake_scan_profiles_by_user_id(max_user_id: int = 5000, stop_after_misses: int = 250) -> list[dict]:
        user_id_calls.extend([1, 2, 3])
        return [
            {"user_id": "26", "ref_user_id": "26", "name": "alpha"},
            {"user_id": "33", "ref_user_id": "33", "name": "beta"},
        ]

    monkeypatch.setattr(client, "get_user_by_index", fake_get_user_by_index)
    monkeypatch.setattr(client, "_scan_profiles_by_user_id", fake_scan_profiles_by_user_id)

    profiles = client.list_user_profiles()

    assert [profile["user_id"] for profile in profiles] == ["26", "33"]
    assert len(index_calls) == 51
    assert user_id_calls == [1, 2, 3]
