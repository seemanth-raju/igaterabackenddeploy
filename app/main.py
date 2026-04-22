import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.schema_guard import assert_required_schema
from app.services.log_sync_worker import run_log_sync_loop
from app.services.device_health_worker import run_device_health_loop
from app.services.validity_sync_worker import run_validity_sync_loop
from database.session import engine

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    assert_required_schema(engine)

    sync_task = asyncio.create_task(
        run_log_sync_loop(interval_seconds=settings.log_sync_interval_seconds)
    )
    log.info("Log sync worker scheduled every %ds", settings.log_sync_interval_seconds)

    validity_task = asyncio.create_task(
        run_validity_sync_loop(interval_seconds=settings.validity_sync_interval_seconds)
    )
    log.info("Validity sync worker scheduled every %ds", settings.validity_sync_interval_seconds)

    health_task = asyncio.create_task(run_device_health_loop(interval_seconds=30))
    log.info("Device health worker scheduled every 30s")

    yield  # app is running

    # Shutdown
    sync_task.cancel()
    validity_task.cancel()
    health_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        log.info("Log sync worker stopped")
    try:
        await validity_task
    except asyncio.CancelledError:
        log.info("Validity sync worker stopped")
    try:
        await health_task
    except asyncio.CancelledError:
        log.info("Device health worker stopped")


app = FastAPI(title=settings.app_name, debug=settings.app_debug, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Veda API running. Open /docs for Swagger UI."}


app.include_router(api_router)
