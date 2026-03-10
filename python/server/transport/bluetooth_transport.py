"""Bluetooth RFCOMM server transport — accepts connections from the RC.

The RC connects OUT to this server over Bluetooth RFCOMM.
Uses newline-delimited JSON framing over raw RFCOMM sockets.

On Windows, uses socket.AF_BTH (address family 32) for native Bluetooth.
Accept and read are done in threads because Windows asyncio (IOCP) does
not support AF_BTH sockets.
"""
from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import json
import logging
import socket
import struct
import threading
from typing import Any, Callable, Optional

from .base import RcTransport

log = logging.getLogger(__name__)

# Windows Bluetooth constants
AF_BTH = 32
BTPROTO_RFCOMM = 3

# SPP UUID: 00001101-0000-1000-8000-00805F9B34FB
SPP_UUID = b'\x01\x11\x00\x00\x00\x00\x10\x00\x80\x00\x00\x80\x5f\x9b\x34\xfb'

# WSASetService constants
RNRSERVICE_REGISTER = 0
NS_BTH = 16


def _register_sdp(channel: int) -> bool:
    """Register an SPP SDP service record on Windows via WSASetService."""
    try:
        ws2 = ctypes.windll.ws2_32

        sockaddr = struct.pack('<HH8s16sI',
                               AF_BTH, 0, b'\x00' * 8, SPP_UUID, channel)
        sockaddr_buf = ctypes.create_string_buffer(sockaddr)

        class SOCKET_ADDRESS(ctypes.Structure):
            _fields_ = [('lpSockaddr', ctypes.c_void_p),
                        ('iSockaddrLength', ctypes.c_int)]

        class CSADDR_INFO(ctypes.Structure):
            _fields_ = [('LocalAddr', SOCKET_ADDRESS),
                        ('RemoteAddr', SOCKET_ADDRESS),
                        ('iSocketType', ctypes.c_int),
                        ('iProtocol', ctypes.c_int)]

        class GUID(ctypes.Structure):
            _fields_ = [('Data1', ctypes.c_ulong), ('Data2', ctypes.c_ushort),
                        ('Data3', ctypes.c_ushort), ('Data4', ctypes.c_ubyte * 8)]

        PTR = ctypes.c_void_p
        DWORD = ctypes.c_ulong

        class WSAQUERYSETW(ctypes.Structure):
            _fields_ = [
                ('dwSize', DWORD), ('lpszServiceInstanceName', PTR),
                ('lpServiceClassId', PTR), ('lpVersion', PTR),
                ('lpszComment', PTR), ('dwNameSpace', DWORD),
                ('lpNSProviderId', PTR), ('lpszContext', PTR),
                ('dwNumberOfProtocols', DWORD), ('lpafpProtocols', PTR),
                ('lpszQueryString', PTR), ('dwNumberOfCsAddrs', DWORD),
                ('lpcsaBuffer', PTR), ('dwOutputFlags', DWORD),
                ('lpBlob', PTR),
            ]

        local_addr = SOCKET_ADDRESS()
        local_addr.lpSockaddr = ctypes.cast(sockaddr_buf, PTR)
        local_addr.iSockaddrLength = len(sockaddr)

        csaddr = CSADDR_INFO()
        csaddr.LocalAddr = local_addr
        csaddr.RemoteAddr = local_addr
        csaddr.iSocketType = socket.SOCK_STREAM
        csaddr.iProtocol = BTPROTO_RFCOMM

        spp_guid = GUID(0x00001101, 0x0000, 0x1000,
                        (ctypes.c_ubyte * 8)(0x80, 0x00, 0x00, 0x80, 0x5f, 0x9b, 0x34, 0xfb))

        name_buf = ctypes.create_string_buffer("DJI RC Controller\0".encode('utf-16-le'))

        qs = WSAQUERYSETW()
        qs.dwSize = ctypes.sizeof(WSAQUERYSETW)
        qs.lpszServiceInstanceName = ctypes.cast(name_buf, PTR)
        qs.lpServiceClassId = ctypes.cast(ctypes.pointer(spp_guid), PTR)
        qs.dwNameSpace = NS_BTH
        qs.dwNumberOfCsAddrs = 1
        qs.lpcsaBuffer = ctypes.cast(ctypes.pointer(csaddr), PTR)

        result = ws2.WSASetServiceW(ctypes.pointer(qs), RNRSERVICE_REGISTER, 0)
        if result == 0:
            log.info("SDP service registered (SPP UUID, channel %d)", channel)
            return True
        log.warning("WSASetService failed: error %d", ws2.WSAGetLastError())
        return False
    except Exception as exc:
        log.warning("SDP registration failed: %s", exc)
        return False


