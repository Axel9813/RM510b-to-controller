"""
RC Discovery — finds the RC's WebSocket server on the LAN.

Mechanisms (all OUTBOUND — no inbound traffic needed):
  1. **TCP subnet scan** — probes every /24 LAN IP on the RC's WS port
  2. **Loopback probe** — checks localhost for ADB forward tunnel
  3. **UDP listener** — listens for RC broadcast announcements (fallback,
     may be blocked by firewall)
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

# ── Shared constants ─────────────────────────────────────────────────────────
MAGIC_PREFIX       = b"DJI_RC_DISCOVER|"
UDP_ANNOUNCE_PORT  = 8765
LOOPBACK_CHECK_INTERVAL = 5.0
SCAN_INTERVAL      = 15.0        # seconds between subnet scans
SCAN_BATCH_SIZE    = 64           # concurrent TCP connect attempts

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]


def _is_lan_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in _PRIVATE_NETS)
    except ValueError:
        return False


def _get_lan_ips() -> list[str]:
    """Get this machine's RFC-1918 IPv4 addresses."""
    ips: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if _is_lan_ip(ip):
                ips.add(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        candidate = s.getsockname()[0]
        s.close()
        if _is_lan_ip(candidate):
            ips.add(candidate)
    except Exception:
        pass
    return sorted(ips)


# ── RC entry ─────────────────────────────────────────────────────────────────

class RcEntry:
    """A discovered RC WebSocket server."""
    __slots__ = ("name", "host", "port", "method")

    def __init__(self, name: str, host: str, port: int, method: str) -> None:
        self.name = name
        self.host = host
        self.port = port
        self.method = method

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    def __repr__(self) -> str:
        return f"RcEntry({self.name} @ {self.host}:{self.port} via {self.method})"


# ── TCP subnet scan (PRIMARY — all outbound, no firewall issues) ─────────────

async def _tcp_scan_loop(
    port: int,
    on_found: Callable[[RcEntry], Any],
    stop_event: asyncio.Event,
) -> None:
    """Periodically scan LAN /24 subnets for an open WS server on `port`."""
    while not stop_event.is_set():
        try:
            await _run_scan(port, on_found)
        except Exception as exc:
            log.debug("Subnet scan error: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=SCAN_INTERVAL)
            break
        except asyncio.TimeoutError:
            pass


async def _run_scan(port: int, on_found: Callable[[RcEntry], Any]) -> None:
    """Scan all LAN /24 subnets for an open TCP port."""
    lan_ips = _get_lan_ips()
    if not lan_ips:
        return

    # Build candidate list (skip our own IPs)
    own_ips = set(lan_ips)
    candidates: list[str] = []
    subnets_scanned: set[str] = set()
    for ip in lan_ips:
        parts = ip.split(".")
        subnet = f"{parts[0]}.{parts[1]}.{parts[2]}"
        if subnet in subnets_scanned:
            continue
        subnets_scanned.add(subnet)
        for i in range(1, 255):
            candidate = f"{subnet}.{i}"
            if candidate not in own_ips:
                candidates.append(candidate)

    if not candidates:
        return

    log.debug("Scanning %d IPs on port %d (subnets: %s)",
              len(candidates), port, list(subnets_scanned))

    # Scan in batches
    for i in range(0, len(candidates), SCAN_BATCH_SIZE):
        batch = candidates[i:i + SCAN_BATCH_SIZE]
        await asyncio.gather(
            *[_probe_host(ip, port, on_found) for ip in batch],
            return_exceptions=True,
        )


async def _probe_host(
    ip: str, port: int, on_found: Callable[[RcEntry], Any],
) -> None:
    """Two-phase probe: TCP connect then WebSocket handshake verification.

    The scan is only active when no RC client is connected, so the WS
    handshake cannot interfere with an active session.
    """
    try:
        # Phase 1: quick TCP connect
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=0.4,
        )
        writer.close()
        await writer.wait_closed()
    except Exception:
        return  # port closed or unreachable

    # Phase 2: verify it's actually a WebSocket server
    try:
        import websockets
        ws = await asyncio.wait_for(
            websockets.connect(f"ws://{ip}:{port}"),
            timeout=2.0,
        )
        await ws.close()
    except Exception:
        return  # port open but not a WebSocket server

    entry = RcEntry(name="RC", host=ip, port=port, method="scan")
    on_found(entry)


# ── Loopback probe (ADB forward tunnel) ─────────────────────────────────────

async def _loopback_probe(
    port: int,
    on_found: Callable[[RcEntry], Any],
    stop_event: asyncio.Event,
) -> None:
    """Periodically check localhost:port for an ADB forward tunnel."""
    while not stop_event.is_set():
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port),
                timeout=0.5,
            )
            writer.close()
            await writer.wait_closed()
            entry = RcEntry(
                name="USB (ADB)", host="127.0.0.1", port=port, method="adb",
            )
            on_found(entry)
        except Exception:
            pass

        try:
            await asyncio.wait_for(stop_event.wait(),
                                   timeout=LOOPBACK_CHECK_INTERVAL)
            break
        except asyncio.TimeoutError:
            pass


