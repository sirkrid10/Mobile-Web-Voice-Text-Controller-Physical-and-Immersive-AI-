"""Own visitor WebSocket connections and state broadcasts."""

import asyncio
from typing import List

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self, state_reader):
        self._state_reader = state_reader
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        # Send immediate initial state
        state = self._state_reader()
        await websocket.send_text(state.model_dump_json())

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def broadcast_state(self):
        state = self._state_reader()
        payload = state.model_dump_json()
        async with self._lock:
            disconnected = []
            for ws in self.active_connections:
                try:
                    await ws.send_text(payload)
                except Exception:
                    disconnected.append(ws)
            for ws in disconnected:
                if ws in self.active_connections:
                    self.active_connections.remove(ws)
