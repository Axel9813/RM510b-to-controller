"""
System-level actions: media control, keyboard combos, volume.
Uses pynput for key presses and optionally pycaw (Windows) for precise volume.
"""
from __future__ import annotations

import logging
import platform
import time
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# pynput import
# ---------------------------------------------------------------------------
try:
    from pynput.keyboard import Controller as KeyboardController, Key  # type: ignore
    _PYNPUT_AVAILABLE = True
except ImportError:
    _PYNPUT_AVAILABLE = False
    log.warning(
        "pynput not available — keyboard/system actions disabled. "
        "Install pynput to enable media keys and key combos."
    )

# ---------------------------------------------------------------------------
# pycaw (Windows absolute volume) — optional
# ---------------------------------------------------------------------------
_pycaw_master: Optional[object] = None

if platform.system() == "Windows":
    try:
        import comtypes  # type: ignore
        comtypes.CoInitialize()
        from pycaw.pycaw import AudioUtilities  # type: ignore

        _speakers = AudioUtilities.GetSpeakers()
        _pycaw_master = _speakers.EndpointVolume
        log.info("pycaw initialised — absolute volume control available.")
    except Exception as exc:
        _pycaw_master = None
        log.warning("pycaw not available (%s) — volume_set will not work.", exc)

# ---------------------------------------------------------------------------
# Key name → pynput Key mapping
# ---------------------------------------------------------------------------

_SPECIAL_KEY_MAP: dict[str, object] = {}
if _PYNPUT_AVAILABLE:
    _SPECIAL_KEY_MAP = {
        "ctrl": Key.ctrl,
        "control": Key.ctrl,
        "shift": Key.shift,
        "alt": Key.alt,
        "cmd": Key.cmd,
        "win": Key.cmd,
        "enter": Key.enter,
        "return": Key.enter,
        "esc": Key.esc,
        "escape": Key.esc,
        "space": Key.space,
        "tab": Key.tab,
        "backspace": Key.backspace,
        "delete": Key.delete,
        "up": Key.up,
        "down": Key.down,
        "left": Key.left,
        "right": Key.right,
        "home": Key.home,
        "end": Key.end,
        "page_up": Key.page_up,
        "page_down": Key.page_down,
        "f1": Key.f1,  "f2": Key.f2,  "f3": Key.f3,  "f4": Key.f4,
        "f5": Key.f5,  "f6": Key.f6,  "f7": Key.f7,  "f8": Key.f8,
        "f9": Key.f9,  "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
        "media_play_pause": Key.media_play_pause,
        "media_next": Key.media_next,
        "media_prev": Key.media_previous,
        "media_volume_up": Key.media_volume_up,
        "media_volume_down": Key.media_volume_down,
        "media_volume_mute": Key.media_volume_mute,
    }


# ---------------------------------------------------------------------------
# SystemActions
# ---------------------------------------------------------------------------

class SystemActions:
    def __init__(self) -> None:
        self._kb: Optional[KeyboardController] = None
        if _PYNPUT_AVAILABLE:
            self._kb = KeyboardController()

    def execute(self, fn: str, value: float = 0.0) -> None:
        """
        Execute a named system function.
        fn options:
          media_play_pause, media_next, media_prev,
          volume_up, volume_down, volume_mute, volume_set
        value is used for volume_set (0.0–1.0).
        """
        try:
            match fn:
                case "media_play_pause":
                    self._press_special("media_play_pause")
                case "media_next":
                    self._press_special("media_next")
                case "media_prev":
                    self._press_special("media_prev")
                case "volume_up":
                    self._press_special("media_volume_up")
                case "volume_down":
                    self._press_special("media_volume_down")
                case "volume_mute":
                    self._press_special("media_volume_mute")
                case "volume_set":
                    self._set_volume(value)
                case _:
                    log.warning("Unknown system function: %s", fn)
        except Exception as exc:
            log.error("system_action '%s' failed: %s", fn, exc)

    def send_key_combo(self, keys: list[str], pressed: bool) -> None:
        """
        Press or release a combination of keys.
        For combos like ['ctrl', 'shift', 'h']:
          - pressed=True  → hold all modifiers + tap the last key
          - pressed=False → release all modifiers (no-op for non-modifiers)
        """
        if not _PYNPUT_AVAILABLE or self._kb is None:
            return
        if not keys:
            return

        resolved = [self._resolve_key(k) for k in keys]
        modifiers = resolved[:-1]
        main_key = resolved[-1]

        if pressed:
            for mod in modifiers:
                self._kb.press(mod)
            self._kb.press(main_key)
            self._kb.release(main_key)
            for mod in reversed(modifiers):
                self._kb.release(mod)
        # On release we don't need to do anything — modifiers were fully
        # pressed+released in the press event already.

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _press_special(self, key_name: str) -> None:
        if not _PYNPUT_AVAILABLE or self._kb is None:
            return
        key = _SPECIAL_KEY_MAP.get(key_name)
        if key is None:
            log.warning("Special key not found: %s", key_name)
            return
        self._kb.press(key)
        self._kb.release(key)

    def _resolve_key(self, name: str) -> object:
        """Resolve a string key name to a pynput Key or character."""
        special = _SPECIAL_KEY_MAP.get(name.lower())
        if special is not None:
            return special
        # Single character
        return name[0] if name else " "

    def _set_volume(self, level: float) -> None:
        """Set absolute system volume (0.0–1.0). Windows only via pycaw."""
        level = max(0.0, min(1.0, level))
        if _pycaw_master is not None:
            try:
                _pycaw_master.SetMasterVolumeLevelScalar(level, None)  # type: ignore
                return
            except Exception as exc:
                log.warning("pycaw volume_set failed: %s", exc)
        # Fallback: not supported without pycaw
        log.debug("volume_set not available on this platform without pycaw.")
