"""Abstract base class for all PC-side transports."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional


class RcTransport(ABC):
    """Abstract base for all PC-side transports.

    Each transport is responsible for:
      - Connecting to or accepting a connection from the RC
      - Receiving messages and dispatching via on_message callback
      - Sending messages (pong, element_update, etc.)
      - Notifying on connect/disconnect
    """

    def __init__(
        self,
        on_message: Callable[[dict[str, Any]], Any],
        on_connected: Callable[[], Any],
        on_disconnected: Callable[[], Any],
    ) -> None:
        self._on_message = on_message
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected

    @property
    @abstractmethod
    def transport_type(self) -> str:
        """Return 'websocket', 'bluetooth', or 'usb'."""
        ...

    @property
    @abstractmethod
    def connected(self) -> bool:
        ...

    @property
    @abstractmethod
    def peer_description(self) -> Optional[str]:
        """Human-readable description of the connected peer."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start the transport (connect, listen, etc.)."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop the transport and disconnect."""
        ...

    @abstractmethod
    async def send(self, msg: dict[str, Any]) -> None:
        """Send a JSON message to the RC."""
        ...

    async def send_text(self, text: str) -> None:
        """send_text compatibility (used by OutputManager).

        OutputManager calls ws.send_text(json.dumps(msg)).
        This default delegates to send().
        """
        await self.send(json.loads(text))
