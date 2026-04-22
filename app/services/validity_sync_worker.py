"""
Background worker: activate tenants on devices when their access start time arrives.

The Matrix device natively enforces the end date (validity-date set at enrollment),
so we only need to handle the start-date side: when global_access_from passes, flip
user-active from 0 → 1 on all enrolled devices.

All devices use push mode — queues config-id=10 which the device picks up on next poll.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.api.services.push.commands import push_create_user
from database.models import Device, DeviceUserMapping, Tenant
from database.session import SessionLocal

log = logging.getLogger(__name__)


def _activate_newly_valid_tenants(interval_seconds: int) -> tuple[int, int]:
    """
    Find tenants whose global_access_from just passed in the last poll window
    and activate them (user-active=1) on all their enrolled devices.

    Returns (activated_count, failed_count).
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=interval_seconds)

        newly_valid = (
            db.query(Tenant)
            .filter(
                Tenant.global_access_from >= window_start,
                Tenant.global_access_from <= now,
                Tenant.is_active.is_(True),
                Tenant.is_access_enabled.is_(True),
            )
            .all()
        )

        if not newly_valid:
            return 0, 0

        activated = 0
        failed = 0

        for tenant in newly_valid:
            mappings = (
                db.query(DeviceUserMapping)
                .filter(DeviceUserMapping.tenant_id == tenant.tenant_id)
                .all()
            )
            device_ids = [m.device_id for m in mappings]
            if not device_ids:
                continue

            devices = (
                db.query(Device)
                .filter(Device.device_id.in_(device_ids))
                .all()
            )

            for device in devices:
                try:
                    push_create_user(
                        db, device.device_id, tenant,
                        correlation_id=f"validity-{tenant.tenant_id}",
                        active=True,
                    )
                    db.commit()
                    log.info(
                        "Queued activation for tenant %d on device %d (access_from=%s)",
                        tenant.tenant_id, device.device_id, tenant.global_access_from,
                    )
                    activated += 1
                except Exception:
                    db.rollback()
                    log.exception(
                        "Error queuing activation for tenant %d on device %d",
                        tenant.tenant_id, device.device_id,
                    )
                    failed += 1

        return activated, failed
    finally:
        db.close()


async def run_validity_sync_loop(interval_seconds: int = 60) -> None:
    """
    Infinite loop: check for start-date arrivals every `interval_seconds` seconds.
    End dates are enforced natively by the device via validity-date set at enrollment.
    Cancelled cleanly when the FastAPI app shuts down.
    """
    log.info("Validity sync worker started (interval: %ds)", interval_seconds)
    while True:
        try:
            activated, failed = await asyncio.get_running_loop().run_in_executor(
                None, _activate_newly_valid_tenants, interval_seconds
            )
            if activated or failed:
                log.info("Validity sync — activated: %d  failed: %d", activated, failed)
        except Exception:
            log.exception("Validity sync worker error")

        await asyncio.sleep(interval_seconds)
