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
        for ws in self.connections[execution_id]:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(execution_id, ws)

ws_manager = ConnectionManager()

