"""WebSocket connection manager for real-time access log broadcasting."""

import json
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """
    Manages active WebSocket connections, scoped by company_id.

    - Company-scoped connections only receive events for their company.
    - Super-admin connections (company_id=None) receive all events.
    """

    def __init__(self) -> None:
        # key: company_id string or None (super_admin) -> list of WebSockets
        self._connections: dict[str | None, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, company_id: str | None) -> None:
        await websocket.accept()
        self._connections.setdefault(company_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, company_id: str | None) -> None:
        bucket = self._connections.get(company_id, [])
        if websocket in bucket:
            bucket.remove(websocket)

    async def broadcast(self, payload: dict[str, Any], company_id: str | None) -> None:
        """
        Send payload to:
          - all connections scoped to `company_id`
          - all super-admin connections (None key)
        """
        message = json.dumps(payload, default=str)
        targets: list[WebSocket] = []

        if company_id is not None:
            targets.extend(self._connections.get(company_id, []))

        # Super-admin connections always get everything
        targets.extend(self._connections.get(None, []))

        dead: list[tuple[WebSocket, str | None]] = []
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                key = company_id if ws in self._connections.get(company_id, []) else None
                dead.append((ws, key))

        for ws, key in dead:
            self.disconnect(ws, key)


# Singleton — imported by route and service layers
manager = ConnectionManager()
