# -*- coding: utf-8 -*-
from fastapi import WebSocket

class ConnectionManager:
    """Manages per-execution WebSocket connections."""
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, execution_id: str, ws: WebSocket):
        await ws.accept()
        if execution_id not in self.connections:
            self.connections[execution_id] = []
        self.connections[execution_id].append(ws)

    def disconnect(self, execution_id: str, ws: WebSocket):
        if execution_id in self.connections:
            self.connections[execution_id] = [
                c for c in self.connections[execution_id] if c is not ws
            ]
            if not self.connections[execution_id]:
                del self.connections[execution_id]

    async def emit(self, execution_id: str, event: dict):
        """Send event to all WebSocket subscribers of this execution."""
        if execution_id not in self.connections:
            return
        dead = []
        safe_event = self._redact_event(event)
        for ws in self.connections[execution_id]:
            try:
                await ws.send_json(safe_event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(execution_id, ws)

    @staticmethod
    def _redact_event(value):
        from services.platform_registry_service import redact_raw_output

        if isinstance(value, dict):
            return {key: ConnectionManager._redact_event(item) for key, item in value.items()}
        if isinstance(value, list):
            return [ConnectionManager._redact_event(item) for item in value]
        if isinstance(value, str):
            return redact_raw_output(value)
        return value

ws_manager = ConnectionManager()

