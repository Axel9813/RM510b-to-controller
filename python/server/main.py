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
import platform
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
from rc_client import RcConnection
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
    print(f"  Checking ADB forward tunnel on localhost:{rc_port}")
    print()
    if platform.system() == "Windows":
        print("  ADB setup (optional, for USB):")
        print(f"    adb forward tcp:{rc_port} tcp:{rc_port}")
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
    # Create RC connection (outbound WebSocket client)
    # ------------------------------------------------------------------

    # We declare discovery early so callbacks can reference it.
    discovery: Optional[RcDiscovery] = None

    def _on_connected() -> None:
        srv.on_rc_connected()
        if discovery:
            discovery.pause()

    def _on_disconnected() -> None:
        srv.on_rc_disconnected()
        # rc_client will auto-retry the same URL — don't restart scan yet

    def _on_retries_exhausted() -> None:
        log.info("RC reconnection failing — resuming discovery scan")
        if discovery:
            discovery.resume()

    rc_conn = RcConnection(
        on_message=srv.handle_rc_message,
        on_connected=_on_connected,
        on_disconnected=_on_disconnected,
        on_retries_exhausted=_on_retries_exhausted,
    )
    srv.set_rc_connection(rc_conn)

    # ------------------------------------------------------------------
    # Start RC discovery — when an RC is found, connect to it
    # ------------------------------------------------------------------
    def _on_rc_found(entry: RcEntry) -> None:
        # Already connected to this RC — skip
        if rc_conn.connected and rc_conn.url == entry.ws_url:
            return
        # Connected and working — only ADB can take over
        if rc_conn.connected and entry.method != "adb":
            return
        # Already retrying this same URL — let rc_client continue
        if not rc_conn.connected and rc_conn.url == entry.ws_url and entry.method != "adb":
            return
        # ADB always takes priority over WiFi
        if entry.method == "adb" and rc_conn.connected:
            log.info("ADB tunnel detected — switching from WiFi to USB")
            rc_conn.stop()

        log.info("Connecting to RC: %s", entry)
        rc_conn.start(entry.ws_url)

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
        rc_conn.stop()
        discovery.stop()
        srv.vjoy.stop()
        log.info("Server stopped.")


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nShutdown requested.")
        sys.exit(0)


if __name__ == "__main__":
    main()
