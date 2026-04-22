"""Integration test: full push-mode enrollment cycle.

Simulates the complete flow:
  1. Frontend queues capture-fingerprint (creates user config + enroll command)
  2. Device polls → gets config → updateconfig (user created)
  3. Device polls → gets cmd (ENROLL) → updatecmd success (finger scanned)
  4. Server callback auto-queues GET_CREDENTIAL
  5. Device polls → gets cmd (GET_CREDENTIAL) → updatecmd with base64 template
  6. Server callback saves Credential + marks mapping synced
  7. Frontend polls enrollment-status → status=success
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.services.push import route as push_route
from app.api.services.push.commands import push_create_user, push_enroll_credential
from app.api.services.push.route import (
    device_get_command,
    device_get_config,
    device_login,
    device_poll,
    device_update_command,
    device_update_config,
    get_operation_status,
)
from database.models import (
    Credential,
    Device,
    DeviceCommand,
    DeviceConfig,
    DeviceUserMapping,
    Tenant,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def parse_text_response(body: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in body.strip().split():
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


def make_request(path: str, params: dict) -> Request:
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


# ---------------------------------------------------------------------------
# Minimal in-memory DB
# ---------------------------------------------------------------------------


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
        for cond in conditions:
            items = [item for item in items if _eval_condition(item, cond)]
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

    def limit(self, n: int):
        return FakeQuery(self._items[:n])

    def count(self):
        return len(self._items)


class FakeSession:
    def __init__(self):
        self._store: dict[type, list] = defaultdict(list)
        self._ids: dict[type, int] = defaultdict(int)
        self.fingerprint_write_path: str | None = None  # intercept file writes

    def _next_id(self, model: type) -> int:
        self._ids[model] += 1
        return self._ids[model]

    def add(self, obj):
        if obj not in self._store[type(obj)]:
            self._store[type(obj)].append(obj)
        self._apply_defaults(obj)

    def query(self, model):
        return FakeQuery(self._store[model])

    def delete(self, obj):
        self._store[type(obj)] = [o for o in self._store[type(obj)] if o is not obj]

    def commit(self):
        pass

    def rollback(self):
        pass

    def flush(self):
        self._auto_id_all()

    def refresh(self, obj):
        self._apply_defaults(obj)

    def _auto_id_all(self):
        for model, items in self._store.items():
            for obj in items:
                self._apply_defaults(obj)

    def _apply_defaults(self, obj):
        if isinstance(obj, Device):
            if obj.config is None:
                obj.config = {}
            if obj.status is None:
                obj.status = "offline"
            if obj.communication_mode is None:
                obj.communication_mode = "direct"
        elif isinstance(obj, DeviceConfig):
            if obj.config_entry_id is None:
                obj.config_entry_id = self._next_id(DeviceConfig)
            if obj.params is None:
                obj.params = {}
            if obj.status is None:
                obj.status = "pending"
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)
        elif isinstance(obj, DeviceCommand):
            if obj.command_id is None:
                obj.command_id = self._next_id(DeviceCommand)
            if obj.params is None:
                obj.params = {}
            if obj.status is None:
                obj.status = "pending"
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)
        elif isinstance(obj, DeviceUserMapping):
            if obj.mapping_id is None:
                obj.mapping_id = self._next_id(DeviceUserMapping)
        elif isinstance(obj, Credential):
            if obj.credential_id is None:
                obj.credential_id = self._next_id(Credential)
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Full enrollment cycle test
# ---------------------------------------------------------------------------


def test_full_push_enrollment_cycle(tmp_path, monkeypatch):
    """Test the complete push enrollment flow end-to-end (no real DB, no file I/O)."""
    push_route._last_request.clear()

    db = FakeSession()

    # Set up: push-mode device with a secret token
    secret = "enrollsecret42"
    device = Device(
        device_id=1,
        company_id=None,
        site_id=None,
        device_serial_number="AABBCCDDEEFF",
        vendor="Matrix",
        model_name="COSEC ARGO",
        ip_address=None,
        mac_address="AA:BB:CC:DD:EE:FF",
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

    # Set up: tenant
    tenant = Tenant(
        tenant_id=42,
        company_id=None,
        full_name="Alice",
        email="alice@example.com",
        is_active=True,
        is_access_enabled=True,
        global_access_from=None,
        global_access_till=None,
    )
    db.add(tenant)

    # ---------- Step 1: Frontend queues capture-fingerprint ----------
    correlation_id = "enroll-42-1-abcd1234"

    push_create_user(db, device_id=1, tenant=tenant, correlation_id=correlation_id, active=True)
    push_enroll_credential(db, device_id=1, tenant_id=42, finger_index=1, correlation_id=correlation_id)

    # Create a mapping (pending)
    mapping = DeviceUserMapping(
        tenant_id=42,
        device_id=1,
        matrix_user_id="42",
        is_synced=False,
        sync_attempt_count=0,
    )
    db.add(mapping)
    db.flush()

    # Verify two items queued: 1 config + 1 command
    all_cmds = db.query(DeviceCommand).all()
    all_cfgs = db.query(DeviceConfig).all()
    assert len(all_cfgs) == 1
    assert all_cfgs[0].config_id == 10
    assert all_cfgs[0].correlation_id == correlation_id
    assert len(all_cmds) == 1
    assert all_cmds[0].cmd_id == 1  # ENROLL_CREDENTIAL

    base_params = {"device-type": "7", "serial-no": "AABBCCDDEEFF", "password": secret}

    # ---------- Step 2: Device logs in ----------
    login_resp = asyncio.run(device_login(make_request("/push/login", base_params), db=db))
    login_data = parse_text_response(login_resp.body.decode())
    assert login_data["status"] == "1"

    # ---------- Step 3: Device polls — config available ----------
    poll_resp = asyncio.run(device_poll(make_request("/push/poll", base_params), db=db))
    poll_data = parse_text_response(poll_resp.body.decode())
    assert poll_data["cnfg-avlbl"] == "1"

    # ---------- Step 4: Device gets config (user creation) ----------
    getcfg_resp = asyncio.run(device_get_config(make_request("/push/getconfig", base_params), db=db))
    getcfg_data = parse_text_response(getcfg_resp.body.decode())
    assert getcfg_data["config-id"] == "10"
    assert getcfg_data["user-id"] == "42"
    assert getcfg_data["name"] == "Alice"
    assert all_cfgs[0].status == "sent"

    # ---------- Step 5: Device reports config success ----------
    updatecfg_resp = asyncio.run(device_update_config(
        make_request("/push/updateconfig", {**base_params, "config-id": "10", "status": "1"}),
        db=db,
    ))
    updatecfg_data = parse_text_response(updatecfg_resp.body.decode())
    assert updatecfg_data["status"] == "1"
    assert all_cfgs[0].status == "success"
    # Callback should have updated device snapshot
    assert "last_user_config" in device.config

    # ---------- Step 6: Device polls — command available ----------
    push_route._last_request.clear()  # Reset rate limiter (simulates time passing)
    poll_resp2 = asyncio.run(device_poll(make_request("/push/poll", base_params), db=db))
    poll_data2 = parse_text_response(poll_resp2.body.decode())
    assert poll_data2["cmd-avlbl"] == "1"

    # ---------- Step 7: Device gets ENROLL_CREDENTIAL command ----------
    getcmd_resp = asyncio.run(device_get_command(make_request("/push/getcmd", base_params), db=db))
    getcmd_data = parse_text_response(getcmd_resp.body.decode())
    assert getcmd_data["cmd-id"] == "1"
    assert getcmd_data["user-id"] == "42"
    assert all_cmds[0].status == "sent"

    # ---------- Step 8: Device reports ENROLL success (no inline template) ----------
    # No data-1 → callback should queue GET_CREDENTIAL automatically
    updatecmd_resp = asyncio.run(device_update_command(
        make_request("/push/updatecmd", {**base_params, "cmd-id": "1", "status": "1", "user-id": "42"}),
        db=db,
    ))
    updatecmd_data = parse_text_response(updatecmd_resp.body.decode())
    assert updatecmd_data["status"] == "1"
    assert all_cmds[0].status == "success"

    # Callback should have auto-queued GET_CREDENTIAL (cmd_id=3)
    all_cmds_now = db.query(DeviceCommand).all()
    get_cred_cmds = [c for c in all_cmds_now if c.cmd_id == 3]
    assert len(get_cred_cmds) == 1, "Callback should auto-queue GET_CREDENTIAL after ENROLL"
    get_cred_cmd = get_cred_cmds[0]
    assert get_cred_cmd.status == "pending"
    assert updatecmd_data["cmd-avlbl"] == "1"  # More commands pending

    # ---------- Step 9: Device gets GET_CREDENTIAL command ----------
    getcmd2_resp = asyncio.run(device_get_command(make_request("/push/getcmd", base_params), db=db))
    getcmd2_data = parse_text_response(getcmd2_resp.body.decode())
    assert getcmd2_data["cmd-id"] == "3"
    assert get_cred_cmd.status == "sent"

    # ---------- Step 10: Device returns fingerprint template ----------
    fake_template = b"\xDE\xAD\xBE\xEF" * 50  # 200 bytes — realistic size
    template_b64 = base64.b64encode(fake_template).decode("ascii")

    # Patch fingerprint storage path so files are written to tmp_path
    import app.api.services.push.callbacks as callbacks_mod
    import app.core.config as config_mod

    monkeypatch.setattr(config_mod.settings, "fingerprint_storage_path", str(tmp_path), raising=False)

    updatecmd2_resp = asyncio.run(device_update_command(
        make_request("/push/updatecmd", {
            **base_params,
            "cmd-id": "3",
            "status": "1",
            "user-id": "42",
            "data-1": template_b64,
        }),
        db=db,
    ))
    updatecmd2_data = parse_text_response(updatecmd2_resp.body.decode())
    assert updatecmd2_data["status"] == "1"
    assert get_cred_cmd.status == "success"

    # Callback should have saved a Credential
    credentials = db.query(Credential).all()
    assert len(credentials) == 1, "GET_CREDENTIAL callback should create a Credential row"
    cred = credentials[0]
    assert cred.tenant_id == 42
    assert cred.type == "finger"
    assert cred.slot_index == 1

    # Mapping should be marked synced
    updated_mapping = db.query(DeviceUserMapping).first()
    assert updated_mapping.is_synced is True

    # ---------- Step 11: Frontend checks enrollment status ----------
    status_result = get_operation_status(correlation_id=correlation_id, db=db)
    assert status_result["status"] == "success", f"Expected success, got: {status_result}"
    assert status_result["correlation_id"] == correlation_id


def test_push_enrollment_with_inline_template(tmp_path, monkeypatch):
    """Test the ENROLL shortcut: device returns data-1 inline in ENROLL response.

    In this case, no GET_CREDENTIAL command should be queued.
    """
    push_route._last_request.clear()

    db = FakeSession()
    device = Device(
        device_id=2,
        company_id=None,
        site_id=None,
        device_serial_number="001122334455",
        vendor="Matrix",
        model_name="COSEC Path V2",
        ip_address=None,
        mac_address="00:11:22:33:44:55",
        api_username="admin",
        api_password_encrypted=None,
        api_port=80,
        use_https=False,
        is_active=True,
        communication_mode="push",
        push_token_hash=None,  # No auth (dev mode)
        status="offline",
        last_heartbeat=None,
        config={},
        created_at=datetime.now(timezone.utc),
    )
    db.add(device)

    tenant = Tenant(
        tenant_id=99,
        company_id=None,
        full_name="Bob",
        email=None,
        is_active=True,
        is_access_enabled=True,
        global_access_from=None,
        global_access_till=None,
    )
    db.add(tenant)

    correlation_id = "enroll-99-2-inline01"
    push_enroll_credential(db, device_id=2, tenant_id=99, finger_index=1, correlation_id=correlation_id)

    mapping = DeviceUserMapping(
        tenant_id=99, device_id=2, matrix_user_id="99", is_synced=False, sync_attempt_count=0,
    )
    db.add(mapping)
    db.flush()

    # Device gets the ENROLL command
    base_params = {"device-type": "4", "serial-no": "001122334455"}
    asyncio.run(device_login(make_request("/push/login", base_params), db=db))
    asyncio.run(device_get_command(make_request("/push/getcmd", base_params), db=db))

    # Device returns data-1 inline (Path V2 behavior)
    fake_template = b"\xAA\xBB" * 100
    template_b64 = base64.b64encode(fake_template).decode("ascii")

    import app.core.config as config_mod
    monkeypatch.setattr(config_mod.settings, "fingerprint_storage_path", str(tmp_path), raising=False)

    updatecmd_resp = asyncio.run(device_update_command(
        make_request("/push/updatecmd", {
            **base_params,
            "cmd-id": "1",
            "status": "1",
            "user-id": "99",
            "data-1": template_b64,
        }),
        db=db,
    ))
    updatecmd_data = parse_text_response(updatecmd_resp.body.decode())
    assert updatecmd_data["status"] == "1"

    # No GET_CREDENTIAL should have been queued (template was inline)
    all_cmds = db.query(DeviceCommand).all()
    get_cred_cmds = [c for c in all_cmds if c.cmd_id == 3]
    assert len(get_cred_cmds) == 0, "Inline template: GET_CREDENTIAL should NOT be queued"

    # Credential should be saved
    credentials = db.query(Credential).all()
    assert len(credentials) == 1
    assert credentials[0].tenant_id == 99
    assert credentials[0].type == "finger"


def test_push_auth_rejection():
    """Test that devices with wrong push_token are rejected."""
    push_route._last_request.clear()

    db = FakeSession()
    device = Device(
        device_id=3,
        company_id=None,
        site_id=None,
        device_serial_number="FFEEDDCCBBAA",
        vendor="Matrix",
        model_name="COSEC",
        ip_address=None,
        mac_address="FF:EE:DD:CC:BB:AA",
        api_username="admin",
        api_password_encrypted=None,
        api_port=80,
        use_https=False,
        is_active=True,
        communication_mode="push",
        push_token_hash=hashlib.sha256("correct_password".encode()).hexdigest(),
        status="offline",
        last_heartbeat=None,
        config={},
        created_at=datetime.now(timezone.utc),
    )
    db.add(device)

    # Login with wrong password
    login_resp = asyncio.run(device_login(
        make_request("/push/login", {"device-type": "7", "serial-no": "FFEEDDCCBBAA", "password": "wrong_password"}),
        db=db,
    ))
    login_data = parse_text_response(login_resp.body.decode())
    assert login_data["status"] == "0", "Wrong password should be rejected"

    # Login with correct password
    login_resp2 = asyncio.run(device_login(
        make_request("/push/login", {"device-type": "7", "serial-no": "FFEEDDCCBBAA", "password": "correct_password"}),
        db=db,
    ))
    login_data2 = parse_text_response(login_resp2.body.decode())
    assert login_data2["status"] == "1", "Correct password should succeed"
