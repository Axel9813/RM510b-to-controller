"""
Raspberry Pi Pico — Button reader firmware (MicroPython).

Reads physical buttons wired to GPIO pins on the DJI RC and streams
a combined frame over USB CDC serial to the Flutter app running on the
RC's Android system.

Protocol:
    9-byte frame: [0xAA] [core_lo] [core_hi] [extra_lo] [extra_hi]
                         [joy_x_lo] [joy_x_hi] [joy_y_lo] [joy_y_hi]
    Core bitmask: 16-bit, bits 0-9 (standard RC buttons).
    Extra bitmask: 16-bit, bits 0-8 (additional buttons, varies per build).
    Analog X/Y: raw ADC read_u16() values (0-65535), little-endian.
    Sent on every state change + heartbeat every 50 ms.

Pin config is loaded from config.json on the Pico's flash filesystem.
Edit config.json to reassign GPIO pins without changing this code.
"""

import json
import sys
import time
from machine import Pin, ADC

# Turn LED on immediately — if you don't see this, MicroPython isn't running main.py
_led = Pin(25, Pin.OUT)
_led.on()

# ── Constants ────────────────────────────────────────────────────────────────

SYNC_BYTE = 0xAA
HEARTBEAT_MS = 50  # send even if unchanged (keepalive)
ADC_THRESHOLD = 512  # minimum ADC change to trigger a send

# Default pin assignments — overridden by config.json if present.
DEFAULT_PINS = {
    "c1": 22,
    "c2": 10,
    "shutter_half": 19,
    "pause": 14,
    "rth": 17,
    "switch_a": 15,
    "switch_b": 16,
    "circle": 20,
    "arrow": 13,
    "shutter_full": 18,
}

DEFAULT_EXTRA_PINS = {
    "joy_click": 0,
    "hat_push": 1,
    "hat_left": 2,
    "hat_up": 3,
    "hat_down": 4,
    "hat_right": 5,
    "switch2_up": 11,
    "switch2_down": 12,
    "red_btn": 21,
}

