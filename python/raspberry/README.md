# Pico Firmware

MicroPython firmware for the Raspberry Pi Pico (RP2040) inside the DJI RC.
Reads physical buttons and an analog joystick wired to GPIO pins, streams
data over USB CDC serial to the Flutter app on the RC.

## Files

| File | Purpose |
|------|---------|
| `main.py` | Main firmware — button reading, ADC sampling, 9-byte frame output |
| `config.json` | Pin assignments — edit to match your wiring without changing code |
| `calibrate.py` | GPIO monitor — reports all pin changes for discovering wiring |
| `upload_to_pico.py` | PC script to upload firmware to the Pico via ADB |

## Protocol

9-byte USB CDC frame at 20 Hz (+ on change):

```
[0xAA] [core_lo] [core_hi] [extra_lo] [extra_hi] [joy_x_lo] [joy_x_hi] [joy_y_lo] [joy_y_hi]
```

- **Core bitmask** (16-bit): 10 standard RC buttons (C1, C2, shutter, pause, RTH, switch, circle, arrow)
- **Extra bitmask** (16-bit): Additional buttons (hat switch, second switch, red button, joy click)
- **Analog X/Y**: Raw ADC `read_u16()` values (0-65535), little-endian

## Uploading Firmware

### Prerequisites
- DJI RC connected to PC via USB (ADB)
- Flutter app installed on the RC

### Upload command

```bash
# Upload main.py + config.json (default)
python upload_to_pico.py

# Upload only config (e.g. after changing pin assignments)
python upload_to_pico.py config.json

# Upload calibration script (renamed to main.py on the Pico)
python upload_to_pico.py calibrate.py

# Restore normal firmware after calibration
python upload_to_pico.py main.py config.json
```

The script pushes files to the RC via `adb push`, then restarts the Flutter
app. On startup, the app auto-detects pending firmware files in its storage
and uploads them to the Pico via raw REPL. Progress is visible in logcat:

```bash
python/server/adb/adb.exe logcat -s PicoPlugin PicoUsbReader
```

Upload takes ~3 minutes for `main.py` (~10 KB via base64 chunks over raw REPL).

## Pin Configuration

Edit `config.json` to match your wiring. Three sections:

- `pins` — Core buttons (10 standard buttons, active-low with external pull-ups)
- `extra_pins` — Additional buttons (active-low with external pull-ups)
- `analog_pins` — Analog axes (ADC-capable pins: 26, 27, 28)

All digital pins use external pull-up resistors (no internal pull-ups configured).
Buttons are active-low: GPIO reads LOW when pressed, HIGH when released.

## Calibration

To discover which GPIO pin each button is wired to:

```bash
python upload_to_pico.py calibrate.py
```

Then open the GPIO Monitor in the Flutter app's Settings tab. Press buttons
one at a time — the monitor reports which GPIO changed state. ADC values
for analog pins update at 5 Hz. LED blinks fast (4 Hz) to indicate
calibration mode.

After calibration, update `config.json` with the correct pin numbers and
upload the normal firmware:

```bash
python upload_to_pico.py main.py config.json
```
