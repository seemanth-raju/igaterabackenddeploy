from __future__ import annotations

import asyncio
import hashlib
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.services.push import route as push_route
from app.api.services.logs.service import sync_logs_from_device
from app.api.services.push.route import (
    QueueConfigRequest,
    device_get_config,
    device_login,
    device_poll,
    device_set_event,
    device_update_config,
    queue_config_route,
)
from app.services import log_sync_worker
from app.core import schema_guard
from database.models import AccessEvent, Device, DeviceConfig


def parse_text_response(body: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in body.strip().split():
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


def make_request(path: str, params: dict[str, str]) -> Request:
    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": urlencode(params).encode(),
        "headers": [],
        "client": ("testclient", 12345),
        "server": ("testserver", 80),
    }
    return Request(scope, receive)


def _eval_condition(item, condition) -> bool:
    attr = condition.left.key
    value = getattr(condition.right, "value", None)
    operator_name = condition.operator.__name__
    current = getattr(item, attr)

    if operator_name == "eq":
        return current == value
    if operator_name == "ne":
        return current != value
    if operator_name == "is_":
        return current is value
    if operator_name == "is_not":
        return current is not value
    if operator_name == "ilike_op":
        if current is None or value is None:
            return False
        pattern = str(value).strip("%").lower()
        return pattern in str(current).lower()
    raise NotImplementedError(f"Unsupported operator: {operator_name}")


def _order_clause_key(ordering) -> tuple[str, bool]:
    if hasattr(ordering, "element"):
        return ordering.element.key, getattr(ordering.modifier, "__name__", "") == "desc_op"
    return ordering.key, False


class FakeQuery:
    def __init__(self, items: list):
        self._items = list(items)

    def filter(self, *conditions):
        items = self._items
        for condition in conditions:
            items = [item for item in items if _eval_condition(item, condition)]
        return FakeQuery(items)

    def order_by(self, *orderings):
        items = list(self._items)
        for ordering in reversed(orderings):
            key, reverse = _order_clause_key(ordering)
            items.sort(
                key=lambda item: getattr(item, key) if getattr(item, key) is not None else datetime.min.replace(tzinfo=timezone.utc),
                reverse=reverse,
            )
        return FakeQuery(items)

    def first(self):
        return self._items[0] if self._items else None

    def all(self):
        return list(self._items)

    def limit(self, count: int):
        return FakeQuery(self._items[:count])

    def count(self):
        return len(self._items)


class FakeSession:
    def __init__(self):
        self._store: dict[type, list] = defaultdict(list)
        self._ids: dict[type, int] = defaultdict(int)

    def add(self, obj):
        model = type(obj)
        if obj not in self._store[model]:
            self._store[model].append(obj)
        self._apply_defaults(obj)

    def query(self, model):
        return FakeQuery(self._store[model])

    def commit(self):
        return None

    def rollback(self):
        return None

    def flush(self):
        return None

    def refresh(self, obj):
        self._apply_defaults(obj)

    def close(self):
        return None

    def _next_id(self, model: type) -> int:
        self._ids[model] += 1
        return self._ids[model]

    def _apply_defaults(self, obj):
        if isinstance(obj, Device):
            if obj.config is None:
                obj.config = {}
            if obj.status is None:
                obj.status = "offline"
            if obj.communication_mode is None:
                obj.communication_mode = "direct"
            if obj.is_active is None:
                obj.is_active = True
        elif isinstance(obj, DeviceConfig):
            if obj.config_entry_id is None:
                obj.config_entry_id = self._next_id(DeviceConfig)
            if obj.params is None:
                obj.params = {}
            if obj.status is None:
                obj.status = "pending"
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)
        elif isinstance(obj, AccessEvent):
            if obj.event_id is None:
                obj.event_id = self._next_id(AccessEvent)
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)


class FakeInspector:
    def __init__(self, tables):
        self._tables = tables

    def has_table(self, table_name, schema=None):
        return table_name in self._tables

    def get_columns(self, table_name, schema=None):
        return [{"name": column} for column in self._tables[table_name]]


