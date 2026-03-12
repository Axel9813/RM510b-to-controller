"""
FastAPI application — REST API and browser monitor WebSocket.

The RC connection is handled by transport/ (pluggable transport layer).

Connections:
  /ws/monitor  — Browser monitor WebSocket (read-only, 20 Hz broadcast)

REST:
  /api/status
  /api/profiles/*
  /api/config/mappings
  /api/config/elements
  /api/outputs/{id}/toggle|set
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from transport import TransportManager

from config_manager import config as cfg
from input_router import InputRouter
from output_manager import OutputManager
from system_actions import SystemActions
from vjoy_handler import VJoyHandler

log = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"

# ---------------------------------------------------------------------------
# Shared singletons (initialised in main.py before uvicorn starts)
# ---------------------------------------------------------------------------
vjoy = VJoyHandler()
sys_actions = SystemActions()
input_router: InputRouter = None  # type: ignore[assignment]
output_mgr: OutputManager = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------
_transport_mgr: Optional[TransportManager] = None
_last_rc_state: dict[str, Any] = {}
_rc_connected: bool = False
_monitor_clients: set[WebSocket] = set()
_last_seq: int = 0


def set_transport_manager(mgr: Optional[TransportManager]) -> None:
    """Register the transport manager (called from main.py)."""
    global _transport_mgr
    _transport_mgr = mgr


def on_rc_connected(transport_type: str) -> None:
    """Called by TransportManager when any transport connects to the RC."""
    global _rc_connected
    _rc_connected = True
    if _transport_mgr is not None:
        output_mgr.set_rc_websocket(_transport_mgr)
    log.info("RC connected via %s.", transport_type)


def on_rc_disconnected(transport_type: str) -> None:
    """Called by TransportManager when the active transport disconnects."""
    global _rc_connected, _last_rc_state
    _rc_connected = False
    _last_rc_state = {}
    output_mgr.set_rc_websocket(None)
    log.info("RC disconnected (was %s).", transport_type)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="DJI RC Controller Server")

# Serve frontend static files (JS, CSS)
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _startup() -> None:
    asyncio.create_task(_monitor_broadcast_loop())
    log.info("Monitor broadcast task started.")


@app.on_event("shutdown")
async def _shutdown() -> None:
    vjoy.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rebuild_router() -> None:
    """Re-instantiate InputRouter from current active profile mappings."""
    global input_router
    input_router = InputRouter(
        cfg.input_mappings(), vjoy, sys_actions,
        gyro_config=cfg.gyro_config(),
        pico_hardware=cfg.pico_hardware(),
    )
    log.info("InputRouter rebuilt from profile '%s'.", cfg.active_profile_name())


def _rebuild_output_manager() -> None:
    """Re-instantiate OutputManager from current active profile registry."""
    global output_mgr
    output_mgr = OutputManager(vjoy, sys_actions)
    output_mgr.load(
        registry=cfg.element_registry(),
        save_cb=cfg.save_active_profile,
        notify_monitor_cb=_notify_monitors_registry,
    )
    if _transport_mgr and _transport_mgr.connected:
        output_mgr.set_rc_websocket(_transport_mgr)
    log.info("OutputManager loaded profile '%s'.", cfg.active_profile_name())


def _on_profile_changed() -> None:
    _rebuild_router()
    _rebuild_output_manager()


def _notify_monitors_registry(msg: dict[str, Any]) -> None:
    """Schedule a registry_update broadcast to all monitor clients."""
    asyncio.ensure_future(_broadcast_to_monitors(json.dumps(msg)))


async def _broadcast_to_monitors(text: str) -> None:
    dead: set[WebSocket] = set()
    for ws in list(_monitor_clients):
        try:
            await ws.send_text(text)
        except Exception:
            dead.add(ws)
    _monitor_clients.difference_update(dead)


async def _monitor_broadcast_loop() -> None:
    """Broadcast rc_state + connection status to browser monitor at 20 Hz."""
    while True:
        await asyncio.sleep(0.05)
        if not _monitor_clients:
            continue
        msg = json.dumps({
            "type": "monitor_update",
            "rc_connected": _rc_connected,
            "vjoy_active": vjoy.active,
            "vjoy_error": vjoy.error,
            "rc_state": _last_rc_state,
            "transport_type": _transport_mgr.active_type if _transport_mgr else None,
        })
        await _broadcast_to_monitors(msg)


# ---------------------------------------------------------------------------
# RC message handler (called by transport layer)
# ---------------------------------------------------------------------------

def handle_rc_message(msg: dict[str, Any]) -> None:
    """Process an incoming message from the RC.
    Called synchronously from transport layer's message callback.
    """
    global _last_rc_state, _last_seq

    msg_type = msg.get("type")

    if msg_type == "rc_state":
        _last_rc_state = msg
        _last_seq = int(msg.get("seq", 0))
        input_router.process(msg)

    elif msg_type == "element_event":
        output_mgr.handle_element_event(msg)

    elif msg_type == "ping":
        # Application-level ping — reply with pong
        if _transport_mgr is not None:
            asyncio.ensure_future(_transport_mgr.send({"type": "pong"}))

    elif msg_type == "hello":
        elements = msg.get("elements", [])
        grid_cols = msg.get("gridCols", 0)
        grid_rows = msg.get("gridRows", 0)
        changed = output_mgr.merge_hello(elements, grid_cols=grid_cols, grid_rows=grid_rows)
        # Respond with full LED state
        if _transport_mgr is not None:
            asyncio.ensure_future(_transport_mgr.send({
                "type": "elements_full_state",
                "states": output_mgr.get_full_state(),
            }))
        if changed:
            gc, gr = output_mgr.get_grid_size()
            asyncio.ensure_future(_broadcast_to_monitors(json.dumps({
                "type": "registry_update",
                "registry": output_mgr.get_registry(),
                "grid_cols": gc,
                "grid_rows": gr,
            })))
        log.info("hello processed: %d elements registered.", len(elements))

    else:
        log.debug("Unknown RC message type: %s", msg_type)


# ---------------------------------------------------------------------------
# WebSocket — Browser monitor
# ---------------------------------------------------------------------------

@app.websocket("/ws/monitor")
async def ws_monitor(websocket: WebSocket) -> None:
    await websocket.accept()
    _monitor_clients.add(websocket)

    # Send initial state immediately
    grid_cols, grid_rows = output_mgr.get_grid_size()
    await websocket.send_text(json.dumps({
        "type": "initial_state",
        "rc_connected": _rc_connected,
        "transport_type": _transport_mgr.active_type if _transport_mgr else None,
        "vjoy_active": vjoy.active,
        "vjoy_error": vjoy.error,
        "rc_state": _last_rc_state,
        "registry": output_mgr.get_registry(),
        "grid_cols": grid_cols,
        "grid_rows": grid_rows,
        "active_profile": cfg.active_profile_name(),
        "profiles": cfg.list_profiles(),
    }))

    try:
        while True:
            # Wait for disconnect (or a keep-alive ping from client)
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                pass  # just loop
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _monitor_clients.discard(websocket)


# ---------------------------------------------------------------------------
# REST — Static / Root
# ---------------------------------------------------------------------------

@app.get("/")
async def serve_index() -> FileResponse:
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ---------------------------------------------------------------------------
# REST — Status
# ---------------------------------------------------------------------------

@app.get("/api/status")
async def api_status() -> JSONResponse:
    grid_cols, grid_rows = output_mgr.get_grid_size()
    return JSONResponse({
        "rc_connected": _rc_connected,
        "last_seq": _last_seq,
        "vjoy_active": vjoy.active,
        "vjoy_error": vjoy.error,
        "active_profile": cfg.active_profile_name(),
        "profiles": cfg.list_profiles(),
        "mappings": cfg.input_mappings(),
        "gyro_config": cfg.gyro_config(),
        "pico_hardware": cfg.pico_hardware(),
        "elements": output_mgr.get_registry() if output_mgr else {},
        "grid_cols": grid_cols,
        "grid_rows": grid_rows,
    })


# ---------------------------------------------------------------------------
# REST — Profiles
# ---------------------------------------------------------------------------

@app.get("/api/profiles")
async def api_list_profiles() -> JSONResponse:
    return JSONResponse({
        "profiles": cfg.list_profiles(),
        "active": cfg.active_profile_name(),
    })


@app.post("/api/profiles")
async def api_create_profile(body: dict[str, Any]) -> JSONResponse:
    name = body.get("name", "").strip()
    clone_from = body.get("clone_from")
    if not name:
        raise HTTPException(400, "Profile name required.")
    try:
        cfg.create_profile(name, clone_from=clone_from)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return JSONResponse({"status": "created", "name": name})


@app.delete("/api/profiles/{name}")
async def api_delete_profile(name: str) -> JSONResponse:
    try:
        cfg.delete_profile(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return JSONResponse({"status": "deleted", "name": name})


@app.post("/api/profiles/{name}/activate")
async def api_activate_profile(name: str) -> JSONResponse:
    try:
        cfg.activate_profile(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    # _on_profile_changed() was called by config_manager via callback
    return JSONResponse({
        "status": "activated",
        "name": name,
        "registry": output_mgr.get_registry(),
    })


@app.get("/api/profiles/{name}")
async def api_get_profile(name: str) -> JSONResponse:
    try:
        data = cfg.load_profile(name)
    except Exception as exc:
        raise HTTPException(404, str(exc))
    return JSONResponse(data)


@app.put("/api/profiles/{name}")
async def api_put_profile(name: str, body: dict[str, Any]) -> JSONResponse:
    cfg.save_profile(name, body)
    if name == cfg.active_profile_name():
        _on_profile_changed()
    return JSONResponse({"status": "saved", "name": name})


# ---------------------------------------------------------------------------
# REST — Input Mappings
# ---------------------------------------------------------------------------

@app.get("/api/config/mappings")
async def api_get_mappings() -> JSONResponse:
    return JSONResponse(cfg.input_mappings())


@app.patch("/api/config/mappings")
async def api_patch_mappings(body: dict[str, Any]) -> JSONResponse:
    """Merge mapping updates into the current mappings."""
    current = cfg.input_mappings()
    current.update(body)
    cfg.set_input_mappings(current)
    input_router.reload(current)
    return JSONResponse({"status": "saved"})


@app.post("/api/config/mappings")
async def api_set_mappings(body: dict[str, Any]) -> JSONResponse:
    """Full replace of all mappings."""
    cfg.set_input_mappings(body)
    input_router.reload(body)
    return JSONResponse({"status": "saved"})


# ---------------------------------------------------------------------------
# REST — Gyro Config
# ---------------------------------------------------------------------------

@app.get("/api/config/gyro")
async def api_get_gyro_config() -> JSONResponse:
    return JSONResponse(cfg.gyro_config())


@app.patch("/api/config/gyro")
async def api_patch_gyro_config(body: dict[str, Any]) -> JSONResponse:
    current = cfg.gyro_config()
    # Deep merge: update nested axis dicts without clobbering siblings
    for key, val in body.items():
        if isinstance(val, dict) and isinstance(current.get(key), dict):
            current[key].update(val)
        else:
            current[key] = val
    cfg.set_gyro_config(current)
    input_router.reload_gyro_config(current)
    return JSONResponse({"status": "saved", "gyro_config": current})


@app.post("/api/gyro/zero")
async def api_gyro_zero() -> JSONResponse:
    """Forward gyro zero/calibrate command to the RC."""
    if _transport_mgr and _transport_mgr.connected:
        await _transport_mgr.send({"type": "gyro_zero"})
        return JSONResponse({"status": "ok"})
    raise HTTPException(503, "RC not connected")


@app.post("/api/gyro/sensor-type")
async def api_gyro_sensor_type(body: dict[str, Any]) -> JSONResponse:
    """Forward sensor type change to the RC."""
    sensor_type = body.get("sensor_type", "game")
    if _transport_mgr and _transport_mgr.connected:
        await _transport_mgr.send({"type": "gyro_set_sensor", "sensor_type": sensor_type})
        # Also update config
        gyro = cfg.gyro_config()
        gyro["sensor_type"] = sensor_type
        cfg.set_gyro_config(gyro)
        input_router.reload_gyro_config(gyro)
        return JSONResponse({"status": "ok"})
    raise HTTPException(503, "RC not connected")


# ---------------------------------------------------------------------------
# REST — Element Registry
# ---------------------------------------------------------------------------

@app.get("/api/config/elements")
async def api_get_elements() -> JSONResponse:
    return JSONResponse(output_mgr.get_registry())


@app.patch("/api/config/elements")
async def api_patch_elements(body: dict[str, Any]) -> JSONResponse:
    """Bulk-update element registry entries. Body: {element_id: {...}, ...}"""
    reg = output_mgr.get_registry()
    for element_id, updates in body.items():
        if element_id in reg:
            reg[element_id].update(updates)
            cfg.update_element(element_id, reg[element_id])
    return JSONResponse({"status": "saved"})


@app.post("/api/config/elements/{element_id}")
async def api_update_element(element_id: str, body: dict[str, Any]) -> JSONResponse:
    reg = output_mgr.get_registry()
    if element_id not in reg:
        raise HTTPException(404, f"Element '{element_id}' not found.")
    cfg.update_element(element_id, body)
    # Reflect in live registry
    reg[element_id] = body
    return JSONResponse({"status": "saved"})


# ---------------------------------------------------------------------------
# REST — Outputs (LED toggle/set)
# ---------------------------------------------------------------------------

@app.post("/api/outputs/{element_id}/toggle")
async def api_toggle_output(element_id: str) -> JSONResponse:
    new_val = output_mgr.toggle(element_id)
    if new_val is None:
        raise HTTPException(404, f"LED element '{element_id}' not found.")
    return JSONResponse({"id": element_id, "state": new_val, "value": new_val})


@app.post("/api/outputs/{element_id}/set")
async def api_set_output(element_id: str, body: dict[str, Any]) -> JSONResponse:
    value = body.get("value", False)
    ok = output_mgr.set_value(element_id, value)
    if not ok:
        raise HTTPException(404, f"LED element '{element_id}' not found.")
    return JSONResponse({"id": element_id, "value": value})
