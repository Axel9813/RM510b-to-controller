# Raspberry Pi Pico — Implementation Plan

## Overview

The Pico reads physical buttons on the DJI RC that are inaccessible to the
Android app (C1, C2, shutter half/full, pause, RTH, 3-pos switch, circle,
arrow). It packs their state into a 16-bit bitmask and streams it to the
Flutter app over USB CDC serial. The Flutter app merges this bitmask into
the `rc_state` JSON sent to the Python server at 50 Hz.

```
Buttons → GPIO (Pico) → USB CDC serial → Android (Flutter) → WebSocket → PC
```

---

## 1. Hardware Wiring

All buttons are **active-low** (short to GND when pressed) with **external
pull-up resistors** already provided by the user.

The **3-position switch** uses two pins:
- Pin A shorted to GND → position 1
- Pin B shorted to GND → position 3
- Neither shorted      → position 2

### Default Pin Assignment (configurable via `config.json`)

| Button           | Bitmask bit | Default GPIO |
|------------------|-------------|--------------|
| C1               | 0           | GP2          |
| C2               | 1           | GP3          |
| Shutter half     | 2           | GP4          |
| Pause            | 3           | GP5          |
| Return to Home   | 4           | GP6          |
| Switch pin A     | 5           | GP7          |
| Switch pin B     | 6           | GP8          |
| Circle           | 7           | GP9          |
| Arrow            | 8           | GP10         |
| Shutter full     | 9           | GP11         |

Bits 10-15 are reserved (sent as 0).

> These bits match the existing `PicoState` model in Flutter and the
> `_PICO_BIT_MAP` in `python/server/input_router.py` exactly.

---

## 2. Pico Firmware (MicroPython)

### Why MicroPython
- First-class support on RP2040 (official Raspberry Pi firmware)
- Built-in USB CDC serial — no driver needed, appears as a serial port
- Simple `sys.stdin`/`sys.stdout` for USB serial I/O
- JSON support for config file
- Negligible latency for GPIO reads + serial writes

### Files on Pico flash

```
/
├── main.py          # firmware entry point (auto-runs on boot)
└── config.json      # pin assignment (user-editable)
```

### config.json

```json
{
  "pins": {
    "c1": 2,
    "c2": 3,
    "shutter_half": 4,
    "pause": 5,
    "rth": 6,
    "switch_a": 7,
    "switch_b": 8,
    "circle": 9,
    "arrow": 10,
    "shutter_full": 11
  },
  "poll_interval_ms": 5,
  "debounce_ms": 10
}
```

The `pins` keys are fixed names mapping to GPIO numbers. Users can
reassign GPIOs by editing this file (Pico appears as a USB drive when
BOOTSEL is held — copy a new `config.json`).

### main.py — Firmware Logic

```
1. Load config.json (fall back to defaults if missing/corrupt)
2. Configure each GPIO as INPUT (no internal pull-up — external resistors)
3. Main loop (runs at ~200 Hz = 5 ms interval):
   a. Read all pins → build 16-bit bitmask
      - Button pressed (pin LOW) → bit = 1
      - Button released (pin HIGH) → bit = 0
   b. Debounce: only update a bit if it has been stable for debounce_ms
   c. If bitmask changed since last send OR 50 ms since last send:
      - Write 3-byte frame to USB serial: [0xAA, low_byte, high_byte]
   d. Sleep until next poll interval
```

### USB Serial Protocol

**Frame format: 3 bytes**

```
Byte 0:  0xAA          (sync/header)
Byte 1:  bitmask[7:0]  (low byte)
Byte 2:  bitmask[15:8] (high byte)
```

- USB CDC is reliable (error-free at USB level), so no checksum needed.
- The 0xAA header lets the reader re-sync if it starts mid-stream.
- At worst-case 200 Hz sending: 600 bytes/sec — negligible bandwidth.

### Sending Strategy

- **On change**: send immediately when debounced bitmask differs from last sent
- **Heartbeat**: send every 50 ms even if unchanged (so the Android side
  can detect disconnection if no data arrives for >100 ms)
- This hybrid approach keeps latency < 5 ms for button presses while
  providing a keepalive signal.

---

## 3. Flutter App Integration

### Android Side (Kotlin)

Create a new `PicoUsbReader.kt` following the same pattern as the existing
`RcUsbReader.kt`:

| Aspect          | RcUsbReader (existing)       | PicoUsbReader (new)         |
|-----------------|------------------------------|-----------------------------|
| Device          | DJI HID (VID 0x2CA3)        | Pico CDC (VID 0x2E8A)      |
| Interface class | HID (class 3)               | CDC Data (class 0x0A)       |
| Transfer type   | Interrupt (via bulkTransfer) | Bulk IN                     |
| Packet size     | 18 bytes fixed               | 3 bytes (framed)            |
| Output          | `RcState`                    | `Int` (16-bit bitmask)      |

