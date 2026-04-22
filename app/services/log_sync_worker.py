"""
Background worker: periodically pulls access logs from all active devices,
inserts them into the database, and broadcasts new events via WebSocket.

Runs inside the FastAPI process (same event loop) so WebSocket clients
get real-time pushes without any external queue or separate process.
"""

import asyncio
import logging

from app.api.services.logs.service import sync_logs_from_device
from app.services.ws_manager import manager
from database.models import Device
from database.session import SessionLocal

log = logging.getLogger(__name__)


def _load_device_ids() -> list[tuple[int, str | None]]:
    """Return direct-mode devices with IPs for background log polling."""
    db = SessionLocal()
    try:
        devices = db.query(Device).filter(Device.ip_address.isnot(None)).all()
        return [
            (d.device_id, str(d.company_id) if d.company_id else None)
            for d in devices
            if d.communication_mode != "push"
        ]
    finally:
        db.close()


def _sync_one(device_id: int) -> dict:
    """Run sync in a thread (SQLAlchemy session created and closed here)."""
    db = SessionLocal()
    try:
        return sync_logs_from_device(device_id, db)
    except Exception as exc:
        # HTTPException from service or network errors — treat as empty result
        log.warning("Sync failed for device %d: %s", device_id, exc)
        return {"device_id": device_id, "fetched": 0, "inserted": 0, "skipped": 0,
                "_new_events": [], "_company_id": None}
    finally:
        db.close()


async def _sync_device(device_id: int, company_id: str | None) -> None:
    result = await asyncio.get_running_loop().run_in_executor(None, _sync_one, device_id)

    new_events: list[dict] = result.pop("_new_events", [])
    result.pop("_company_id", None)

    if result["inserted"] > 0:
        log.info(
            "Device %d — fetched: %d  inserted: %d  skipped: %d",
            device_id, result["fetched"], result["inserted"], result["skipped"],
        )
    else:
        log.debug(
            "Device %d — fetched: %d  inserted: 0  skipped: %d",
            device_id, result["fetched"], result["skipped"],
        )

    for evt in new_events:
        await manager.broadcast(evt, company_id)


async def run_log_sync_loop(interval_seconds: int = 60) -> None:
    """
    Infinite loop: sync every device every `interval_seconds` seconds.
    Cancelled cleanly when the FastAPI app shuts down.
    """
    log.info("Log sync worker started (interval: %ds)", interval_seconds)
    while True:
        try:
            device_list = await asyncio.get_running_loop().run_in_executor(None, _load_device_ids)
        except Exception:
            log.exception("Could not load device list — will retry next cycle")
            await asyncio.sleep(interval_seconds)
            continue

        if device_list:
            log.debug("Syncing logs for %d device(s)…", len(device_list))
            # Run all devices concurrently
            await asyncio.gather(
                *[_sync_device(did, cid) for did, cid in device_list],
                return_exceptions=True,
            )

        await asyncio.sleep(interval_seconds)