class BluetoothTransport(RcTransport):
    """RFCOMM server using threads for accept/read (IOCP doesn't support AF_BTH)."""

    def __init__(
        self,
        on_message: Callable[[dict[str, Any]], Any],
        on_connected: Callable[[], Any],
        on_disconnected: Callable[[], Any],
        channel: int = 4,
    ) -> None:
        super().__init__(on_message, on_connected, on_disconnected)
        self._channel = channel
        self._server_sock: Optional[socket.socket] = None
        self._client_sock: Optional[socket.socket] = None
        self._client_addr: Optional[str] = None
        self._client_lock = threading.Lock()
        self._running = False
        self._accept_thread: Optional[threading.Thread] = None
        self._read_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def transport_type(self) -> str:
        return 'bluetooth'

    @property
    def connected(self) -> bool:
        return self._client_sock is not None

    @property
    def peer_description(self) -> Optional[str]:
        if self._client_addr:
            return f"BT ({self._client_addr})"
        return None

    async def start(self) -> None:
        """Bind RFCOMM server socket, register SDP, start accept thread."""
        self._loop = asyncio.get_event_loop()
        try:
            self._server_sock = socket.socket(AF_BTH, socket.SOCK_STREAM, BTPROTO_RFCOMM)
            # Keep blocking for thread-based accept
            self._server_sock.settimeout(2.0)
            self._server_sock.bind(("00:00:00:00:00:00", self._channel))
            self._server_sock.listen(1)
            self._running = True

            _register_sdp(self._channel)

            self._accept_thread = threading.Thread(
                target=self._accept_loop, daemon=True, name="BT-Accept")
            self._accept_thread.start()
            log.info("Bluetooth RFCOMM server listening on channel %d", self._channel)
        except OSError as exc:
            log.warning("Bluetooth not available: %s", exc)
            self._cleanup_server()

    def stop(self) -> None:
        self._running = False
        self._close_client()
        self._cleanup_server()

    async def send(self, msg: dict[str, Any]) -> None:
        await self._send_line_async(json.dumps(msg) + '\n')

    async def send_text(self, text: str) -> None:
        await self._send_line_async(text.rstrip('\n') + '\n')

    async def _send_line_async(self, line: str) -> None:
        loop = self._loop or asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send_line, line)

    def _send_line(self, line: str) -> None:
        with self._client_lock:
            sock = self._client_sock
        if sock is None:
            return
        try:
            sock.sendall(line.encode('utf-8'))
        except Exception as exc:
            log.warning("BT send error: %s", exc)
            # Don't close/notify here — the read thread will detect
            # the broken connection and handle cleanup + notification.

    # ── Thread: accept loop ──────────────────────────────────────────────

    def _accept_loop(self) -> None:
        """Accept incoming RFCOMM connections (runs in thread)."""
        while self._running and self._server_sock is not None:
            try:
                client_sock, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    log.debug("BT accept error")
                break

            # Close previous client
            self._close_client()

            addr_str = str(addr[0]) if isinstance(addr, tuple) else str(addr)
            log.info("Bluetooth client connected: %s", addr_str)

            with self._client_lock:
                self._client_sock = client_sock
                self._client_addr = addr_str

            # Notify on the asyncio loop
            if self._loop:
                self._loop.call_soon_threadsafe(self._on_connected)

            # Read until disconnected
            self._read_from_client(client_sock)

            # Client disconnected
            log.info("Bluetooth client disconnected.")
            with self._client_lock:
                if self._client_sock is client_sock:
                    self._client_sock = None
                    self._client_addr = None
            if self._loop and self._running:
                self._loop.call_soon_threadsafe(self._on_disconnected)

    def _read_from_client(self, sock: socket.socket) -> None:
        """Read newline-delimited JSON from client (runs in thread).

        For rc_state messages (sent at 50 Hz), only the latest from each
        recv batch is dispatched to avoid flooding the asyncio event loop.
        """
        buf = ''
        sock.settimeout(0.1)
        while self._running:
            try:
                data = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            if not data:
                break  # EOF

            buf += data.decode('utf-8', errors='replace')

            latest_state = None
            while '\n' in buf:
                line, buf = buf.split('\n', 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    msg_type = msg.get('type')
                    if msg_type == 'rc_state':
                        latest_state = msg  # keep only newest
                    elif msg_type == 'ping':
                        # Reply immediately from read thread
                        self._send_line('{"type":"pong"}\n')
                    elif self._loop:
                        self._loop.call_soon_threadsafe(self._on_message, msg)
                except json.JSONDecodeError:
                    log.debug("BT invalid JSON: %s", line[:100])

            # Dispatch only the latest rc_state from this batch
            if latest_state is not None and self._loop:
                self._loop.call_soon_threadsafe(self._on_message, latest_state)

    # ── Cleanup ──────────────────────────────────────────────────────────

    def _close_client(self) -> None:
        with self._client_lock:
            sock = self._client_sock
            self._client_sock = None
            self._client_addr = None
        if sock:
            try:
                sock.close()
            except Exception:
                pass

    def _cleanup_server(self) -> None:
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
        self._server_sock = None