**Steps:**

1. **`PicoUsbReader.kt`** — New class:
   - Find Pico device: VID `0x2E8A`, PID `0x0005` (MicroPython CDC)
   - Claim CDC Data interface (class 10 / 0x0A)
   - Find bulk IN endpoint
   - Background thread reads continuously with `bulkTransfer()`
   - Parse 3-byte frames: scan for `0xAA` header, extract 2-byte bitmask
   - Callback: `onBitmask: (Int) -> Unit`

2. **`PicoPlugin.kt`** — New platform channel plugin:
   - MethodChannel: `'com.dji.rc/pico'`
     - `start` — find device, request permission, start reader
     - `stop` — stop reader
     - `status` — return connection state
   - EventChannel: `'com.dji.rc/pico_state'`
     - Stream bitmask updates to Dart side

3. **`usb_device_filter.xml`** — Add Pico VID:
   ```xml
   <usb-device vendor-id="11914" />  <!-- 0x2E8A = Raspberry Pi -->
   ```

4. **`MainActivity.kt`** — Register `PicoPlugin` alongside existing `RcPlugin`

### Dart Side (Flutter)

Replace the stub `PicoService` with a real implementation:

```dart
class PicoService extends ChangeNotifier {
  static const _method = MethodChannel('com.dji.rc/pico');
  static const _events = EventChannel('com.dji.rc/pico_state');

  PicoState _state = const PicoState();
  String _status = 'disconnected';
  StreamSubscription? _sub;

  PicoState get state => _state;
  String get status => _status;
  int get bitmask => _state.bitmask;

  Future<void> start() async {
    final ok = await _method.invokeMethod<bool>('start');
    _status = (ok == true) ? 'connected' : 'waiting for permission';
    notifyListeners();

    _sub ??= _events.receiveBroadcastStream().listen((data) {
      final mask = data as int;
      if (mask != _state.bitmask) {
        _state = PicoState(bitmask: mask);
        notifyListeners();
      }
    });
  }

  void stop() { ... }
}
```

### Integration (already wired)

The `MainScreen` already merges `picoService.bitmask` into `RcState` before
sending via WebSocket (see `main_screen.dart:31-37`). No changes needed
there — once `PicoService` emits real bitmask values, they flow through
automatically.

---

## 4. Python Server Side

**No changes needed.** The `input_router.py` already:
- Decodes `picoBitmask` from `rc_state` messages (`_PICO_BIT_MAP`)
- Maps pico button fields to vJoy/system actions
- The bitmask bit positions match between Pico firmware, Flutter model,
  and Python decoder

---

## 5. USB Topology

The DJI RC510B has:
- **Internal USB bus**: DJI HID joystick (VID 0x2CA3, PID 0x1501) — sticks,
  wheels, 5D button, record, shutter
- **External USB-C male connector**: Located in a compartment under the back
  plate, intended for connecting external modules

The Pico (which has a USB-C female connector) plugs directly into this
external USB-C male port via a USB-C cable. The Android USB host API
(`UsbManager.deviceList`) sees both the internal DJI HID device and the
external Pico CDC device as separate entries filtered by VID. They
coexist without conflict.

---

## 6. Implementation Order

### Phase A — Pico firmware (can test standalone via PC serial terminal)
1. Write `main.py` + `config.json` for Pico
2. Flash MicroPython firmware onto Pico
3. Copy `main.py` and `config.json` to Pico
4. Test: open serial terminal on PC, press buttons, verify bitmask frames

### Phase B — Android USB reader
1. Create `PicoUsbReader.kt` (CDC bulk reader)
2. Create `PicoPlugin.kt` (platform channel bridge)
3. Add Pico VID to `usb_device_filter.xml`
4. Register plugin in `MainActivity.kt`

### Phase C — Flutter service
1. Replace `PicoService` stub with real implementation
2. Test on RC: verify bitmask appears in `PicoState`

### Phase D — End-to-end
1. Connect Pico to RC, run Flutter app
2. Verify buttons appear in `rc_state` WebSocket stream on PC
3. Verify `input_router.py` decodes pico fields correctly
4. Map pico buttons to vJoy axes/buttons in profile config

---

## 7. Latency Budget

| Stage                        | Estimated latency |
|------------------------------|-------------------|
| GPIO read + debounce         | 5-10 ms           |
| USB CDC serial transfer      | 1-2 ms            |
| Android bulk read + parse    | 1-5 ms            |
| Flutter event channel        | < 1 ms            |
| WebSocket send (next 20ms tick) | 0-20 ms        |
| **Total button → server**    | **~8-38 ms**      |

Well within acceptable range for a gaming controller.
