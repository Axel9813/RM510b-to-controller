"""
Input router — maps incoming rc_state fields to configured actions.

Responsibilities:
  - Decode the picoBitmask into individual boolean input fields
  - Compare each field against the previous state to detect edges
  - Dispatch axis values and button press/release events to
    VJoyHandler or SystemActions according to the active input_mappings
  - Process gyro axes (pitch/yaw/roll) with push-to-activate gating,
    per-axis sensitivity, deadzone, and mouse/vJoy output
"""
from __future__ import annotations

import logging
import math
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

# Button fields provided by the Raspberry Pi Pico — core (standard across all RCs)
PICO_BUTTON_FIELDS: frozenset[str] = frozenset({
    "pico_c1", "pico_c2",
    "pico_shutter_half",   # bit 2 — triggers AF / half-press
    "pico_shutter_full",   # bit 9 — full shutter press
    "pico_pause", "pico_rth",
    "pico_switch_f", "pico_switch_s",
    "pico_circle", "pico_arrow",
})

# Pico extra buttons — varies per RC build
PICO_EXTRA_BUTTON_FIELDS: frozenset[str] = frozenset({
    "pico_joy_click",
    "pico_hat_push", "pico_hat_left", "pico_hat_up",
    "pico_hat_down", "pico_hat_right",
    "pico_switch2_up", "pico_switch2_down",
    "pico_red_btn",
})

BUTTON_FIELDS: frozenset[str] = HID_BUTTON_FIELDS | PICO_BUTTON_FIELDS | PICO_EXTRA_BUTTON_FIELDS

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

# Gyro: radians → ±660 scale factor (±45° = ±0.785 rad → ±660 at sensitivity 1.0)
_GYRO_RAD_TO_660 = 660.0 / 0.785


# picoExtraBitmask bit positions → pico extra field name
_PICO_EXTRA_BIT_MAP: list[str] = [
    "pico_joy_click",    # bit 0
    "pico_hat_push",     # bit 1
    "pico_hat_left",     # bit 2
    "pico_hat_up",       # bit 3
    "pico_hat_down",     # bit 4
    "pico_hat_right",    # bit 5
    "pico_switch2_up",   # bit 6
    "pico_switch2_down", # bit 7
    "pico_red_btn",      # bit 8
]


def decode_pico_bitmask(bitmask: int) -> dict[str, bool]:
    """Expand the 16-bit picoBitmask into individual named boolean fields."""
    result: dict[str, bool] = {}
    for bit, name in enumerate(_PICO_BIT_MAP):
        result[name] = bool(bitmask & (1 << bit))
    return result


