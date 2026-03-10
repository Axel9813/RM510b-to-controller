"""
Entry point — wires up all components and starts the server.

Architecture: The Python server connects OUT to the RC's WebSocket server.
This avoids Windows firewall issues (outbound TCP is never blocked).

Usage:
    python main.py

Or with custom config file:
    python main.py --config path/to/server.json
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import uvicorn

# ---------------------------------------------------------------------------
# Configure logging before anything else
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Imports (after logging so module-level log messages show up)
# ---------------------------------------------------------------------------
from config_manager import config as cfg
from typing import Optional

from discovery import RcDiscovery, RcEntry, UDP_ANNOUNCE_PORT
from transport import TransportManager, WebSocketTransport, UsbTransport, BluetoothTransport
import server as srv


def _print_startup_banner(web_port: int, rc_port: int) -> None:
    print()
    print("=" * 64)
    print("  DJI RC Controller Server")
    print("=" * 64)
    print(f"  Web UI:         http://localhost:{web_port}/")
    print(f"  Monitor WS:     ws://localhost:{web_port}/ws/monitor")
    print(f"  Profile:        {cfg.active_profile_name()}")
    print(f"  vJoy:           {'active' if srv.vjoy.active else 'not available'}")
    print()
    print("  Connection mode: OUTBOUND (PC connects to RC)")
    print(f"  RC WebSocket port:    {rc_port}")
    print(f"  Listening for RC announcements on UDP port {UDP_ANNOUNCE_PORT}")
    print(f"  USB transport:  bundled ADB (auto-detect + forward)")
    print(f"  Bluetooth:      RFCOMM server (channel 4)")
    print("=" * 64)
    print()


async def _main() -> None:
    parser = argparse.ArgumentParser(description="DJI RC Controller Server")
    parser.add_argument("--config", default=None, help="Path to server.json (optional)")
    parser.parse_args()

    # ------------------------------------------------------------------
    # Load configuration
    # ------------------------------------------------------------------
    cfg.ensure_defaults()
    cfg.load()

    server_cfg = cfg.server_cfg()
    rc_port: int = server_cfg.get("rc_port", 8080)     # RC's WS server port
    web_port: int = server_cfg.get("web_port", 8081)    # local web UI port
    vjoy_device_id: int = server_cfg.get("vjoy_device_id", 1)

    # ------------------------------------------------------------------
    # Register profile-change callback
    # ------------------------------------------------------------------
    cfg.on_profile_changed(srv._on_profile_changed)

    # ------------------------------------------------------------------
    # Initialise vJoy
    # ------------------------------------------------------------------
    srv.vjoy.start(vjoy_device_id)

    # ------------------------------------------------------------------
    # Build InputRouter and OutputManager from active profile
    # ------------------------------------------------------------------
    srv._rebuild_router()
    srv._rebuild_output_manager()

    # ------------------------------------------------------------------
    # Create transport manager
    # ------------------------------------------------------------------

    # We declare discovery early so callbacks can reference it.
    discovery: Optional[RcDiscovery] = None

    transport_mgr = TransportManager(
        on_message=srv.handle_rc_message,
        on_connected=lambda t: _on_connected(t, discovery),
        on_disconnected=lambda t: _on_disconnected(t, discovery),
    )
    srv.set_transport_manager(transport_mgr)

    # Register WebSocket transport
    ws_transport = WebSocketTransport(
        on_message=transport_mgr.make_message_handler('websocket'),
        on_connected=lambda: transport_mgr.on_transport_connected('websocket'),
        on_disconnected=lambda: transport_mgr.on_transport_disconnected('websocket'),
        on_retries_exhausted=lambda: discovery.resume() if discovery else None,
    )
    transport_mgr.register(ws_transport)

    # Register USB/ADB transport (bundled adb.exe)
    usb_transport = UsbTransport(
        on_message=transport_mgr.make_message_handler('usb'),
        on_connected=lambda: transport_mgr.on_transport_connected('usb'),
        on_disconnected=lambda: transport_mgr.on_transport_disconnected('usb'),
        rc_port=rc_port,
    )
    transport_mgr.register(usb_transport)
    await usb_transport.start()

    # Register Bluetooth RFCOMM transport
    bt_transport = BluetoothTransport(
        on_message=transport_mgr.make_message_handler('bluetooth'),
        on_connected=lambda: transport_mgr.on_transport_connected('bluetooth'),
        on_disconnected=lambda: transport_mgr.on_transport_disconnected('bluetooth'),
    )
    transport_mgr.register(bt_transport)
    await bt_transport.start()

    # ------------------------------------------------------------------
    # Start RC discovery — when an RC is found, connect via WiFi
    # ------------------------------------------------------------------
    def _on_rc_found(entry: RcEntry) -> None:
        # Already connected to this RC — skip
        if ws_transport.connected and ws_transport.url == entry.ws_url:
            return
        # Higher-priority transport (USB) is active — don't switch to WiFi
        if transport_mgr.connected and transport_mgr.active_type != 'websocket':
            return
        # Already retrying this same URL — let transport continue
        if not ws_transport.connected and ws_transport.url == entry.ws_url:
            return

        log.info("Connecting to RC: %s", entry)
        ws_transport.start_with_url(entry.ws_url)

    discovery = RcDiscovery(on_rc_found=_on_rc_found, ws_port=rc_port)
    await discovery.start()

    # ------------------------------------------------------------------
    # Print banner
    # ------------------------------------------------------------------
    _print_startup_banner(web_port, rc_port)

    # ------------------------------------------------------------------
    # Start uvicorn (for web UI, REST API, monitor WS only)
    # ------------------------------------------------------------------
    config = uvicorn.Config(
        app=srv.app,
        host="0.0.0.0",
        port=web_port,
        log_level="warning",
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        transport_mgr.stop_all()
        discovery.stop()
        srv.vjoy.stop()
        log.info("Server stopped.")


def _on_connected(transport_type: str, discovery: Optional[RcDiscovery]) -> None:
    srv.on_rc_connected(transport_type)
    if discovery:
        discovery.pause()


def _on_disconnected(transport_type: str, discovery: Optional[RcDiscovery]) -> None:
    srv.on_rc_disconnected(transport_type)
    if discovery:
        discovery.resume()


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nShutdown requested.")
        sys.exit(0)


if __name__ == "__main__":
    main()
