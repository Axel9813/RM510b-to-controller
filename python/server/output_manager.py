"""
Output manager — tracks LED element states, merges the Flutter 'hello'
registry, dispatches element_event actions, and pushes updates to the RC.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional

from system_actions import SystemActions
from gamepad_output import GamepadOutput

log = logging.getLogger(__name__)


class OutputManager:
    def __init__(
        self,
        gamepad: GamepadOutput,
        sys_actions: SystemActions,
    ) -> None:
        self._gamepad = gamepad
        self._sys = sys_actions

        # element_registry section from active profile: {id: {...}}
        self._registry: dict[str, Any] = {}

        # Grid dimensions reported by the RC (visible cols × rows)
        self._grid_cols: int = 0
        self._grid_rows: int = 0

        # Callback to persist changes back to the active profile on disk
        self._save_cb: Optional[Callable[[], None]] = None

        # Callback to notify browser monitor clients of registry changes
        self._notify_monitor_cb: Optional[Callable[[dict[str, Any]], None]] = None

        # Active RC WebSocket (FastAPI WebSocket object)
        self._rc_ws: Optional[Any] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(
        self,
        registry: dict[str, Any],
        save_cb: Callable[[], None],
        notify_monitor_cb: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        """
        Load element registry from the active profile.

        Args:
            registry: the element_registry dict from the active profile.
            save_cb: called whenever the registry is mutated (to persist to disk).
            notify_monitor_cb: called with a message dict to push to browser clients.
        """
        self._registry = registry
        self._save_cb = save_cb
        self._notify_monitor_cb = notify_monitor_cb

    def set_rc_websocket(self, ws: Optional[Any]) -> None:
        """Register (or clear) the active RC WebSocket connection."""
        self._rc_ws = ws

    # ------------------------------------------------------------------
    # Registry / hello merge
    # ------------------------------------------------------------------

    def merge_hello(self, elements: list[dict[str, Any]],
                    grid_cols: int = 0, grid_rows: int = 0) -> bool:
        """
        Merge elements received from the Flutter 'hello' message.
        New unknown IDs are added with safe defaults.
        IDs not present in the hello are removed (element was deleted on RC).
        Existing entries are NOT overwritten (except display_name).
        Returns True if the registry changed.
        """
        if grid_cols > 0:
            self._grid_cols = grid_cols
        if grid_rows > 0:
            self._grid_rows = grid_rows
        changed = False
        incoming_ids: set[str] = set()

        for elem in elements:
            eid = elem.get("id")
            if not eid:
                continue
            incoming_ids.add(eid)

            # Grid position fields — always update (user may have moved elements)
            grid = {
                "grid_x": elem.get("gridX", 0),
                "grid_y": elem.get("gridY", 0),
                "grid_w": elem.get("gridW", 3),
                "grid_h": elem.get("gridH", 2),
            }

            if eid in self._registry:
                # Update display name and grid position, keep action config
                existing = self._registry[eid]
                new_name = elem.get("displayName", eid)
                if existing.get("display_name") != new_name:
                    existing["display_name"] = new_name
                    changed = True
                for k, v in grid.items():
                    if existing.get(k) != v:
                        existing[k] = v
                        changed = True
                continue

            etype = elem.get("elementType", "button")
            entry: dict[str, Any] = {
                "display_name": elem.get("displayName", eid),
                "element_type": etype,
                **grid,
            }
            if etype == "led":
                entry["current_value"] = False
                entry["trigger"] = "manual"
            elif etype == "button":
                entry["on_press"] = {"action": "none"}
                entry["on_release"] = {"action": "none"}
            elif etype == "slider":
                entry["on_change"] = {"action": "none"}

            self._registry[eid] = entry
            changed = True
            log.info("Registered new element: %s (%s)", eid, etype)

        # Remove elements that no longer exist on the RC
        stale_ids = set(self._registry.keys()) - incoming_ids
        for eid in stale_ids:
            log.info("Removed stale element: %s", eid)
            del self._registry[eid]
            changed = True

        if changed and self._save_cb:
            self._save_cb()
        return changed

    # ------------------------------------------------------------------
    # State accessors
    # ------------------------------------------------------------------

    def get_full_state(self) -> dict[str, Any]:
        """
        Return {element_id: value} for all LED elements.
        Used to populate elements_full_state on RC connection.
        """
        return {
            eid: entry.get("current_value", False)
            for eid, entry in self._registry.items()
            if entry.get("element_type") == "led"
        }

    def get_registry(self) -> dict[str, Any]:
        """Return a copy of the full registry (for API responses)."""
        return dict(self._registry)

    def get_grid_size(self) -> tuple[int, int]:
        """Return (cols, rows) of the RC screen grid."""
        return self._grid_cols, self._grid_rows

    # ------------------------------------------------------------------
    # LED control
    # ------------------------------------------------------------------

    def toggle(self, element_id: str) -> Optional[bool]:
        """Toggle a LED and return the new value, or None if not found."""
        entry = self._registry.get(element_id)
        if entry is None or entry.get("element_type") != "led":
            return None
        new_val = not bool(entry.get("current_value", False))
        entry["current_value"] = new_val
        if self._save_cb:
            self._save_cb()
        self._schedule_push_to_rc({"type": "element_update", "id": element_id, "value": new_val})
        self._notify_monitors_state(element_id, new_val)
        return new_val

    def set_value(self, element_id: str, value: Any) -> bool:
        """Set a LED value. Returns True on success."""
        entry = self._registry.get(element_id)
        if entry is None or entry.get("element_type") != "led":
            return False
        entry["current_value"] = value
        if self._save_cb:
            self._save_cb()
        self._schedule_push_to_rc({"type": "element_update", "id": element_id, "value": value})
        self._notify_monitors_state(element_id, value)
        return True

    # ------------------------------------------------------------------
    # Element event dispatching (from Flutter buttons/sliders)
    # ------------------------------------------------------------------

    def handle_element_event(self, event: dict[str, Any]) -> None:
        """
        Route an element_event from the RC app to the configured action.
        Events: press, release (buttons) | change (sliders).
        Also broadcasts element state to browser monitor clients.
        """
        eid = event.get("id", "")
        ev_type = event.get("event", "")
        entry = self._registry.get(eid)
        if entry is None:
            log.debug("element_event for unknown id '%s'", eid)
            return

        etype = entry.get("element_type", "button")

        if etype == "button":
            if ev_type == "press":
                self._dispatch_action(entry.get("on_press", {"action": "none"}), value=1.0)
                self._notify_monitors_state(eid, True)
            elif ev_type == "release":
                self._dispatch_action(entry.get("on_release", {"action": "none"}), value=0.0)
                self._notify_monitors_state(eid, False)

        elif etype == "slider":
            if ev_type == "change":
                slider_val = float(event.get("value", 0.0))
                self._dispatch_action(entry.get("on_change", {"action": "none"}), value=slider_val)
                self._notify_monitors_state(eid, slider_val)

        elif etype == "led":
            # LED can also receive press/release if wired to something
            if ev_type == "press":
                self._dispatch_action(entry.get("on_press", {"action": "none"}), value=1.0)

    # ------------------------------------------------------------------
    # Push to RC WebSocket
    # ------------------------------------------------------------------

    async def push_to_rc(self, msg: dict[str, Any]) -> None:
        """Async: send a message to the connected RC WebSocket."""
        ws = self._rc_ws
        if ws is None:
            return
        try:
            await ws.send_text(json.dumps(msg))
        except Exception as exc:
            log.debug("push_to_rc failed: %s", exc)

    def _notify_monitors_state(self, element_id: str, value: Any) -> None:
        """Broadcast an element state change to all browser monitor clients."""
        if self._notify_monitor_cb:
            self._notify_monitor_cb({
                "type": "element_state_update",
                "id": element_id,
                "value": value,
            })

    def _schedule_push_to_rc(self, msg: dict[str, Any]) -> None:
        """
        Schedule a push_to_rc coroutine on the running event loop.
        Safe to call from synchronous code.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.push_to_rc(msg))
        except Exception as exc:
            log.debug("_schedule_push_to_rc: %s", exc)

    # ------------------------------------------------------------------
    # Internal action dispatcher
    # ------------------------------------------------------------------

    def _dispatch_action(self, mapping: dict[str, Any], value: float = 0.0) -> None:
        action = mapping.get("action", "none")
        if action == "none":
            return
        if action == "vjoy_button":
            btn = int(mapping.get("button", 1))
            self._gamepad.set_button(btn, value > 0.5)
        elif action == "vjoy_axis":
            axis = mapping.get("axis", "X")
            invert = bool(mapping.get("invert", False))
            # Slider 0.0-1.0 → RC-equivalent ±660
            rc_val = int((value - 0.5) * 2 * 660)
            self._gamepad.set_axis(axis, rc_val, invert)
        elif action == "key":
            keys: list[str] = mapping.get("keys", [])
            self._sys.send_key_combo(keys, pressed=True)
        elif action == "system":
            fn = mapping.get("fn", "")
            self._sys.execute(fn, value=value)
        else:
            log.debug("Unknown action in element dispatch: %s", action)