def test_push_config_lifecycle():
    push_route._last_request.clear()

    db = FakeSession()
    secret = "testpush123"
    device = Device(
        device_id=1,
        company_id=None,
        site_id=None,
        device_serial_number="001B0912CA49",
        vendor="Matrix",
        model_name="COSEC",
        ip_address="192.168.1.201",
        mac_address="00:1B:09:12:CA:49",
        api_username="admin",
        api_password_encrypted=None,
        api_port=80,
        use_https=False,
        is_active=True,
        communication_mode="push",
        push_token_hash=hashlib.sha256(secret.encode()).hexdigest(),
        status="offline",
        last_heartbeat=None,
        config={},
        created_at=datetime.now(timezone.utc),
    )
    db.add(device)

    queued = queue_config_route(
        QueueConfigRequest(
            device_id=1,
            config_id=10,
            params={
                "ref-user-id": "101",
                "user-id": "101",
                "name": "TEST101",
                "user-active": "1",
                "validity-enable": "0",
            },
            correlation_id="manual-user-101",
        ),
        db=db,
    )

    assert queued["status"] == "pending"
    assert queued["correlation_id"] == "manual-user-101"

    login_response = asyncio.run(
        device_login(
            make_request("/push/login", {
                "device-type": "4",
                "serial-no": "001B0912CA49",
                "password": secret,
            }),
            db=db,
        )
    )
    login_data = parse_text_response(login_response.body.decode())
    assert login_data["status"] == "1"
    assert login_data["poll-interval"] == "5"

    poll_response = asyncio.run(
        device_poll(
            make_request("/push/poll", {
                "device-type": "4",
                "serial-no": "001B0912CA49",
                "password": secret,
            }),
            db=db,
        )
    )
    poll_data = parse_text_response(poll_response.body.decode())
    assert poll_data["cnfg-avlbl"] == "1"

    getcfg_response = asyncio.run(
        device_get_config(
            make_request("/push/getconfig", {
                "device-type": "4",
                "serial-no": "001B0912CA49",
                "password": secret,
            }),
            db=db,
        )
    )
    getcfg_data = parse_text_response(getcfg_response.body.decode())
    assert getcfg_data["config-id"] == "10"
    assert getcfg_data["user-id"] == "101"

    cfg = db.query(DeviceConfig).first()
    assert cfg.status == "sent"

    update_response = asyncio.run(
        device_update_config(
            make_request("/push/updateconfig", {
                "device-type": "4",
                "serial-no": "001B0912CA49",
                "password": secret,
                "config-id": "10",
                "status": "1",
            }),
            db=db,
        )
    )
    update_data = parse_text_response(update_response.body.decode())
    assert update_data["status"] == "1"
    assert update_data["cnfg-avlbl"] == "0"

    cfg = db.query(DeviceConfig).first()
    assert cfg.status == "success"
    assert device.config["last_user_config"]["status"] == "success"
    assert device.config["last_user_config"]["user_id"] == "101"


def test_find_device_matches_lowercase_serial_number():
    db = FakeSession()
    device = Device(
        device_id=1,
        company_id=None,
        site_id=None,
        device_serial_number="001B0912CA49",
        vendor="Matrix",
        model_name="COSEC",
        ip_address="192.168.1.201",
        mac_address=None,
        api_username="admin",
        api_password_encrypted=None,
        api_port=80,
        use_https=False,
        is_active=True,
        communication_mode="push",
        status="offline",
        last_heartbeat=None,
        config={},
        created_at=datetime.now(timezone.utc),
    )
    db.add(device)

    found = push_route._find_device("001b0912ca49", db)

    assert found is device


