"""WebSocket transport — connects OUT to the RC's WebSocket server.

This reverses the original architecture: instead of the RC connecting
to us, we connect to the RC. Outbound TCP from Windows is virtually
never blocked by firewalls, solving the GPO/firewall issue.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional

import websockets
from websockets.connection import State as WsState

from .base import RcTransport

log = logging.getLogger(__name__)

# Reconnection backoff
_MIN_RETRY = 2.0          # seconds
_MAX_RETRY = 15.0         # seconds
_PING_INTERVAL = 10.0     # seconds
_PING_TIMEOUT = 25.0      # seconds
_RETRIES_BEFORE_SCAN = 5  # trigger scan after this many consecutive failures


class WebSocketTransport(RcTransport):
    """Persistent WebSocket connection to the RC.

    Handles:
      - Connecting to a discovered RC
      - Receiving messages and dispatching to handlers
      - Sending messages (element_update, pong, etc.)
      - App-level ping/pong
      - Auto-reconnection with exponential backoff
    """

    def __init__(
        self,
        on_message: Callable[[dict[str, Any]], Any],
        on_connected: Callable[[], Any],
        on_disconnected: Callable[[], Any],
        on_retries_exhausted: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(on_message, on_connected, on_disconnected)
        self._on_retries_exhausted = on_retries_exhausted
        self._ws = None
        self._url: Optional[str] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._consecutive_failures = 0
        self._exhausted_fired = False

    @property
    def transport_type(self) -> str:
        return 'websocket'

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._ws.state == WsState.OPEN

    @property
    def peer_description(self) -> Optional[str]:
        if self.connected and self._url:
            return self._url
        return None

    @property
    def url(self) -> Optional[str]:
        return self._url

    # ── Target management ───────────────────────────────────────────────

    def set_target(self, url: str) -> None:
        """Set the WebSocket URL to connect to."""
        self._url = url

    # ── send_text compatibility ─────────────────────────────────────────

    async def send_text(self, text: str) -> None:
        """Send raw text — compatible with FastAPI WebSocket.send_text()."""
        if self._ws is not None and self._ws.state == WsState.OPEN:
            await self._ws.send(text)

    async def send(self, msg: dict[str, Any]) -> None:
        """Send a JSON message to the RC."""
        if self._ws is not None and self._ws.state == WsState.OPEN:
            await self._ws.send(json.dumps(msg))

    # ── Connection lifecycle ────────────────────────────────────────────

    async def start(self) -> None:
        """Begin connecting to the RC at the current target URL."""
        if not self._url:
            return
        self.stop()
        self._running = True
        self._consecutive_failures = 0
        self._exhausted_fired = False
        self._task = asyncio.ensure_future(self._run_loop())

    def start_with_url(self, url: str) -> None:
        """Set target and start connecting (convenience for discovery)."""
        self.stop()
        self._url = url
        self._running = True
        self._consecutive_failures = 0
        self._exhausted_fired = False
        self._task = asyncio.ensure_future(self._run_loop())

    def stop(self) -> None:
        """Stop the connection loop and disconnect."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        if self._ws:
            asyncio.ensure_future(self._close_ws())

    async def _close_ws(self) -> None:
        try:
            if self._ws:
                await self._ws.close()
        except Exception:
            pass
        self._ws = None

    async def _run_loop(self) -> None:
        """Main loop: connect, handle messages, reconnect on failure."""
        while self._running and self._url:
            try:
                log.info("Connecting to RC at %s ...", self._url)
                self._ws = await asyncio.wait_for(
                    websockets.connect(
                        self._url,
                        ping_interval=_PING_INTERVAL,
                        ping_timeout=_PING_TIMEOUT,
                        close_timeout=5,
                    ),
                    timeout=10.0,
                )
                log.info("Connected to RC at %s", self._url)
                self._consecutive_failures = 0
                self._on_connected()

                # Read loop
                async for raw in self._ws:
                    if not self._running:
                        break
                    try:
                        msg = json.loads(raw)
                        self._on_message(msg)
                    except json.JSONDecodeError:
                        pass

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._consecutive_failures += 1
                log.warning("RC connection failed: %s (attempt %d)",
                            exc, self._consecutive_failures)
                if (self._consecutive_failures >= _RETRIES_BEFORE_SCAN
                        and not self._exhausted_fired
                        and self._on_retries_exhausted):
                    self._exhausted_fired = True
                    self._on_retries_exhausted()
            finally:
                was_connected = self._ws is not None
                await self._close_ws()
                if was_connected:
                    self._on_disconnected()

            if not self._running:
                break

            # Backoff
            delay = min(
                _MIN_RETRY + self._consecutive_failures * 1.0,
                _MAX_RETRY,
            )
            log.info("Reconnecting in %.0fs...", delay)
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break