# ── UDP announcement listener (fallback — may be blocked by firewall) ───────

class _UdpAnnouncementListener(asyncio.DatagramProtocol):
    """Listens for RC UDP broadcast announcements."""

    def __init__(self, on_found: Callable[[RcEntry], Any]) -> None:
        self._on_found = on_found
        self._transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
        self._transport = transport
        log.info("UDP listener: listening on port %d (may be blocked by firewall)",
                 UDP_ANNOUNCE_PORT)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        sender_ip = addr[0]
        if sender_ip != "127.0.0.1" and not _is_lan_ip(sender_ip):
            return
        if not data.startswith(MAGIC_PREFIX):
            return
        try:
            payload = json.loads(data[len(MAGIC_PREFIX):].decode("utf-8"))
        except Exception:
            return
        if payload.get("type") != "dji_rc_server":
            return

        name = payload.get("name", "RC")
        port = payload.get("port", 8080)
        entry = RcEntry(name=name, host=sender_ip, port=port, method="udp")
        self._on_found(entry)

    def error_received(self, exc: Exception) -> None:
        log.warning("UDP listener error: %s", exc)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        log.debug("UDP listener socket closed.")


# ── Public facade ─────────────────────────────────────────────────────────────

class RcDiscovery:
    """
    Discovers RC WebSocket servers on the LAN.

    Primary: TCP subnet scan (outbound only, firewall-proof).
    Secondary: ADB loopback probe, UDP listener.
    """

    def __init__(
        self,
        on_rc_found: Callable[[RcEntry], Any],
        ws_port: int = 8080,
    ) -> None:
        self._on_rc_found = on_rc_found
        self._ws_port = ws_port
        self._udp_transport: Optional[asyncio.DatagramTransport] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._scan_task: Optional[asyncio.Task] = None
        self._loopback_task: Optional[asyncio.Task] = None
        self._seen: dict[str, float] = {}

    async def start(self) -> None:
        self._stop_event = asyncio.Event()

        # 1. TCP subnet scan (primary — all outbound)
        self._scan_task = asyncio.create_task(
            _tcp_scan_loop(self._ws_port, self._on_found, self._stop_event)
        )

        # 2. Loopback probe (ADB forward)
        self._loopback_task = asyncio.create_task(
            _loopback_probe(self._ws_port, self._on_found, self._stop_event)
        )

        # 3. UDP listener (fallback — may be blocked by firewall)
        loop = asyncio.get_event_loop()
        try:
            self._udp_transport, _ = await loop.create_datagram_endpoint(
                lambda: _UdpAnnouncementListener(self._on_found),
                local_addr=("0.0.0.0", UDP_ANNOUNCE_PORT),
                allow_broadcast=True,
            )
        except Exception as exc:
            log.warning("UDP listener failed to start: %s", exc)

        log.info("RC discovery started (subnet scan + loopback + UDP listener)")

    def pause(self) -> None:
        """Pause active scanning (called when RC is connected).

        Stops the TCP subnet scan and ADB loopback probe.
        UDP listener stays up (passive, doesn't interfere).
        """
        if self._stop_event:
            self._stop_event.set()
        log.info("Discovery paused (RC connected).")

    def resume(self) -> None:
        """Resume active scanning (called when reconnection exhausted).

        Restarts TCP subnet scan and ADB loopback probe with a fresh
        stop event.  Clears the seen-cache so hosts are re-reported.
        """
        # Don't double-start
        if self._scan_task and not self._scan_task.done():
            return

        self._stop_event = asyncio.Event()
        self._seen.clear()

        self._scan_task = asyncio.create_task(
            _tcp_scan_loop(self._ws_port, self._on_found, self._stop_event)
        )
        self._loopback_task = asyncio.create_task(
            _loopback_probe(self._ws_port, self._on_found, self._stop_event)
        )
        log.info("Discovery resumed (searching for RC).")

    def _on_found(self, entry: RcEntry) -> None:
        """Deduplicate and forward to caller."""
        import time
        now = time.monotonic()
        key = f"{entry.host}:{entry.port}"

        # Suppress duplicate notifications within 30 seconds
        last = self._seen.get(key, 0.0)
        if now - last < 30.0:
            return
        self._seen[key] = now

        log.info("Discovered RC: %s", entry)
        self._on_rc_found(entry)

    def stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._udp_transport:
            self._udp_transport.close()
            self._udp_transport = None
        log.info("RC discovery stopped.")
