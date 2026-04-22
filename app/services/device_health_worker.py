"""Background worker: mark push-mode devices as offline when they stop polling.

Runs every 30s, checks last_heartbeat against the configured threshold
(push_api_device_offline_seconds, default 120s).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from database.models import Device
from database.session import SessionLocal

log = logging.getLogger(__name__)


def _mark_stale_devices_offline() -> int:
    """Mark push devices as offline if they haven't polled recently.

    Returns the number of devices marked offline.
    """
    db = SessionLocal()
    try:
        threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.push_api_device_offline_seconds)
        stale_devices = (
            db.query(Device)
            .filter(
                Device.communication_mode == "push",
                Device.status == "online",
                Device.last_heartbeat < threshold,
            )
            .all()
        )
        count = 0
        for device in stale_devices:
            device.status = "offline"
            log.info(
                "Device %d (%s) marked offline — last heartbeat: %s",
                device.device_id, device.device_serial_number, device.last_heartbeat,
            )
            count += 1

        if count:
            db.commit()
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def run_device_health_loop(interval_seconds: int = 30) -> None:
    """Infinite loop: check for stale push devices every interval_seconds."""
    log.info("Device health worker started (interval: %ds, offline threshold: %ds)",
             interval_seconds, settings.push_api_device_offline_seconds)
    while True:
        try:
            count = await asyncio.get_running_loop().run_in_executor(None, _mark_stale_devices_offline)
            if count:
                log.info("Device health check — marked %d device(s) offline", count)
        except Exception:
            log.exception("Device health worker error")

        await asyncio.sleep(interval_seconds)
