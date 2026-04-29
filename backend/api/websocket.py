"""
WebSocket handlers for real-time data streaming.
"""
import asyncio
import json
import logging
from typing import Dict, List, Set

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger("raven.ws")


class ConnectionManager:
    """Manages WebSocket connections by channel."""

    def __init__(self):
        self._channels: Dict[str, Set[WebSocket]] = {
            "spectrum": set(),
            "alerts": set(),
            "status": set(),
        }
        self._heartbeat_interval = 30

    async def connect(self, websocket: WebSocket, channel: str):
        if channel not in self._channels:
            self._channels[channel] = set()
        await websocket.accept()
        self._channels[channel].add(websocket)
        logger.info("WS connect: %s (channel=%s, total=%d)",
                     websocket.client, channel, len(self._channels[channel]))

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self._channels:
            self._channels[channel].discard(websocket)
        logger.info("WS disconnect: channel=%s", channel)

    async def broadcast(self, channel: str, data: dict):
        """Send data to all connected clients on a channel."""
        if channel not in self._channels:
            return

        dead = []
        message = json.dumps(data)
        for ws in self._channels[channel]:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self._channels[channel].discard(ws)

    async def broadcast_alert(self, event_data: dict):
        """Broadcast an alert event to all alert subscribers."""
        await self.broadcast("alerts", {
            "type": "alert",
            "data": event_data,
        })

    async def broadcast_spectrum_frame(self, frame_data: dict):
        """Broadcast a spectrum frame to all spectrum subscribers."""
        await self.broadcast("spectrum", {
            "type": "spectrum",
            "data": frame_data,
        })

    async def broadcast_device_status(self, device_data: dict):
        """Broadcast device status update."""
        await self.broadcast("status", {
            "type": "device_status",
            "data": device_data,
        })

    def client_count(self, channel: str) -> int:
        return len(self._channels.get(channel, set()))


# Singleton
ws_manager = ConnectionManager()


async def spectrum_endpoint(websocket: WebSocket):
    """WebSocket endpoint for live spectrum data."""
    await ws_manager.connect(websocket, "spectrum")
    try:
        while True:
            # Client can send control messages (e.g., change freq range)
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                logger.debug("Spectrum control: %s", msg)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, "spectrum")


async def alerts_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time alert stream."""
    await ws_manager.connect(websocket, "alerts")
    try:
        while True:
            await websocket.receive_text()  # keepalive
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, "alerts")


async def status_endpoint(websocket: WebSocket):
    """WebSocket endpoint for device/system status updates."""
    await ws_manager.connect(websocket, "status")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, "status")