DEFAULT_ANALOG_PINS = {
    "joy_x": 28,
    "joy_y": 27,
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

# Extra button name → bitmask bit position.
# Must match _PICO_EXTRA_BIT_MAP in input_router.py.
EXTRA_BIT_MAP = {
    "joy_click": 0,
    "hat_push": 1,
    "hat_left": 2,
    "hat_up": 3,
    "hat_down": 4,
    "hat_right": 5,
    "switch2_up": 6,
    "switch2_down": 7,
    "red_btn": 8,
}


# ── Config ───────────────────────────────────────────────────────────────────

def load_config():
    """Load config.json, falling back to defaults on any error."""
    try:
        with open("config.json", "r") as f:
            cfg = json.load(f)
        pins = cfg.get("pins", DEFAULT_PINS)
        extra_pins = cfg.get("extra_pins", DEFAULT_EXTRA_PINS)
        analog_pins = cfg.get("analog_pins", DEFAULT_ANALOG_PINS)
        poll_ms = cfg.get("poll_interval_ms", DEFAULT_POLL_MS)
        debounce_ms = cfg.get("debounce_ms", DEFAULT_DEBOUNCE_MS)
        return pins, extra_pins, analog_pins, poll_ms, debounce_ms
    except Exception:
        return (dict(DEFAULT_PINS), dict(DEFAULT_EXTRA_PINS),
                dict(DEFAULT_ANALOG_PINS), DEFAULT_POLL_MS, DEFAULT_DEBOUNCE_MS)


# ── GPIO setup ───────────────────────────────────────────────────────────────

def setup_pins(pin_map, bit_map):
    """
    Create Pin objects for each button.

    All buttons use EXTERNAL pull-up resistors and are active-low
    (shorted to GND when pressed). We configure as INPUT with no
    internal pull to avoid interfering with the external resistors.

    Returns: list of (name, Pin) tuples in bit-order.
    """
    buttons = []
    for name in sorted(bit_map, key=bit_map.get):
        gpio = pin_map.get(name)
        if gpio is None:
            continue
        pin = Pin(gpio, Pin.IN)  # external pull-up, no internal pull
        buttons.append((name, pin))
    return buttons


def setup_adcs(analog_pins):
    """Create ADC objects for analog inputs. Returns list of (name, ADC)."""
    adcs = []
    for name, gpio in analog_pins.items():
        adcs.append((name, ADC(gpio)))
    return adcs


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


def send_frame(core_bitmask, extra_bitmask, analog_x, analog_y):
    """Write a 9-byte frame to USB CDC serial."""
    _write(bytes([
        SYNC_BYTE,
        core_bitmask & 0xFF, (core_bitmask >> 8) & 0xFF,
        extra_bitmask & 0xFF, (extra_bitmask >> 8) & 0xFF,
        analog_x & 0xFF, (analog_x >> 8) & 0xFF,
        analog_y & 0xFF, (analog_y >> 8) & 0xFF,
    ]))


# ── Main loop ────────────────────────────────────────────────────────────────

def main():
    pin_map, extra_pin_map, analog_pin_map, poll_ms, debounce_ms = load_config()
    core_buttons = setup_pins(pin_map, BIT_MAP)
    extra_buttons = setup_pins(extra_pin_map, EXTRA_BIT_MAP)
    adcs = setup_adcs(analog_pin_map)

    total_buttons = len(core_buttons) + len(extra_buttons)
    if total_buttons == 0 and len(adcs) == 0:
        # Nothing configured — halt
        while True:
            time.sleep_ms(1000)

    debouncer = Debouncer(total_buttons, debounce_ms)

    last_core = -1        # last core bitmask sent (-1 forces initial send)
    last_extra = -1       # last extra bitmask sent
    last_ax = -1          # last analog X sent
    last_ay = -1          # last analog Y sent
    last_send_time = 0    # ticks_ms of last send
    led_toggle_time = 0   # slow blink while running

    # ADC smoothing: 4-sample moving average
    ax_buf = [0] * 4
    ay_buf = [0] * 4
    adc_idx = 0

    while True:
        now = time.ticks_ms()
        core_bitmask = 0
        extra_bitmask = 0

        # Read core buttons
        for i, (name, pin) in enumerate(core_buttons):
            raw = 1 if pin.value() == 0 else 0
            debounced = debouncer.update(i, raw, now)
            if debounced:
                core_bitmask |= (1 << BIT_MAP[name])

        # Read extra buttons
        core_count = len(core_buttons)
        for i, (name, pin) in enumerate(extra_buttons):
            raw = 1 if pin.value() == 0 else 0
            debounced = debouncer.update(core_count + i, raw, now)
            if debounced:
                extra_bitmask |= (1 << EXTRA_BIT_MAP[name])

        # Read analog with smoothing
        analog_x = 0
        analog_y = 0
        if adcs:
            for aname, adc in adcs:
                val = adc.read_u16()
                if aname == "joy_x":
                    ax_buf[adc_idx % 4] = val
                    analog_x = sum(ax_buf) // 4
                elif aname == "joy_y":
                    ay_buf[adc_idx % 4] = val
                    analog_y = sum(ay_buf) // 4
            adc_idx += 1

        # Detect changes
        digital_changed = (core_bitmask != last_core or
                           extra_bitmask != last_extra)
        analog_changed = (abs(analog_x - last_ax) > ADC_THRESHOLD or
                          abs(analog_y - last_ay) > ADC_THRESHOLD)
        heartbeat_due = time.ticks_diff(now, last_send_time) >= HEARTBEAT_MS

        if digital_changed or analog_changed or heartbeat_due:
            send_frame(core_bitmask, extra_bitmask, analog_x, analog_y)
            last_core = core_bitmask
            last_extra = extra_bitmask
            last_ax = analog_x
            last_ay = analog_y
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
