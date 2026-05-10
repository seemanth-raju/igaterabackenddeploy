from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.services.devices.route import _to_device_read


def test_to_device_read_includes_credential_types():
    device = SimpleNamespace(
        device_id=14,
        company_id=uuid4(),
        site_id=None,
        device_serial_number="SN-14",
        vendor="Matrix",
        model_name="COSEC",
        ip_address="192.0.2.10",
        mac_address="00:11:22:33:44:55",
        api_username="admin",
        api_port=80,
        use_https=False,
        is_active=True,
        communication_mode="push",
        status="online",
        config={},
        credential_types=["finger", "card"],
        created_at=datetime.now(timezone.utc),
    )

    result = _to_device_read(device)

    assert result.credential_types == ["finger", "card"]


def test_to_device_read_defaults_credential_types():
    device = SimpleNamespace(
        device_id=15,
        company_id=uuid4(),
        site_id=None,
        device_serial_number="SN-15",
        vendor="Matrix",
        model_name=None,
        ip_address=None,
        mac_address=None,
        api_username=None,
        api_port=80,
        use_https=False,
        is_active=True,
        communication_mode="direct",
        status="offline",
        config={},
        credential_types=None,
        created_at=datetime.now(timezone.utc),
    )

    result = _to_device_read(device)

    assert result.credential_types == ["finger"]
