"""
Background script: polls all devices every N seconds and updates
device.status + device.last_heartbeat in the database.

Run directly:
    python scripts/device_health_checker.py

Run with a custom interval (e.g. every 60 seconds):
    python scripts/device_health_checker.py --interval 60
"""

import argparse
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import func

from app.services.matrix import MatrixDeviceClient
from database.models import Device
from database.session import SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def check_all_devices() -> None:
    db = SessionLocal()
    try:
        devices = db.query(Device).filter(Device.ip_address.isnot(None)).all()
        log.info("Checking %d device(s)...", len(devices))

        for device in devices:
            client = MatrixDeviceClient(
                device_ip=device.ip_address,
                username=device.api_username or "admin",
                encrypted_password=device.api_password_encrypted or "",
                use_https=device.use_https,
            )
            is_online = client.ping()
            new_status = "online" if is_online else "offline"

            if device.status != new_status:
                log.info(
                    "Device %d (%s) status changed: %s → %s",
                    device.device_id,
                    device.ip_address,
                    device.status,
                    new_status,
                )

            device.status = new_status
            device.last_heartbeat = db.query(func.current_timestamp()).scalar()

        db.commit()
        log.info("Done. %d online, %d offline.",
                 sum(1 for d in devices if d.status == "online"),
                 sum(1 for d in devices if d.status == "offline"))
    except Exception:
        log.exception("Error during device health check")
        db.rollback()
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Device health checker")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval in seconds (default: 30)")
    parser.add_argument("--once", action="store_true", help="Run once and exit (useful for cron)")
    args = parser.parse_args()

    if args.once:
        check_all_devices()
        return

    log.info("Starting device health checker (interval: %ds). Press Ctrl+C to stop.", args.interval)
    while True:
        check_all_devices()
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
