"""
Federation service — Peer-to-peer mesh discovery and intel sharing
between Recon-Raven nodes.

Each node advertises itself via UDP multicast and shares events/alerts
over a lightweight HTTP API.
"""
import asyncio
import json
import logging
import socket
import struct
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger("raven.federation")

MCAST_GROUP = "239.42.42.42"
MCAST_PORT = 8042
BEACON_INTERVAL = 10  # seconds
PEER_TIMEOUT = 45  # seconds without beacon → stale


class FederationPeer:
    """Represents a remote Raven node."""
    def __init__(self, node_id: str, host: str, port: int, version: str = ""):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.version = version
        self.last_seen = time.time()
        self.gps_lat: Optional[float] = None
        self.gps_lon: Optional[float] = None
        self.device_count: int = 0

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_seen) < PEER_TIMEOUT

    @property
    def api_url(self) -> str:
        return f"http://{self.host}:{self.port}/api"

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "host": self.host,
            "port": self.port,
            "version": self.version,
            "last_seen": self.last_seen,
            "alive": self.is_alive,
            "gps": {"lat": self.gps_lat, "lon": self.gps_lon}
                  if self.gps_lat else None,
            "device_count": self.device_count,
        }


class FederationService:
    def __init__(self, settings, node_id: str = ""):
        self._settings = settings
        self._node_id = node_id or socket.gethostname()
        self._port = getattr(settings, "port", 8080)
        self._peers: Dict[str, FederationPeer] = {}
        self._running = False
        self._beacon_task: Optional[asyncio.Task] = None
        self._listener_task: Optional[asyncio.Task] = None
        self._sock: Optional[socket.socket] = None
        self._enabled = getattr(getattr(settings, "federation", None),
                                "enabled", False)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def start(self):
        if not self._enabled:
            logger.info("Federation disabled in config")
            return

        self._running = True

        # Create multicast UDP socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                   socket.IPPROTO_UDP)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Bind to multicast port
        self._sock.bind(("", MCAST_PORT))

        # Join multicast group
        mreq = struct.pack("4sL", socket.inet_aton(MCAST_GROUP),
                           socket.INADDR_ANY)
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self._sock.setblocking(False)

        self._beacon_task = asyncio.create_task(self._beacon_loop())
        self._listener_task = asyncio.create_task(self._listen_loop())

        logger.info("Federation started — node=%s, multicast=%s:%d",
                     self._node_id, MCAST_GROUP, MCAST_PORT)

    async def stop(self):
        self._running = False
        if self._beacon_task:
            self._beacon_task.cancel()
        if self._listener_task:
            self._listener_task.cancel()
        if self._sock:
            self._sock.close()
        logger.info("Federation stopped")

    def get_peers(self) -> List[dict]:
        """Return all known peers."""
        # Prune stale
        stale = [nid for nid, p in self._peers.items()
                 if not p.is_alive]
        for nid in stale:
            del self._peers[nid]
        return [p.to_dict() for p in self._peers.values()]

    def get_status(self) -> dict:
        return {
            "enabled": self._enabled,
            "running": self._running,
            "node_id": self._node_id,
            "peer_count": len([p for p in self._peers.values() if p.is_alive]),
            "multicast_group": MCAST_GROUP,
            "multicast_port": MCAST_PORT,
        }

    async def share_event(self, event_data: dict):
        """Push an event to all alive peers."""
        if not self._running:
            return

        alive = [p for p in self._peers.values() if p.is_alive]
        if not alive:
            return

        payload = {
            "from_node": self._node_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_data,
        }

        async with httpx.AsyncClient(timeout=5) as client:
            for peer in alive:
                try:
                    await client.post(
                        f"{peer.api_url}/federation/receive",
                        json=payload,
                    )
                except Exception as e:
                    logger.debug("Failed to share event with %s: %s",
                                 peer.node_id, e)

    async def query_peer(self, node_id: str, endpoint: str) -> Optional[dict]:
        """Query a specific peer's API."""
        peer = self._peers.get(node_id)
        if not peer or not peer.is_alive:
            return None

        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{peer.api_url}/{endpoint}")
                return resp.json()
            except Exception as e:
                logger.error("Query peer %s failed: %s", node_id, e)
                return None

    # ── Internal ────────────────────────────────────────────────

    async def _beacon_loop(self):
        """Periodically send beacon on multicast."""
        loop = asyncio.get_event_loop()
        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                  socket.IPPROTO_UDP)
        send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

        while self._running:
            try:
                beacon = json.dumps({
                    "node_id": self._node_id,
                    "port": self._port,
                    "version": "0.1.0",
                    "ts": time.time(),
                }).encode()

                await loop.run_in_executor(
                    None,
                    lambda: send_sock.sendto(beacon, (MCAST_GROUP, MCAST_PORT)),
                )
            except Exception as e:
                logger.debug("Beacon send error: %s", e)

            await asyncio.sleep(BEACON_INTERVAL)

        send_sock.close()

    async def _listen_loop(self):
        """Listen for multicast beacons from other nodes."""
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                data, addr = await loop.run_in_executor(
                    None, lambda: self._sock.recvfrom(1024),
                )
                msg = json.loads(data.decode())
                node_id = msg.get("node_id", "")

                # Skip our own beacons
                if node_id == self._node_id:
                    continue

                host = addr[0]
                port = msg.get("port", 8080)

                if node_id in self._peers:
                    self._peers[node_id].last_seen = time.time()
                    self._peers[node_id].version = msg.get("version", "")
                else:
                    peer = FederationPeer(node_id, host, port,
                                          msg.get("version", ""))
                    self._peers[node_id] = peer
                    logger.info("New peer discovered: %s @ %s:%d",
                                 node_id, host, port)

            except BlockingIOError:
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.debug("Listener error: %s", e)
                await asyncio.sleep(1)