def test_push_setevent_ignores_duplicate_event():
    push_route._last_request.clear()

    db = FakeSession()
    device = Device(
        device_id=1,
        company_id=None,
        site_id=None,
        device_serial_number="001B0912CA49",
        vendor="Matrix",
        model_name="COSEC",
        ip_address="192.168.1.201",
        mac_address="00:1B:09:12:CA:49",
        api_username="admin",
        api_password_encrypted=None,
        api_port=80,
        use_https=False,
        is_active=True,
        communication_mode="push",
        status="online",
        last_heartbeat=None,
        config={},
        created_at=datetime.now(timezone.utc),
    )
    db.add(device)
    db.add(
        AccessEvent(
            company_id=None,
            device_id=1,
            tenant_id=None,
            device_seq_number=22,
            device_rollover_count=0,
            cosec_event_id=405,
            event_type="enrollment",
            event_time=datetime.now(timezone.utc),
            direction="IN",
            auth_used=None,
            access_granted=False,
            raw_data={"detail_1": "37"},
        )
    )

    response = asyncio.run(
        device_set_event(
            make_request(
                "/push/setevent",
                {
                    "device-type": "7",
                    "serial-no": "001B0912CA49",
                    "seq-no": "22",
                    "roll-over-count": "0",
                    "evt_id": "405",
                    "date-dd": "19",
                    "date-mm": "4",
                    "date-yyyy": "2026",
                    "time-hh": "19",
                    "time-mm": "15",
                    "time-ss": "27",
                    "field-1": "37",
                    "field-2": "9",
                    "field-3": "0",
                    "field-4": "44",
                    "field-5": "",
                },
            ),
            db=db,
        )
    )

    data = parse_text_response(response.body.decode())
    assert data["status"] == "1"
    assert data["next-seq-no"] == "23"
    assert len(db.query(AccessEvent).all()) == 1


def test_sync_logs_from_device_skips_push_mode(monkeypatch):
    db = FakeSession()
    device = Device(
        device_id=1,
        company_id=None,
        site_id=None,
        device_serial_number="001B0912CA49",
        vendor="Matrix",
        model_name="COSEC",
        ip_address="192.168.1.201",
        mac_address="00:1B:09:12:CA:49",
        api_username="admin",
        api_password_encrypted=None,
        api_port=80,
        use_https=False,
        is_active=True,
        communication_mode="push",
        status="online",
        last_heartbeat=None,
        config={},
        created_at=datetime.now(timezone.utc),
    )
    db.add(device)

    class UnexpectedClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("push-mode devices should not use direct Matrix log sync")

    import app.services.matrix as matrix_mod

    monkeypatch.setattr(matrix_mod, "MatrixDeviceClient", UnexpectedClient)

    result = sync_logs_from_device(device_id=1, db=db)

    assert result["device_id"] == 1
    assert result["fetched"] == 0
    assert result["inserted"] == 0
    assert result["skipped"] == 0


def test_load_device_ids_skips_push_devices(monkeypatch):
    db = FakeSession()
    db.add(
        Device(
            device_id=1,
            company_id=None,
            site_id=None,
            device_serial_number="DIRECT01",
            vendor="Matrix",
            model_name="COSEC",
            ip_address="192.168.1.200",
            mac_address="00:11:22:33:44:55",
            api_username="admin",
            api_password_encrypted=None,
            api_port=80,
            use_https=False,
            is_active=True,
            communication_mode="direct",
            status="offline",
            last_heartbeat=None,
            config={},
            created_at=datetime.now(timezone.utc),
        )
    )
    db.add(
        Device(
            device_id=2,
            company_id=None,
            site_id=None,
            device_serial_number="PUSH01",
            vendor="Matrix",
            model_name="COSEC",
            ip_address="192.168.1.201",
            mac_address="66:77:88:99:AA:BB",
            api_username="admin",
            api_password_encrypted=None,
            api_port=80,
            use_https=False,
            is_active=True,
            communication_mode="push",
            status="online",
            last_heartbeat=None,
            config={},
            created_at=datetime.now(timezone.utc),
        )
    )

    monkeypatch.setattr(log_sync_worker, "SessionLocal", lambda: db)

    assert log_sync_worker._load_device_ids() == [(1, None)]


