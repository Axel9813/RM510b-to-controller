"""
Raspberry Pi Pico — Button reader firmware (MicroPython).

Reads physical buttons wired to GPIO pins on the DJI RC and streams
a 16-bit bitmask over USB CDC serial to the Flutter app running on the
RC's Android system.

Protocol:
    3-byte frame: [0xAA] [bitmask_low] [bitmask_high]
    Sent on every state change + heartbeat every 50 ms.

Pin config is loaded from config.json on the Pico's flash filesystem.
Edit config.json to reassign GPIO pins without changing this code.
"""

import json
import sys
import time
from machine import Pin

# Turn LED on immediately — if you don't see this, MicroPython isn't running main.py
_led = Pin(25, Pin.OUT)
_led.on()

# ── Constants ────────────────────────────────────────────────────────────────

SYNC_BYTE = 0xAA
HEARTBEAT_MS = 50  # send even if unchanged (keepalive)

# Default pin assignments — overridden by config.json if present.
DEFAULT_PINS = {
    "c1": 2,
    "c2": 3,
    "shutter_half": 4,
    "pause": 5,
    "rth": 6,
    "switch_a": 7,
    "switch_b": 8,
    "circle": 9,
    "arrow": 10,
    "shutter_full": 11,
}

DEFAULT_POLL_MS = 5
DEFAULT_DEBOUNCE_MS = 10

# Button name → bitmask bit position.
# Must match PicoState in Flutter and _PICO_BIT_MAP in input_router.py.
BIT_MAP = {
    "c1": 0,
    "c2": 1,
    "shutter_half": 2,
    "pause": 3,
    "rth": 4,
    "switch_a": 5,
    "switch_b": 6,
    "circle": 7,
    "arrow": 8,
    "shutter_full": 9,
}


# ── Config ───────────────────────────────────────────────────────────────────

def load_config():
    """Load config.json, falling back to defaults on any error."""
    try:
        with open("config.json", "r") as f:
            cfg = json.load(f)
        pins = cfg.get("pins", DEFAULT_PINS)
        poll_ms = cfg.get("poll_interval_ms", DEFAULT_POLL_MS)
        debounce_ms = cfg.get("debounce_ms", DEFAULT_DEBOUNCE_MS)
        return pins, poll_ms, debounce_ms
    except Exception:
        return dict(DEFAULT_PINS), DEFAULT_POLL_MS, DEFAULT_DEBOUNCE_MS


# ── GPIO setup ───────────────────────────────────────────────────────────────

def setup_pins(pin_map):
    """
    Create Pin objects for each button.

    All buttons use EXTERNAL pull-up resistors and are active-low
    (shorted to GND when pressed). We configure as INPUT with no
    internal pull to avoid interfering with the external resistors.

    Returns: list of (name, Pin) tuples in bit-order.
    """
    buttons = []
    for name in sorted(BIT_MAP, key=BIT_MAP.get):
        gpio = pin_map.get(name)
        if gpio is None:
            continue
        pin = Pin(gpio, Pin.IN)  # external pull-up, no internal pull
        buttons.append((name, pin))
    return buttons


# ── Debounce ─────────────────────────────────────────────────────────────────

class Debouncer:
    """Per-button debouncer using timestamp-based stability check."""

    def __init__(self, count, debounce_ms):
        self._debounce_ms = debounce_ms
        # Stable (debounced) state per button: 0 = released, 1 = pressed
        self._state = [0] * count
        # Raw reading at last change
        self._raw = [0] * count
        # Timestamp (ms) of last raw change
        self._last_change = [0] * count

    def update(self, index, raw_value, now_ms):
        """Update one button. Returns the debounced value (0 or 1)."""
        if raw_value != self._raw[index]:
            self._raw[index] = raw_value
            self._last_change[index] = now_ms

        if raw_value != self._state[index]:
            if (now_ms - self._last_change[index]) >= self._debounce_ms:
                self._state[index] = raw_value

        return self._state[index]


# ── Serial output ────────────────────────────────────────────────────────────

# Resolve the write function once at import time.
# MicroPython: sys.stdout.write() accepts bytes directly.
# Some builds also have sys.stdout.buffer — try that first for safety.
_write = getattr(sys.stdout, 'buffer', sys.stdout).write


def send_bitmask(bitmask):
    """Write a 3-byte frame to USB CDC serial."""
    _write(bytes([SYNC_BYTE, bitmask & 0xFF, (bitmask >> 8) & 0xFF]))


# ── Main loop ────────────────────────────────────────────────────────────────

def main():
    pin_map, poll_ms, debounce_ms = load_config()
    buttons = setup_pins(pin_map)

    if not buttons:
        # No buttons configured — halt (nothing we can do)
        while True:
            time.sleep_ms(1000)

    debouncer = Debouncer(len(buttons), debounce_ms)
    last_sent = -1       # last bitmask value sent (-1 forces initial send)
    last_send_time = 0   # ticks_ms of last send
    led_toggle_time = 0  # slow blink while running

    while True:
        now = time.ticks_ms()
        bitmask = 0

        for i, (name, pin) in enumerate(buttons):
            # Active-low: pin reads 0 when pressed → we want bit = 1
            raw = 1 if pin.value() == 0 else 0
            debounced = debouncer.update(i, raw, now)
            if debounced:
                bitmask |= (1 << BIT_MAP[name])

        # Send on change or as heartbeat
        changed = bitmask != last_sent
        heartbeat_due = time.ticks_diff(now, last_send_time) >= HEARTBEAT_MS

        if changed or heartbeat_due:
            send_bitmask(bitmask)
            last_sent = bitmask
            last_send_time = now

        # Slow LED blink (1s on / 1s off) = main loop alive
        if time.ticks_diff(now, led_toggle_time) >= 1000:
            _led.toggle()
            led_toggle_time = now

        time.sleep_ms(poll_ms)


# ── Entry ────────────────────────────────────────────────────────────────────

# Wrap in try/except so a crash doesn't silently die —
# error text goes to CDC where the reader can at least see bytes flowing.
try:
    main()
except Exception as e:
    # Print error to CDC so it's visible in Android logcat raw data
    sys.stdout.write("PICO ERROR: ")
    sys.stdout.write(str(e))
    sys.stdout.write("\n")
    # Keep retrying after a pause
    time.sleep(3)
    import machine
    machine.soft_reset()
