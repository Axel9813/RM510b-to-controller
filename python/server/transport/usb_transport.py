"""USB transport — auto-detects RC via bundled ADB, sets up port forwarding,
and delegates data flow to an internal WebSocketTransport.

The bundled adb.exe + DLLs live in ../adb/ relative to this file.
No ADB installation required on the target PC — the driver for the DJI RC's
ADB interface auto-installs on Windows.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

from .base import RcTransport
from .websocket_transport import WebSocketTransport

log = logging.getLogger(__name__)

# Path to bundled adb.exe
_ADB_DIR = Path(__file__).resolve().parent.parent / "adb"
_ADB_EXE = str(_ADB_DIR / "adb.exe")

_POLL_INTERVAL = 3.0  # seconds between ADB device checks


class UsbTransport(RcTransport):
    """Auto-detect RC via ADB, forward port, connect via WebSocket.

    This is a composite transport: it manages the ADB polling loop and
    internally delegates data transport to a WebSocketTransport connected
    to localhost.
    """

    def __init__(
        self,
        on_message: Callable[[dict[str, Any]], Any],
        on_connected: Callable[[], Any],
        on_disconnected: Callable[[], Any],
        rc_port: int = 8080,
    ) -> None:
        super().__init__(on_message, on_connected, on_disconnected)
        self._rc_port = rc_port
        self._adb_device: Optional[str] = None
        self._ws_transport: Optional[WebSocketTransport] = None
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._adb_available: Optional[bool] = None

    @property
    def transport_type(self) -> str:
        return 'usb'

    @property
    def connected(self) -> bool:
        return self._ws_transport is not None and self._ws_transport.connected

    @property
    def peer_description(self) -> Optional[str]:
        if self._adb_device:
            return f"USB ({self._adb_device})"
        return None

    async def start(self) -> None:
        if not os.path.isfile(_ADB_EXE):
            log.warning("Bundled adb.exe not found at %s — USB transport disabled.", _ADB_EXE)
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._adb_poll_loop())
        log.info("USB transport started (polling for ADB devices).")

    def stop(self) -> None:
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._poll_task = None
        if self._ws_transport:
            self._ws_transport.stop()
            self._ws_transport = None
        self._adb_device = None

    async def send(self, msg: dict[str, Any]) -> None:
        if self._ws_transport:
            await self._ws_transport.send(msg)

    async def send_text(self, text: str) -> None:
        if self._ws_transport:
            await self._ws_transport.send_text(text)

    # ── ADB polling ─────────────────────────────────────────────────────

    async def _adb_poll_loop(self) -> None:
        while self._running:
            try:
                device = await self._detect_adb_device()
                if device and device != self._adb_device:
                    # New device detected
                    self._adb_device = device
                    await self._setup_forward(device)
                    await self._connect_ws()
                elif device and device == self._adb_device and not self.connected:
                    # Same device but WS dropped — reconnect
                    await self._setup_forward(device)
                    await self._connect_ws()
                elif not device and self._adb_device:
                    # Device removed
                    log.info("USB device removed.")
                    self._adb_device = None
                    if self._ws_transport:
                        self._ws_transport.stop()
                        self._ws_transport = None
                        self._on_disconnected()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.debug("ADB poll error: %s", exc)

            try:
                await asyncio.sleep(_POLL_INTERVAL)
            except asyncio.CancelledError:
                break

    async def _detect_adb_device(self) -> Optional[str]:
        """Run `adb devices` and find a connected device."""
        try:
            proc = await asyncio.create_subprocess_exec(
                _ADB_EXE, 'devices',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, 'PATH': str(_ADB_DIR) + os.pathsep + os.environ.get('PATH', '')},
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)

            if self._adb_available is None:
                self._adb_available = True
                log.info("Bundled ADB is available.")

            for line in stdout.decode(errors='replace').strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == 'device':
                    return parts[0]
        except FileNotFoundError:
            if self._adb_available is None:
                self._adb_available = False
                log.warning("adb.exe not found — USB transport disabled.")
        except asyncio.TimeoutError:
            log.debug("adb devices timed out.")
        except Exception as exc:
            log.debug("adb devices error: %s", exc)
        return None

    async def _setup_forward(self, device: str) -> None:
        """Run `adb -s {device} forward tcp:{port} tcp:{port}`."""
        try:
            proc = await asyncio.create_subprocess_exec(
                _ADB_EXE, '-s', device, 'forward',
                f'tcp:{self._rc_port}', f'tcp:{self._rc_port}',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, 'PATH': str(_ADB_DIR) + os.pathsep + os.environ.get('PATH', '')},
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if proc.returncode == 0:
                log.info("ADB forward: localhost:%d -> RC:%d (device %s)",
                         self._rc_port, self._rc_port, device)
            else:
                log.warning("ADB forward failed: %s", stderr.decode(errors='replace').strip())
        except Exception as exc:
            log.warning("ADB forward error: %s", exc)

    async def _connect_ws(self) -> None:
        """Connect to the RC via the ADB-forwarded localhost port."""
        # Stop existing WS if any
        if self._ws_transport:
            self._ws_transport.stop()

        self._ws_transport = WebSocketTransport(
            on_message=self._on_message,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
        )
        self._ws_transport.start_with_url(f"ws://127.0.0.1:{self._rc_port}")