def test_assert_required_schema_applies_runtime_push_patches(monkeypatch):
    executed: list[str] = []
    create_all_calls: list[list[str]] = []

    class FakeConnection:
        def execute(self, statement):
            executed.append(str(statement))

    class FakeBegin:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    pre_tables = {
        "company": schema_guard.REQUIRED_SCHEMA["company"],
        "app_user": schema_guard.REQUIRED_SCHEMA["app_user"],
        "auth_token": schema_guard.REQUIRED_SCHEMA["auth_token"],
        "site": schema_guard.REQUIRED_SCHEMA["site"],
        "tenant": schema_guard.REQUIRED_SCHEMA["tenant"],
        "tenant_group": schema_guard.REQUIRED_SCHEMA["tenant_group"],
        "device": schema_guard.REQUIRED_SCHEMA["device"] - {"communication_mode", "push_token_hash"},
    }
    post_tables = {
        **pre_tables,
        "device": schema_guard.REQUIRED_SCHEMA["device"],
        "device_command": schema_guard.REQUIRED_SCHEMA["device_command"],
        "device_config": schema_guard.REQUIRED_SCHEMA["device_config"],
    }

    inspectors = iter([FakeInspector(pre_tables), FakeInspector(post_tables)])
    monkeypatch.setattr(schema_guard, "inspect", lambda engine: next(inspectors))
    monkeypatch.setattr(
        schema_guard.Base.metadata,
        "create_all",
        lambda bind, tables, checkfirst=True: create_all_calls.append([table.name for table in tables]),
    )

    schema_guard.assert_required_schema(FakeEngine())

    assert any("ALTER TABLE public.device ADD COLUMN IF NOT EXISTS communication_mode" in stmt for stmt in executed)
    assert any("ALTER TABLE public.device ADD COLUMN IF NOT EXISTS push_token_hash" in stmt for stmt in executed)
    assert create_all_calls
    assert "device_command" in create_all_calls[0]
    assert "device_config" in create_all_calls[0]


def test_assert_required_schema_patches_legacy_push_queue_tables(monkeypatch):
    executed: list[str] = []

    class FakeConnection:
        def execute(self, statement):
            executed.append(str(statement))

    class FakeBegin:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    legacy_tables = {
        "company": schema_guard.REQUIRED_SCHEMA["company"],
        "app_user": schema_guard.REQUIRED_SCHEMA["app_user"],
        "auth_token": schema_guard.REQUIRED_SCHEMA["auth_token"],
        "site": schema_guard.REQUIRED_SCHEMA["site"],
        "tenant": schema_guard.REQUIRED_SCHEMA["tenant"],
        "tenant_group": schema_guard.REQUIRED_SCHEMA["tenant_group"],
        "device": schema_guard.REQUIRED_SCHEMA["device"] - {"communication_mode", "push_token_hash"},
        "device_command": schema_guard.REQUIRED_SCHEMA["device_command"] - {"correlation_id"},
        "device_config": schema_guard.REQUIRED_SCHEMA["device_config"] - {"correlation_id"},
    }

    patched_tables = {
        **legacy_tables,
        "device": schema_guard.REQUIRED_SCHEMA["device"],
        "device_command": schema_guard.REQUIRED_SCHEMA["device_command"],
        "device_config": schema_guard.REQUIRED_SCHEMA["device_config"],
    }
    inspectors = iter([FakeInspector(legacy_tables), FakeInspector(patched_tables)])
    monkeypatch.setattr(schema_guard, "inspect", lambda engine: next(inspectors))
    monkeypatch.setattr(
        schema_guard.Base.metadata,
        "create_all",
        lambda bind, tables, checkfirst=True: None,
    )

    schema_guard.assert_required_schema(FakeEngine())

    assert any("ALTER TABLE public.device_command ADD COLUMN IF NOT EXISTS correlation_id" in stmt for stmt in executed)
    assert any("ALTER TABLE public.device_config ADD COLUMN IF NOT EXISTS correlation_id" in stmt for stmt in executed)
    assert any("CREATE INDEX IF NOT EXISTS idx_devcmd_correlation" in stmt for stmt in executed)
    assert any("CREATE INDEX IF NOT EXISTS idx_devcfg_correlation" in stmt for stmt in executed)