def decode_pico_extra_bitmask(bitmask: int) -> dict[str, bool]:
    """Expand the 16-bit picoExtraBitmask into individual named boolean fields."""
    result: dict[str, bool] = {}
    for bit, name in enumerate(_PICO_EXTRA_BIT_MAP):
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
        gyro_config: dict[str, Any] | None = None,
    ) -> None:
        self._mappings = mappings
        self._vjoy = vjoy
        self._sys = sys_actions
        self._gyro_config = gyro_config or {}
        # Previous flattened state for edge detection
        self._prev: dict[str, Any] = {}
        # PC-side gyro offset: captured on activate-button press
        self._gyro_offset: dict[str, float] = {"gyroPitch": 0.0, "gyroYaw": 0.0, "gyroRoll": 0.0}

    def reload(self, mappings: dict[str, Any]) -> None:
        """Hot-reload mappings without losing previous state."""
        self._mappings = mappings
        log.info("InputRouter: mappings reloaded.")

    def reload_gyro_config(self, gyro_config: dict[str, Any]) -> None:
        """Hot-reload gyro configuration."""
        self._gyro_config = gyro_config
        log.info("InputRouter: gyro config reloaded.")

    def process(self, rc_state: dict[str, Any]) -> None:
        """
        Process one rc_state message.
        Decodes picoBitmask, then dispatches each field per the mapping.
        """
        # Flatten: merge RC state with decoded pico bits (core + extras)
        flat = dict(rc_state)
        bitmask = int(rc_state.get("picoBitmask", 0))
        flat.update(decode_pico_bitmask(bitmask))
        extra_bitmask = int(rc_state.get("picoExtraBitmask", 0))
        flat.update(decode_pico_extra_bitmask(extra_bitmask))

        # Which button (if any) is the gyro activate button
        activate_btn = self._gyro_config.get("activate_button") if self._gyro_config.get("enabled") else None

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

            # Suppress activate button's normal mapping; capture gyro offset on press
            if field == activate_btn:
                if curr and not prev:
                    self._gyro_offset = {
                        "gyroPitch": float(flat.get("gyroPitch", 0.0)),
                        "gyroYaw":   float(flat.get("gyroYaw", 0.0)),
                        "gyroRoll":  float(flat.get("gyroRoll", 0.0)),
                    }
                self._prev[field] = curr
                continue

            if curr == prev:
                # Always keep vjoy buttons in sync even with no change
                mapping = self._mappings.get(field, {})
                if mapping.get("action") == "vjoy_button":
                    self._vjoy.set_button(int(mapping["button"]), curr)
                continue
            mapping = self._mappings.get(field)
            if mapping:
                self._dispatch_button(field, curr, mapping)

        # Process gyro
        self._process_gyro(flat, activate_btn)

        self._prev = flat

    # ------------------------------------------------------------------
    # Gyro processing
    # ------------------------------------------------------------------

    def _zero_gyro_outputs(self, cfg: dict[str, Any]) -> None:
        """Reset all gyro-mapped vJoy axes to center (0)."""
        for gyro_name in ("pitch", "yaw", "roll"):
            axis_cfg = cfg.get(gyro_name, {})
            if axis_cfg.get("action") == "vjoy_axis":
                self._vjoy.set_axis(axis_cfg.get("vjoy_axis", "SL0"), 0)

    def _process_gyro(self, flat: dict[str, Any], activate_btn: str | None) -> None:
        """Apply gyro → vJoy axis / mouse movement based on gyro_config."""
        cfg = self._gyro_config
        if not cfg.get("enabled", False):
            return

        # Push-to-activate: if activate button is set and not pressed, zero outputs
        if activate_btn:
            if not bool(flat.get(activate_btn, False)):
                self._zero_gyro_outputs(cfg)
                return

        deadzone = float(cfg.get("deadzone", 0.02))
        mouse_speed = float(cfg.get("mouse_speed", 10.0))

        # Accumulate mouse deltas across axes
        mouse_dx = 0.0
        mouse_dy = 0.0

        for gyro_name, rc_field in [("pitch", "gyroPitch"), ("yaw", "gyroYaw"), ("roll", "gyroRoll")]:
            raw = float(flat.get(rc_field, 0.0)) - self._gyro_offset.get(rc_field, 0.0)
            if math.isnan(raw) or math.isinf(raw):
                continue
            axis_cfg = cfg.get(gyro_name, {})
            action = axis_cfg.get("action", "none")
            if action == "none":
                continue

            # Apply deadzone (subtract threshold so output starts at 0)
            if abs(raw) < deadzone:
                raw = 0.0
            else:
                raw = raw - math.copysign(deadzone, raw)

            sensitivity = float(axis_cfg.get("sensitivity", 1.0))
            invert = bool(axis_cfg.get("invert", False))
            value = raw * sensitivity
            if invert:
                value = -value

            if action == "vjoy_axis":
                # Scale radians to ±660 range
                vjoy_val = int(max(-660, min(660, value * _GYRO_RAD_TO_660)))
                axis_name = axis_cfg.get("vjoy_axis", "SL0")
                self._vjoy.set_axis(axis_name, vjoy_val)

            elif action == "mouse_move":
                mouse_axis = axis_cfg.get("mouse_axis", "x")
                delta = value * mouse_speed
                if mouse_axis == "x":
                    mouse_dx += delta
                else:
                    mouse_dy += delta

        # Apply accumulated mouse movement
        idx, idy = int(round(mouse_dx)), int(round(mouse_dy))
        if idx != 0 or idy != 0:
            # Clamp to prevent runaway cursor
            idx = max(-100, min(100, idx))
            idy = max(-100, min(100, idy))
            self._sys.mouse_move(idx, idy)

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
