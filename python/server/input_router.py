"""
Input router — maps incoming rc_state fields to configured actions.

Responsibilities:
  - Decode the picoBitmask into individual boolean input fields
  - Compare each field against the previous state to detect edges
  - Dispatch axis values and button press/release events to
    VJoyHandler or SystemActions according to the active input_mappings
"""
from __future__ import annotations

import logging
from typing import Any

from vjoy_handler import VJoyHandler
from system_actions import SystemActions

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field classification
# ---------------------------------------------------------------------------

# Axis fields: continuous signed int values (±660)
AXIS_FIELDS: frozenset[str] = frozenset({
    "stickLeftH", "stickLeftV",
    "stickRightH", "stickRightV",
    "leftWheel", "rightWheel",
})

# Button fields available via USB HID (Phase 1)
HID_BUTTON_FIELDS: frozenset[str] = frozenset({
    "record",
    "fiveDUp", "fiveDDown", "fiveDLeft", "fiveDRight", "fiveDCenter",
})

# Button fields provided by the Raspberry Pi Pico (Phase 3)
PICO_BUTTON_FIELDS: frozenset[str] = frozenset({
    "pico_c1", "pico_c2",
    "pico_shutter_half",   # bit 2 — triggers AF / half-press
    "pico_shutter_full",   # bit 9 — full shutter press
    "pico_pause", "pico_rth",
    "pico_switch_f", "pico_switch_s",
    "pico_circle", "pico_arrow",
})

BUTTON_FIELDS: frozenset[str] = HID_BUTTON_FIELDS | PICO_BUTTON_FIELDS

# picoBitmask bit positions → pico field name
_PICO_BIT_MAP: list[str] = [
    "pico_c1",           # bit 0
    "pico_c2",           # bit 1
    "pico_shutter_half", # bit 2 — half-press (AF)
    "pico_pause",        # bit 3
    "pico_rth",          # bit 4
    "pico_switch_f",     # bit 5
    "pico_switch_s",     # bit 6
    "pico_circle",       # bit 7
    "pico_arrow",        # bit 8
    "pico_shutter_full", # bit 9 — full shutter press
]


def decode_pico_bitmask(bitmask: int) -> dict[str, bool]:
    """Expand the 16-bit picoBitmask into individual named boolean fields."""
    result: dict[str, bool] = {}
    for bit, name in enumerate(_PICO_BIT_MAP):
        result[name] = bool(bitmask & (1 << bit))
    return result


# ---------------------------------------------------------------------------
# InputRouter
# ---------------------------------------------------------------------------

class InputRouter:
    def __init__(
        self,
        mappings: dict[str, Any],
        vjoy: VJoyHandler,
        sys_actions: SystemActions,
    ) -> None:
        self._mappings = mappings
        self._vjoy = vjoy
        self._sys = sys_actions
        # Previous flattened state for edge detection
        self._prev: dict[str, Any] = {}

    def reload(self, mappings: dict[str, Any]) -> None:
        """Hot-reload mappings without losing previous state."""
        self._mappings = mappings
        log.info("InputRouter: mappings reloaded.")

    def process(self, rc_state: dict[str, Any]) -> None:
        """
        Process one rc_state message.
        Decodes picoBitmask, then dispatches each field per the mapping.
        """
        # Flatten: merge RC state with decoded pico bits
        flat = dict(rc_state)
        bitmask = int(rc_state.get("picoBitmask", 0))
        flat.update(decode_pico_bitmask(bitmask))

        # Process axes
        for field in AXIS_FIELDS:
            if field not in flat:
                continue
            value = int(flat[field])
            mapping = self._mappings.get(field)
            if mapping:
                self._dispatch_axis(field, value, mapping)

        # Process buttons (edge detection)
        for field in BUTTON_FIELDS:
            curr = bool(flat.get(field, False))
            prev = bool(self._prev.get(field, False))
            if curr == prev:
                # Always keep vjoy buttons in sync even with no change
                mapping = self._mappings.get(field, {})
                if mapping.get("action") == "vjoy_button":
                    self._vjoy.set_button(int(mapping["button"]), curr)
                continue
            mapping = self._mappings.get(field)
            if mapping:
                self._dispatch_button(field, curr, mapping)

        self._prev = flat

    # ------------------------------------------------------------------
    # Dispatch helpers
    # ------------------------------------------------------------------

    def _dispatch_axis(
        self, field: str, value: int, mapping: dict[str, Any]
    ) -> None:
        action = mapping.get("action", "none")
        if action == "none":
            return
        if action == "vjoy_axis":
            axis_name = mapping.get("axis", "X")
            invert = bool(mapping.get("invert", False))
            self._vjoy.set_axis(axis_name, value, invert)
        else:
            log.debug("Axis '%s' mapped to unsupported action '%s'", field, action)

    def _dispatch_button(
        self, field: str, pressed: bool, mapping: dict[str, Any]
    ) -> None:
        action = mapping.get("action", "none")
        if action == "none":
            return

        if action == "vjoy_button":
            button_id = int(mapping.get("button", 1))
            self._vjoy.set_button(button_id, pressed)

        elif action == "key":
            # Fire combo on press only; release is handled inside send_key_combo
            if pressed:
                keys: list[str] = mapping.get("keys", [])
                self._sys.send_key_combo(keys, pressed=True)

        elif action == "system":
            # Fire system function on press only
            if pressed:
                fn: str = mapping.get("fn", "")
                self._sys.execute(fn)

        else:
            log.debug("Button '%s' mapped to unknown action '%s'", field, action)
