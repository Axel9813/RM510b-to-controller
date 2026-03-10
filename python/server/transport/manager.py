"""Transport manager — selects the best transport and provides a unified interface."""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .base import RcTransport

log = logging.getLogger(__name__)


class TransportManager:
    """Manages multiple transport instances on the PC side.

    Priority order (highest first): USB > WiFi (WebSocket) > Bluetooth.
    All transports run simultaneously. Only one is "active" for message flow.
    """

    PRIORITY = ['usb', 'websocket', 'bluetooth']

    def __init__(
        self,
        on_message: Callable[[dict[str, Any]], Any],
        on_connected: Callable[[str], Any],       # arg: transport_type
        on_disconnected: Callable[[str], Any],     # arg: transport_type
    ) -> None:
        self._on_message = on_message
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._transports: dict[str, RcTransport] = {}
        self._active_type: Optional[str] = None
        self._preference: str = 'auto'  # 'auto' | 'websocket' | 'bluetooth' | 'usb'

    def make_message_handler(self, transport_type: str) -> Callable[[dict[str, Any]], Any]:
        """Create a message handler that only forwards if this transport is active."""
        def handler(msg: dict[str, Any]) -> None:
            if self._active_type == transport_type:
                self._on_message(msg)
        return handler

    def register(self, transport: RcTransport) -> None:
        self._transports[transport.transport_type] = transport

    @property
    def active(self) -> Optional[RcTransport]:
        if self._active_type:
            return self._transports.get(self._active_type)
        return None

    @property
    def connected(self) -> bool:
        return self.active is not None and self.active.connected

    @property
    def active_type(self) -> Optional[str]:
        return self._active_type

    @property
    def peer_description(self) -> Optional[str]:
        return self.active.peer_description if self.active else None

    async def start_all(self) -> None:
        for t in self._transports.values():
            try:
                await t.start()
            except Exception as exc:
                log.warning("Transport %s failed to start: %s", t.transport_type, exc)

    def stop_all(self) -> None:
        for t in self._transports.values():
            t.stop()

    async def send(self, msg: dict[str, Any]) -> None:
        if self.active and self.active.connected:
            await self.active.send(msg)

    async def send_text(self, text: str) -> None:
        """OutputManager compatibility — calls send_text on active transport."""
        if self.active and self.active.connected:
            await self.active.send_text(text)

    # ── Transport status callbacks ──────────────────────────────────────

    # USB and WebSocket both connect to the same RC WebSocket server,
    # so they conflict and cannot run simultaneously.  Bluetooth is
    # independent and should never be stopped when switching transports.
    _CONFLICTS = {'usb': 'websocket', 'websocket': 'usb'}

    def on_transport_connected(self, transport_type: str) -> None:
        """Called by individual transports when they connect."""
        if self._preference != 'auto':
            if transport_type != self._preference:
                return

        # Check priority — switch if new transport is higher priority
        if self._active_type is None or \
           self.PRIORITY.index(transport_type) < self.PRIORITY.index(self._active_type):
            old = self._active_type
            self._active_type = transport_type
            if old and old != transport_type:
                log.info("Switching active transport: %s -> %s", old, transport_type)
                # Only stop the old transport if it conflicts with the new one
                if self._CONFLICTS.get(transport_type) == old:
                    old_transport = self._transports.get(old)
                    if old_transport:
                        old_transport.stop()
            self._on_connected(transport_type)

    def on_transport_disconnected(self, transport_type: str) -> None:
        """Called by individual transports when they disconnect."""
        if transport_type == self._active_type:
            self._active_type = None
            self._on_disconnected(transport_type)
            # Check if another transport is already connected and fall back to it
            self._fallback_to_next()

    def _fallback_to_next(self) -> None:
        """Activate the highest-priority transport that is already connected."""
        order = self.PRIORITY if self._preference == 'auto' else [self._preference]
        for ttype in order:
            t = self._transports.get(ttype)
            if t and t.connected:
                log.info("Falling back to transport: %s", ttype)
                self._active_type = ttype
                self._on_connected(ttype)
                return
