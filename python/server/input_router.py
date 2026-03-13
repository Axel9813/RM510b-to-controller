"""
Input router — maps incoming rc_state fields to configured actions.

Responsibilities:
  - Decode the picoBitmask into individual boolean input fields
  - Decode picoExtraBitmask using dynamic pico_hardware definition
  - Compare each field against the previous state to detect edges
  - Dispatch axis values and button press/release events to
    GamepadOutput or SystemActions according to the active input_mappings
  - Process pico analog axes (joystick) with configurable mapping
  - Process gyro axes (pitch/yaw/roll) with push-to-activate gating,
    per-axis sensitivity, deadzone, and mouse/vJoy output
  - Accumulate mouse deltas from all sources (axes, gyro) per frame
"""
from __future__ import annotations

import logging
import math
from typing import Any

from gamepad_output import GamepadOutput
from system_actions import SystemActions

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field classification — fixed inputs (standard across all RC builds)
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

# picoBitmask bit positions → pico field name (fixed, same for all RCs)
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
        gamepad: GamepadOutput,
        sys_actions: SystemActions,
        gyro_config: dict[str, Any] | None = None,
        pico_hardware: dict[str, Any] | None = None,
    ) -> None:
        self._mappings = mappings
        self._gamepad = gamepad
        self._sys = sys_actions
        self._gyro_config = gyro_config or {}
        # Previous flattened state for edge detection
        self._prev: dict[str, Any] = {}
        # PC-side gyro offset: captured on activate-button press
        self._gyro_offset: dict[str, float] = {"gyroPitch": 0.0, "gyroYaw": 0.0, "gyroRoll": 0.0}
        # Per-frame mouse accumulator (reset each process() call)
        self._frame_mouse_dx: float = 0.0
        self._frame_mouse_dy: float = 0.0

        # Build dynamic extra input definitions from pico_hardware
        hw = pico_hardware or {"extra_buttons": [], "extra_axes": []}
        self._extra_bit_map: list[str] = [
            f"pico_{btn['id']}" for btn in hw.get("extra_buttons", [])
        ]
        self._extra_button_fields: frozenset[str] = frozenset(self._extra_bit_map)
        self._pico_axes: list[dict[str, str]] = hw.get("extra_axes", [])
        self._all_button_fields: frozenset[str] = (
            HID_BUTTON_FIELDS | PICO_BUTTON_FIELDS | self._extra_button_fields
        )

    def reload(self, mappings: dict[str, Any]) -> None:
        """Hot-reload mappings without losing previous state."""
        self._mappings = mappings
        log.info("InputRouter: mappings reloaded.")

    def reload_gyro_config(self, gyro_config: dict[str, Any]) -> None:
        """Hot-reload gyro configuration."""
        self._gyro_config = gyro_config
        log.info("InputRouter: gyro config reloaded.")

    def _decode_extra_bitmask(self, bitmask: int) -> dict[str, bool]:
        """Expand picoExtraBitmask using dynamic bit map from pico_hardware."""
        result: dict[str, bool] = {}
        for bit, name in enumerate(self._extra_bit_map):
            result[name] = bool(bitmask & (1 << bit))
        return result

    def process(self, rc_state: dict[str, Any]) -> None:
        """
        Process one rc_state message.
        Decodes bitmasks, dispatches axes and buttons, processes gyro.
        """
        # Reset per-frame mouse accumulator
        self._frame_mouse_dx = 0.0
        self._frame_mouse_dy = 0.0

        # Flatten: merge RC state with decoded pico bits (core + extras)
        flat = dict(rc_state)
        bitmask = int(rc_state.get("picoBitmask", 0))
        flat.update(decode_pico_bitmask(bitmask))
        extra_bitmask = int(rc_state.get("picoExtraBitmask", 0))
        flat.update(self._decode_extra_bitmask(extra_bitmask))

        # Which button (if any) is the gyro activate button
        activate_btn = self._gyro_config.get("activate_button") if self._gyro_config.get("enabled") else None

        # Process HID axes (±660 range)
        for field in AXIS_FIELDS:
            if field not in flat:
                continue
            value = int(flat[field])
            mapping = self._mappings.get(field)
            if mapping:
                self._dispatch_axis(field, value, mapping)

        # Process pico analog axes (raw ADC → ±660 with calibration)
        for axis_def in self._pico_axes:
            source = axis_def.get("source_field", "")
            if source not in flat:
                continue
            raw = int(flat[source])
            cal_min = int(axis_def.get("cal_min", 0))
            cal_center = int(axis_def.get("cal_center", 32768))
            cal_max = int(axis_def.get("cal_max", 65535))
            # Map [cal_min, cal_center] → [-660, 0] and [cal_center, cal_max] → [0, 660]
            if raw < cal_center:
                span = cal_center - cal_min
                value = int((raw - cal_center) * 660 / span) if span > 0 else 0
            else:
                span = cal_max - cal_center
                value = int((raw - cal_center) * 660 / span) if span > 0 else 0
            value = max(-660, min(660, value))
            input_id = f"pico_{axis_def['id']}"
            mapping = self._mappings.get(input_id)
            if mapping:
                self._dispatch_axis(input_id, value, mapping)

        # Process buttons (edge detection)
        for field in self._all_button_fields:
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
                    self._gamepad.set_button(mapping["button"], curr)
                continue
            mapping = self._mappings.get(field)
            if mapping:
                self._dispatch_button(field, curr, mapping)

        # Process gyro (also accumulates mouse deltas)
        self._process_gyro(flat, activate_btn)

        # Send accumulated mouse movement from all sources (axes + gyro)
        dx = int(round(self._frame_mouse_dx))
        dy = int(round(self._frame_mouse_dy))
        if dx != 0 or dy != 0:
            dx = max(-100, min(100, dx))
            dy = max(-100, min(100, dy))
            self._sys.mouse_move(dx, dy)

        self._prev = flat

    # ------------------------------------------------------------------
    # Gyro processing
    # ------------------------------------------------------------------

    def _zero_gyro_outputs(self, cfg: dict[str, Any]) -> None:
        """Reset all gyro-mapped vJoy axes to center (0)."""
        for gyro_name in ("pitch", "yaw", "roll"):
            axis_cfg = cfg.get(gyro_name, {})
            if axis_cfg.get("action") == "vjoy_axis":
                self._gamepad.set_axis(axis_cfg.get("vjoy_axis", "SL0"), 0)

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
                self._gamepad.set_axis(axis_name, vjoy_val)

            elif action == "mouse_move":
                mouse_axis = axis_cfg.get("mouse_axis", "x")
                delta = value * mouse_speed
                if mouse_axis == "x":
                    self._frame_mouse_dx += delta
                else:
                    self._frame_mouse_dy += delta

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
            dead_zone = float(mapping.get("dead_zone", 0.0))
            if dead_zone > 0:
                normalized = value / 660.0
                if abs(normalized) < dead_zone:
                    value = 0
                else:
                    value = int(
                        (normalized - math.copysign(dead_zone, normalized))
                        / (1.0 - dead_zone) * 660
                    )
            self._gamepad.set_axis(axis_name, value, invert)

        elif action == "mouse_move":
            dead_zone = float(mapping.get("dead_zone", 0.05))
            normalized = value / 660.0
            if abs(normalized) < dead_zone:
                normalized = 0.0
            else:
                normalized = (
                    (normalized - math.copysign(dead_zone, normalized))
                    / (1.0 - dead_zone)
                )
            sensitivity = float(mapping.get("sensitivity", 5.0))
            if mapping.get("invert"):
                normalized = -normalized
            delta = normalized * sensitivity
            mouse_axis = mapping.get("mouse_axis", "x")
            if mouse_axis == "x":
                self._frame_mouse_dx += delta
            else:
                self._frame_mouse_dy += delta

        else:
            log.debug("Axis '%s' mapped to unsupported action '%s'", field, action)

    def _dispatch_button(
        self, field: str, pressed: bool, mapping: dict[str, Any]
    ) -> None:
        action = mapping.get("action", "none")
        if action == "none":
            return

        if action == "vjoy_button":
            button_id = mapping.get("button", 1)
            self._gamepad.set_button(button_id, pressed)

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
