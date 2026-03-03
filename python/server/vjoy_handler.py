"""
vJoy wrapper.
Gracefully falls back to a no-op implementation if pyvjoy is not
installed or the vJoy driver is not present on the system.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Axis name → pyvjoy HID_USAGE constant mapping
# ---------------------------------------------------------------------------
_AXIS_NAME_MAP: dict[str, int] = {}  # filled at import time if pyvjoy available

try:
    import pyvjoy  # type: ignore

    _AXIS_NAME_MAP = {
        "X":  pyvjoy.HID_USAGE_X,
        "Y":  pyvjoy.HID_USAGE_Y,
        "Z":  pyvjoy.HID_USAGE_Z,
        "RX": pyvjoy.HID_USAGE_RX,
        "RY": pyvjoy.HID_USAGE_RY,
        "RZ": pyvjoy.HID_USAGE_RZ,
        "SL0": pyvjoy.HID_USAGE_SL0,
        "SL1": pyvjoy.HID_USAGE_SL1,
    }
    _PYVJOY_AVAILABLE = True
except ImportError:
    _PYVJOY_AVAILABLE = False
    log.warning(
        "pyvjoy not available — vJoy integration disabled. "
        "Install pyvjoy and the vJoy driver if you need gamepad output."
    )


# ---------------------------------------------------------------------------
# Scaling helper
# ---------------------------------------------------------------------------

_RC_RANGE = 660  # approximate max absolute value from RC sticks/wheels
_VJOY_MAX = 32767
_VJOY_CENTER = _VJOY_MAX // 2  # 16383


def _rc_to_vjoy(value: int, invert: bool = False) -> int:
    """Map RC axis value (±660) to vJoy range (0–32767, centre 16383)."""
    clamped = max(-_RC_RANGE, min(_RC_RANGE, value))
    scaled = int((clamped + _RC_RANGE) / (2 * _RC_RANGE) * _VJOY_MAX)
    return _VJOY_MAX - scaled if invert else scaled


# ---------------------------------------------------------------------------
# VJoyHandler
# ---------------------------------------------------------------------------

class VJoyHandler:
    def __init__(self) -> None:
        self._device = None
        self._device_id: int = 1
        self._active: bool = False
        self._error: Optional[str] = None
        self._inactive_warned: bool = False  # log once, not every frame

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, device_id: int = 1) -> bool:
        """
        Acquire the vJoy device.
        Returns True on success, False if vJoy is unavailable.
        """
        self._device_id = device_id
        self._inactive_warned = False
        if not _PYVJOY_AVAILABLE:
            self._error = "pyvjoy not installed"
            log.warning(
                "vJoy start skipped — pyvjoy not installed. "
                "Install: pip install pyvjoy"
            )
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
                "Make sure vJoy driver is installed and device %d is "
                "configured in vJoyConf.",
                device_id, exc, device_id,
            )
            self._device = None
            self._active = False
            return False

    def stop(self) -> None:
        """Release vJoy device — reset all axes and buttons to neutral."""
        if self._device is not None:
            try:
                # Reset all axes to centre
                for axis_const in _AXIS_NAME_MAP.values():
                    try:
                        self._device.set_axis(axis_const, _VJOY_CENTER)
                    except Exception:
                        pass
            except Exception:
                pass
        self._device = None
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    @property
    def error(self) -> Optional[str]:
        return self._error

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def set_axis(self, axis_name: str, rc_value: int, invert: bool = False) -> None:
        if not self._active or self._device is None:
            if not self._inactive_warned:
                self._inactive_warned = True
                log.warning(
                    "vJoy not active — axis/button commands will be ignored. "
                    "Error: %s", self._error or "unknown",
                )
            return
        axis_const = _AXIS_NAME_MAP.get(axis_name.upper())
        if axis_const is None:
            log.warning("Unknown vJoy axis name: %s", axis_name)
            return
        vjoy_val = _rc_to_vjoy(rc_value, invert)
        try:
            self._device.set_axis(axis_const, vjoy_val)
        except Exception as exc:
            log.warning("vJoy set_axis(%s) error: %s", axis_name, exc)

    def set_button(self, button_id: int, pressed: bool) -> None:
        if not self._active or self._device is None:
            if not self._inactive_warned:
                self._inactive_warned = True
                log.warning(
                    "vJoy not active — axis/button commands will be ignored. "
                    "Error: %s", self._error or "unknown",
                )
            return
        if not (1 <= button_id <= 128):
            log.warning("vJoy button id %d out of range (1-128)", button_id)
            return
        try:
            self._device.set_button(button_id, 1 if pressed else 0)
        except Exception as exc:
            log.warning("vJoy set_button(%d) error: %s", button_id, exc)
