"""
Manages server.json and per-profile JSON files in config/profiles/.
All paths are resolved relative to the directory that contains this file.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

BASE_DIR = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"
PROFILES_DIR = CONFIG_DIR / "profiles"

# ---------------------------------------------------------------------------
# Default content helpers
# ---------------------------------------------------------------------------

DEFAULT_SERVER: dict[str, Any] = {
    "port": 8080,
    "discovery_port": 8766,
    "tcp_beacon_port": 8767,
    "vjoy_device_id": 1,
    "active_profile": "default",
}

DEFAULT_PROFILE: dict[str, Any] = {
    "profile_name": "default",
    "input_mappings": {
        "stickLeftH":  {"action": "vjoy_axis",   "axis": "X"},
        "stickLeftV":  {"action": "vjoy_axis",   "axis": "Y",  "invert": True},
        "stickRightH": {"action": "vjoy_axis",   "axis": "RX"},
        "stickRightV": {"action": "vjoy_axis",   "axis": "RY", "invert": True},
        "leftWheel":   {"action": "vjoy_axis",   "axis": "Z"},
        "rightWheel":  {"action": "vjoy_axis",   "axis": "RZ"},
        "record":      {"action": "vjoy_button", "button": 1},
        "shutter":     {"action": "vjoy_button", "button": 3},
        "fiveDUp":     {"action": "vjoy_button", "button": 4},
        "fiveDDown":   {"action": "vjoy_button", "button": 5},
        "fiveDLeft":   {"action": "vjoy_button", "button": 6},
        "fiveDRight":  {"action": "vjoy_button", "button": 7},
        "fiveDCenter": {"action": "vjoy_button", "button": 8},
        "pico_c1":     {"action": "vjoy_button", "button": 9},
        "pico_c2":     {"action": "vjoy_button", "button": 10},
        "pico_shutter_half": {"action": "vjoy_button", "button": 2},  # half-press
        "pico_shutter_full": {"action": "vjoy_button", "button": 3},  # full-press (was HID shutter)
        "pico_pause":  {"action": "system", "fn": "media_play_pause"},
        "pico_rth":    {"action": "none"},
        "pico_switch_f": {"action": "none"},
        "pico_switch_s": {"action": "none"},
        "pico_circle": {"action": "none"},
        "pico_arrow":  {"action": "none"},
    },
    "element_registry": {},
}


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    """Singleton-style manager for server + profile configs."""

    def __init__(self) -> None:
        self._server: dict[str, Any] = {}
        self._profile: dict[str, Any] = {}
        self._profile_name: str = "default"
        self._on_profile_changed: list[Callable[[], None]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def ensure_defaults(self) -> None:
        """Create config directory structure and default files if missing."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)

        server_path = CONFIG_DIR / "server.json"
        if not server_path.exists():
            _write_json(server_path, DEFAULT_SERVER)

        default_profile = PROFILES_DIR / "default.json"
        if not default_profile.exists():
            _write_json(default_profile, DEFAULT_PROFILE)

    def load(self) -> None:
        """Load server config and the active profile from disk."""
        self.ensure_defaults()
        self._server = _read_json(CONFIG_DIR / "server.json")
        self._profile_name = self._server.get("active_profile", "default")
        self._profile = self._load_profile_raw(self._profile_name)

    # ------------------------------------------------------------------
    # Server config
    # ------------------------------------------------------------------

    def server_cfg(self) -> dict[str, Any]:
        return self._server

    def save_server(self) -> None:
        _write_json(CONFIG_DIR / "server.json", self._server)

    # ------------------------------------------------------------------
    # Profile management
    # ------------------------------------------------------------------

    def list_profiles(self) -> list[str]:
        """Return sorted list of profile names (without .json extension)."""
        return sorted(
            p.stem for p in PROFILES_DIR.glob("*.json")
        )

    def active_profile_name(self) -> str:
        return self._profile_name

    def active_profile(self) -> dict[str, Any]:
        return self._profile

    def load_profile(self, name: str) -> dict[str, Any]:
        return self._load_profile_raw(name)

    def save_active_profile(self) -> None:
        _write_json(PROFILES_DIR / f"{self._profile_name}.json", self._profile)

    def save_profile(self, name: str, data: dict[str, Any]) -> None:
        data["profile_name"] = name
        _write_json(PROFILES_DIR / f"{name}.json", data)

    def delete_profile(self, name: str) -> None:
        if name == self._profile_name:
            raise ValueError("Cannot delete the active profile.")
        path = PROFILES_DIR / f"{name}.json"
        if path.exists():
            path.unlink()

    def activate_profile(self, name: str) -> None:
        """Switch to a different profile and notify listeners."""
        path = PROFILES_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Profile '{name}' not found.")
        self._profile_name = name
        self._profile = self._load_profile_raw(name)
        self._server["active_profile"] = name
        self.save_server()
        for cb in self._on_profile_changed:
            cb()

    def create_profile(self, name: str, clone_from: Optional[str] = None) -> None:
        """Create a new profile, optionally cloning from an existing one."""
        dest = PROFILES_DIR / f"{name}.json"
        if dest.exists():
            raise FileExistsError(f"Profile '{name}' already exists.")
        if clone_from:
            src = PROFILES_DIR / f"{clone_from}.json"
            if not src.exists():
                raise FileNotFoundError(f"Source profile '{clone_from}' not found.")
            data = _read_json(src)
            data["profile_name"] = name
        else:
            data = {**DEFAULT_PROFILE, "profile_name": name, "element_registry": {}}
        _write_json(dest, data)

    def rename_profile(self, old_name: str, new_name: str) -> None:
        if old_name == self._profile_name:
            raise ValueError("Cannot rename the active profile while it is active.")
        old_path = PROFILES_DIR / f"{old_name}.json"
        new_path = PROFILES_DIR / f"{new_name}.json"
        if not old_path.exists():
            raise FileNotFoundError(f"Profile '{old_name}' not found.")
        if new_path.exists():
            raise FileExistsError(f"Profile '{new_name}' already exists.")
        shutil.move(str(old_path), str(new_path))
        data = _read_json(new_path)
        data["profile_name"] = new_name
        _write_json(new_path, data)

    # ------------------------------------------------------------------
    # Convenience accessors into active profile sections
    # ------------------------------------------------------------------

    def input_mappings(self) -> dict[str, Any]:
        return self._profile.setdefault("input_mappings", {})

    def set_input_mappings(self, mappings: dict[str, Any]) -> None:
        self._profile["input_mappings"] = mappings
        self.save_active_profile()

    def element_registry(self) -> dict[str, Any]:
        return self._profile.setdefault("element_registry", {})

    def set_element_registry(self, registry: dict[str, Any]) -> None:
        self._profile["element_registry"] = registry
        self.save_active_profile()

    def update_element(self, element_id: str, data: dict[str, Any]) -> None:
        reg = self.element_registry()
        reg[element_id] = data
        self.save_active_profile()

    def update_element_value(self, element_id: str, key: str, value: Any) -> None:
        """Update a single field within an element entry."""
        reg = self.element_registry()
        if element_id in reg:
            reg[element_id][key] = value
            self.save_active_profile()

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def on_profile_changed(self, cb: Callable[[], None]) -> None:
        """Register a callback to be called after a profile switch."""
        self._on_profile_changed.append(cb)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_profile_raw(self, name: str) -> dict[str, Any]:
        path = PROFILES_DIR / f"{name}.json"
        if not path.exists():
            # Fall back to default
            path = PROFILES_DIR / "default.json"
        if not path.exists():
            return {**DEFAULT_PROFILE, "profile_name": name}
        return _read_json(path)


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

config = ConfigManager()
