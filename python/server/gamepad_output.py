"""
Gamepad output abstraction — supports vJoy, ViGEm Xbox 360, and ViGEm DualShock 4.

Provides a unified interface for all gamepad output drivers.
Each driver handles its own value scaling from RC range (±660) to native range.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional, Union

log = logging.getLogger(__name__)

RC_RANGE = 660  # approximate max absolute value from RC sticks/wheels

# ---------------------------------------------------------------------------
# Driver identifiers
# ---------------------------------------------------------------------------
DRIVER_VJOY = "vjoy"
DRIVER_VIGEM_XBOX = "vigem_xbox"
DRIVER_VIGEM_DS4 = "vigem_ds4"

ALL_DRIVERS = [DRIVER_VJOY, DRIVER_VIGEM_XBOX, DRIVER_VIGEM_DS4]

# ---------------------------------------------------------------------------
# Per-driver metadata (axes, buttons, labels) — used by frontend for dropdowns
# ---------------------------------------------------------------------------
DRIVER_INFO: dict[str, dict[str, Any]] = {
    DRIVER_VJOY: {
        "label": "vJoy",
        "axes": ["X", "Y", "Z", "RX", "RY", "RZ", "SL0", "SL1"],
        "triggers": [],
        "buttons": list(range(1, 129)),
        "button_type": "number",
    },
    DRIVER_VIGEM_XBOX: {
        "label": "Xbox 360",
        "axes": ["LX", "LY", "RX", "RY", "LT", "RT"],
        "triggers": ["LT", "RT"],
        "buttons": [
            "A", "B", "X", "Y",
            "LB", "RB",
            "Back", "Start", "Guide",
            "L3", "R3",
            "DPad_Up", "DPad_Down", "DPad_Left", "DPad_Right",
        ],
        "button_type": "name",
    },
    DRIVER_VIGEM_DS4: {
        "label": "DualShock 4",
        "axes": ["LX", "LY", "RX", "RY", "LT", "RT"],
        "triggers": ["LT", "RT"],
        "buttons": [
            "Cross", "Circle", "Square", "Triangle",
            "L1", "R1", "L2", "R2",
            "Share", "Options", "PS", "Touchpad",
            "L3", "R3",
            "DPad_Up", "DPad_Down", "DPad_Left", "DPad_Right",
        ],
        "button_type": "name",
    },
}


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class GamepadOutput(ABC):
    @abstractmethod
    def start(self, **kwargs: Any) -> bool: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def set_axis(self, axis_name: str, rc_value: int, invert: bool = False) -> None: ...

    @abstractmethod
    def set_button(self, button_id: Union[int, str], pressed: bool) -> None: ...

    @property
    @abstractmethod
    def active(self) -> bool: ...

    @property
    @abstractmethod
    def error(self) -> Optional[str]: ...

    @property
    @abstractmethod
    def driver_name(self) -> str: ...

    def register_rumble_callback(self, callback: Callable[[int, int], None]) -> None:
        """Register a callback for rumble events: callback(large_motor, small_motor).
        Only ViGEm drivers support this; others silently ignore."""
        pass


# ---------------------------------------------------------------------------
# Null (no-op) output
# ---------------------------------------------------------------------------

class NullOutput(GamepadOutput):
    """No-op output when no driver is available."""

    def __init__(self, reason: str = "No gamepad driver available") -> None:
        self._error = reason

    def start(self, **kwargs: Any) -> bool:
        return False

    def stop(self) -> None:
        pass

    def set_axis(self, axis_name: str, rc_value: int, invert: bool = False) -> None:
        pass

    def set_button(self, button_id: Union[int, str], pressed: bool) -> None:
        pass

    @property
    def active(self) -> bool:
        return False

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def driver_name(self) -> str:
        return "none"


# ---------------------------------------------------------------------------
# vJoy output
# ---------------------------------------------------------------------------

_AXIS_NAME_MAP: dict[str, int] = {}
_PYVJOY_AVAILABLE = False

try:
    import pyvjoy  # type: ignore

    _AXIS_NAME_MAP = {
        "X":   pyvjoy.HID_USAGE_X,
        "Y":   pyvjoy.HID_USAGE_Y,
        "Z":   pyvjoy.HID_USAGE_Z,
        "RX":  pyvjoy.HID_USAGE_RX,
        "RY":  pyvjoy.HID_USAGE_RY,
        "RZ":  pyvjoy.HID_USAGE_RZ,
        "SL0": pyvjoy.HID_USAGE_SL0,
        "SL1": pyvjoy.HID_USAGE_SL1,
    }
    _PYVJOY_AVAILABLE = True
except ImportError:
    pass

_VJOY_MAX = 32767
_VJOY_CENTER = _VJOY_MAX // 2  # 16383


def _rc_to_vjoy(value: int, invert: bool = False) -> int:
    """Map RC axis value (±660) to vJoy range (0–32767, centre 16383)."""
    clamped = max(-RC_RANGE, min(RC_RANGE, value))
    scaled = int((clamped + RC_RANGE) / (2 * RC_RANGE) * _VJOY_MAX)
    return _VJOY_MAX - scaled if invert else scaled


class VJoyOutput(GamepadOutput):
    """vJoy output — wraps pyvjoy."""

    def __init__(self) -> None:
        self._device = None
        self._device_id: int = 1
        self._active: bool = False
        self._error: Optional[str] = None
        self._inactive_warned: bool = False

    def start(self, **kwargs: Any) -> bool:
        device_id = kwargs.get("device_id", 1)
        self._device_id = device_id
        self._inactive_warned = False
        if not _PYVJOY_AVAILABLE:
            self._error = "pyvjoy not installed"
            log.warning("vJoy start skipped — pyvjoy not installed.")
            return False
        try:
            self._device = pyvjoy.VJoyDevice(device_id)  # type: ignore[name-defined]
            self._active = True
            self._error = None
            log.info("vJoy device %d acquired.", device_id)
            return True
        except Exception as exc:
            self._error = str(exc)
            log.error(
                "Failed to acquire vJoy device %d: %s. "
                "Make sure vJoy driver is installed and device %d is configured in vJoyConf.",
                device_id, exc, device_id,
            )
            self._device = None
            self._active = False
            return False

    def stop(self) -> None:
        if self._device is not None:
            try:
                for axis_const in _AXIS_NAME_MAP.values():
                    try:
                        self._device.set_axis(axis_const, _VJOY_CENTER)
                    except Exception:
                        pass
            except Exception:
                pass
        self._device = None
        self._active = False

    def set_axis(self, axis_name: str, rc_value: int, invert: bool = False) -> None:
        if not self._active or self._device is None:
            if not self._inactive_warned:
                self._inactive_warned = True
                log.warning("vJoy not active — commands ignored. Error: %s", self._error)
            return
        axis_const = _AXIS_NAME_MAP.get(axis_name.upper())
        if axis_const is None:
            log.warning("Unknown vJoy axis name: %s", axis_name)
            return
        try:
            self._device.set_axis(axis_const, _rc_to_vjoy(rc_value, invert))
        except Exception as exc:
            log.warning("vJoy set_axis(%s) error: %s", axis_name, exc)

    def set_button(self, button_id: Union[int, str], pressed: bool) -> None:
        if not self._active or self._device is None:
            if not self._inactive_warned:
                self._inactive_warned = True
                log.warning("vJoy not active — commands ignored. Error: %s", self._error)
            return
        bid = int(button_id)
        if not (1 <= bid <= 128):
            log.warning("vJoy button id %d out of range (1-128)", bid)
            return
        try:
            self._device.set_button(bid, 1 if pressed else 0)
        except Exception as exc:
            log.warning("vJoy set_button(%d) error: %s", bid, exc)

    @property
    def active(self) -> bool:
        return self._active

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def driver_name(self) -> str:
        return DRIVER_VJOY


# ---------------------------------------------------------------------------
# ViGEm output (Xbox 360 / DualShock 4)
# ---------------------------------------------------------------------------

_VGAMEPAD_AVAILABLE = False
_vg = None  # module reference

try:
    import vgamepad as _vg  # type: ignore
    _VGAMEPAD_AVAILABLE = True
except ImportError:
    pass


def _build_xbox_button_map() -> dict[str, Any]:
    if _vg is None:
        return {}
    return {
        "A": _vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
        "B": _vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
        "X": _vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
        "Y": _vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
        "LB": _vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
        "RB": _vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
        "Back": _vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
        "Start": _vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
        "Guide": _vg.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE,
        "L3": _vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
        "R3": _vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
        "DPad_Up": _vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
        "DPad_Down": _vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
        "DPad_Left": _vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
        "DPad_Right": _vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
    }


def _build_ds4_button_map() -> dict[str, Any]:
    if _vg is None:
        return {}
    return {
        "Cross": _vg.DS4_BUTTONS.DS4_BUTTON_CROSS,
        "Circle": _vg.DS4_BUTTONS.DS4_BUTTON_CIRCLE,
        "Square": _vg.DS4_BUTTONS.DS4_BUTTON_SQUARE,
        "Triangle": _vg.DS4_BUTTONS.DS4_BUTTON_TRIANGLE,
        "L1": _vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_LEFT,
        "R1": _vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_RIGHT,
        "L2": _vg.DS4_BUTTONS.DS4_BUTTON_TRIGGER_LEFT,
        "R2": _vg.DS4_BUTTONS.DS4_BUTTON_TRIGGER_RIGHT,
        "Share": _vg.DS4_BUTTONS.DS4_BUTTON_SHARE,
        "Options": _vg.DS4_BUTTONS.DS4_BUTTON_OPTIONS,
        "L3": _vg.DS4_BUTTONS.DS4_BUTTON_THUMB_LEFT,
        "R3": _vg.DS4_BUTTONS.DS4_BUTTON_THUMB_RIGHT,
    }


def _build_ds4_special_map() -> dict[str, Any]:
    if _vg is None:
        return {}
    return {
        "PS": _vg.DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_PS,
        "Touchpad": _vg.DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_TOUCHPAD,
    }


def _build_ds4_dpad_map() -> dict[str, Any]:
    if _vg is None:
        return {}
    return {
        "DPad_Up": _vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTH,
        "DPad_Down": _vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTH,
        "DPad_Left": _vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_WEST,
        "DPad_Right": _vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_EAST,
    }


class ViGEmOutput(GamepadOutput):
    """ViGEm output — Xbox 360 or DualShock 4 via vgamepad."""

    def __init__(self, profile: str = DRIVER_VIGEM_XBOX) -> None:
        self._profile = profile
        self._gamepad: Any = None
        self._active: bool = False
        self._error: Optional[str] = None
        self._inactive_warned: bool = False
        self._rumble_cb: Optional[Callable[[int, int], None]] = None
        # Buffered axis state (sticks need X+Y set together)
        self._axes: dict[str, float] = {
            "LX": 0.0, "LY": 0.0, "RX": 0.0, "RY": 0.0, "LT": 0.0, "RT": 0.0,
        }
        # DS4 DPad state tracking
        self._dpad: dict[str, bool] = {
            "DPad_Up": False, "DPad_Down": False,
            "DPad_Left": False, "DPad_Right": False,
        }

    def start(self, **kwargs: Any) -> bool:
        self._inactive_warned = False
        if not _VGAMEPAD_AVAILABLE or _vg is None:
            self._error = "vgamepad not installed"
            log.warning(
                "ViGEm start skipped — vgamepad not installed. "
                "Install: pip install vgamepad"
            )
            return False
        try:
            if self._profile == DRIVER_VIGEM_DS4:
                self._gamepad = _vg.VDS4Gamepad()
                log.info("ViGEm DualShock 4 gamepad created.")
            else:
                self._gamepad = _vg.VX360Gamepad()
                log.info("ViGEm Xbox 360 gamepad created.")
            self._active = True
            self._error = None
            self._gamepad.update()
            # Register rumble notification if callback is set
            if self._rumble_cb is not None:
                self._register_notification()
            return True
        except Exception as exc:
            self._error = str(exc)
            log.error("Failed to create ViGEm gamepad: %s", exc)
            self._gamepad = None
            self._active = False
            return False

    def stop(self) -> None:
        if self._gamepad is not None:
            try:
                self._gamepad.reset()
                self._gamepad.update()
            except Exception:
                pass
            # Let garbage collection destroy the gamepad (disconnects from ViGEmBus)
        self._gamepad = None
        self._active = False
        self._axes = {"LX": 0.0, "LY": 0.0, "RX": 0.0, "RY": 0.0, "LT": 0.0, "RT": 0.0}

    def set_axis(self, axis_name: str, rc_value: int, invert: bool = False) -> None:
        if not self._active or self._gamepad is None:
            if not self._inactive_warned:
                self._inactive_warned = True
                log.warning("ViGEm not active — commands ignored. Error: %s", self._error)
            return

        name = axis_name.upper()
        triggers = {"LT", "RT"}
        valid_axes = {"LX", "LY", "RX", "RY", "LT", "RT"}
        if name not in valid_axes:
            log.warning("Unknown ViGEm axis: %s", axis_name)
            return

        clamped = max(-RC_RANGE, min(RC_RANGE, rc_value))

        if name in triggers:
            # Triggers: center (0) = released, full deflection either way = fully pressed
            val = abs(clamped) / RC_RANGE
            if invert:
                val = 1.0 - val
            self._axes[name] = val
        else:
            # Sticks: ±660 → ±1.0
            val = clamped / RC_RANGE
            if invert:
                val = -val
            self._axes[name] = val

        try:
            self._apply_axes()
        except Exception as exc:
            log.warning("ViGEm set_axis(%s) error: %s", axis_name, exc)

    def set_button(self, button_id: Union[int, str], pressed: bool) -> None:
        if not self._active or self._gamepad is None:
            if not self._inactive_warned:
                self._inactive_warned = True
                log.warning("ViGEm not active — commands ignored. Error: %s", self._error)
            return

        name = str(button_id)
        try:
            if self._profile == DRIVER_VIGEM_XBOX:
                self._set_xbox_button(name, pressed)
            else:
                self._set_ds4_button(name, pressed)
        except Exception as exc:
            log.warning("ViGEm set_button(%s) error: %s", name, exc)

    def register_rumble_callback(self, callback: Callable[[int, int], None]) -> None:
        self._rumble_cb = callback
        if self._active and self._gamepad is not None:
            self._register_notification()

    def _register_notification(self) -> None:
        """Register vgamepad notification to receive rumble events from games."""
        try:
            def _on_notification(client, target, large_motor, small_motor, led_number, user_data):
                if self._rumble_cb is not None:
                    try:
                        self._rumble_cb(int(large_motor), int(small_motor))
                    except Exception as exc:
                        log.debug("Rumble callback error: %s", exc)
            self._gamepad.register_notification(callback_function=_on_notification)
            log.info("ViGEm rumble notification registered.")
        except Exception as exc:
            log.warning("Failed to register ViGEm rumble notification: %s", exc)

    def _apply_axes(self) -> None:
        """Send buffered axis values to the gamepad."""
        gp = self._gamepad
        gp.left_joystick_float(
            x_value_float=self._axes["LX"],
            y_value_float=self._axes["LY"],
        )
        gp.right_joystick_float(
            x_value_float=self._axes["RX"],
            y_value_float=self._axes["RY"],
        )
        gp.left_trigger_float(value_float=self._axes["LT"])
        gp.right_trigger_float(value_float=self._axes["RT"])
        gp.update()

    def _set_xbox_button(self, name: str, pressed: bool) -> None:
        btn_map = _build_xbox_button_map()
        btn = btn_map.get(name)
        if btn is None:
            log.warning("Unknown Xbox button: %s", name)
            return
        if pressed:
            self._gamepad.press_button(button=btn)
        else:
            self._gamepad.release_button(button=btn)
        self._gamepad.update()

    def _set_ds4_button(self, name: str, pressed: bool) -> None:
        # Check regular buttons
        btn_map = _build_ds4_button_map()
        btn = btn_map.get(name)
        if btn is not None:
            if pressed:
                self._gamepad.press_button(button=btn)
            else:
                self._gamepad.release_button(button=btn)
            self._gamepad.update()
            return

        # Check special buttons (PS, Touchpad)
        special_map = _build_ds4_special_map()
        special = special_map.get(name)
        if special is not None:
            if pressed:
                self._gamepad.press_special_button(special_button=special)
            else:
                self._gamepad.release_special_button(special_button=special)
            self._gamepad.update()
            return

        # Check DPad
        dpad_map = _build_ds4_dpad_map()
        if name in dpad_map:
            self._dpad[name] = pressed
            self._apply_ds4_dpad()
            return

        log.warning("Unknown DS4 button: %s", name)

    def _apply_ds4_dpad(self) -> None:
        """Compute DS4 DPad direction from tracked button states."""
        up = self._dpad.get("DPad_Up", False)
        down = self._dpad.get("DPad_Down", False)
        left = self._dpad.get("DPad_Left", False)
        right = self._dpad.get("DPad_Right", False)

        if _vg is None:
            return
        d = _vg.DS4_DPAD_DIRECTIONS

        if up and right:
            direction = d.DS4_BUTTON_DPAD_NORTHEAST
        elif up and left:
            direction = d.DS4_BUTTON_DPAD_NORTHWEST
        elif down and right:
            direction = d.DS4_BUTTON_DPAD_SOUTHEAST
        elif down and left:
            direction = d.DS4_BUTTON_DPAD_SOUTHWEST
        elif up:
            direction = d.DS4_BUTTON_DPAD_NORTH
        elif down:
            direction = d.DS4_BUTTON_DPAD_SOUTH
        elif left:
            direction = d.DS4_BUTTON_DPAD_WEST
        elif right:
            direction = d.DS4_BUTTON_DPAD_EAST
        else:
            direction = d.DS4_BUTTON_DPAD_NONE

        self._gamepad.directional_pad(direction=direction)
        self._gamepad.update()

    @property
    def active(self) -> bool:
        return self._active

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def driver_name(self) -> str:
        return self._profile


# ---------------------------------------------------------------------------
# Factory + detection
# ---------------------------------------------------------------------------

def detect_available_drivers() -> list[str]:
    """Return list of driver identifiers that can be used on this system."""
    available: list[str] = []
    if _PYVJOY_AVAILABLE:
        available.append(DRIVER_VJOY)
    if _VGAMEPAD_AVAILABLE:
        available.append(DRIVER_VIGEM_XBOX)
        available.append(DRIVER_VIGEM_DS4)
    return available


def create_output(driver: str, **kwargs: Any) -> GamepadOutput:
    """Create a GamepadOutput instance for the given driver."""
    if driver == DRIVER_VJOY:
        return VJoyOutput()
    if driver in (DRIVER_VIGEM_XBOX, DRIVER_VIGEM_DS4):
        return ViGEmOutput(profile=driver)
    # Fallback: try vJoy, then ViGEm, then null
    available = detect_available_drivers()
    if available:
        log.warning("Unknown driver '%s', falling back to '%s'.", driver, available[0])
        return create_output(available[0], **kwargs)
    return NullOutput(f"No gamepad drivers installed (requested: {driver})")
