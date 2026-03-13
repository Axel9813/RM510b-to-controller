Fixes:

0. ~~DONE~~ Pico input not being captured reliably (sometimes shows connected status but not capturing inputs at all).

   **What was done:**
   - Diagnosed root cause: Pico was entering BOOTSEL mode (PID 0x0003) on the RC's USB port, so MicroPython never ran (confirmed via LED test and ADB USB enumeration).
   - Implemented PICOBOOT reboot protocol in `PicoUsbReader.rebootFromBootsel()` — sends EXCLUSIVE_ACCESS + REBOOT commands via bulk OUT on the vendor-specific interface (class 0xFF), reads ACK from bulk IN.
   - Added BOOTSEL recovery loop in `PicoPlugin.handleStartWithBootselRecovery()` — retries up to 5 times with 4s waits between PICOBOOT reboots.
   - Removed unsafe vendor-class fallback in `findCdcDataInterface()` that was matching PICOBOOT/mass-storage interfaces instead of CDC Data (class 0x0A).
   - Added soft-reboot sequence (Ctrl+C + Ctrl+D via bulk OUT) to restart main.py if Pico is stuck in REPL mode.
   - Added CDC ACM DTR/RTS line activation for proper serial handshake.
   - Fixed `sys.stdout.buffer` portability in main.py: `_write = getattr(sys.stdout, 'buffer', sys.stdout).write`.
   - Added crash recovery in main.py: try/except around `main()` that prints error to CDC then does `machine.soft_reset()`.
   - Fixed duplicate reader thread race condition: added `synchronized(startLock)` guard and `@Volatile` on reader field, stale readers stopped before new start.
   - Added USB disconnect detection: 50 consecutive `-1` bulkTransfer results (~5s) triggers stop + error callback instead of spinning forever.
   - Removed broken CircuitPython `import storage` from boot.py (MicroPython-only now).

1. ~~DONE~~ vJoy not capturing output of app. In frontend stick movements and button presses are visible but they are not reaching vJoy.

   **What was done:**
   - Elevated all vJoy error logging from DEBUG to WARNING level so `set_axis`/`set_button` failures are visible in normal log output.
   - Added `_error` field to `VJoyHandler` that stores the failure reason (exposed via `error` property).
   - Startup `start()` now logs actionable message on failure: "Make sure vJoy driver is installed and device N is configured in vJoyConf."
   - Added one-time warning when vJoy is inactive and axis/button commands are attempted (logs once, not every frame).
   - Exposed `vjoy_error` in `/api/status` REST endpoint, monitor WebSocket `initial_state`, and 20Hz `monitor_update` broadcasts.
   - Updated PC frontend `setVJoyStatus()` to show error reason next to the status pill (e.g. "vJoy: inactive (pyvjoy not installed)").
   - The green/red status dot in the frontend header was already present — now it shows the error reason when inactive.

2. ~~DONE~~ Shutter stage 1 clearly being captured by Android app itself not by Raspberry, I think both should be handled by one way (Raspberry).

   **What was done:**
   - Removed `shutter` field from `RcState.kt` — no longer parsed from HID byte 16 bit 3, no longer in `toMap()`.
   - Removed `"shutter"` from `HID_BUTTON_FIELDS` in `input_router.py`.
   - Removed `"shutter"` mapping from default profile in `config_manager.py`.
   - Removed `"shutter"` entry from frontend `config_editor.js` field catalog.
   - Updated `rc_visualizer.js` right trigger display to use only Pico `shutter_half` (bit 2) and `shutter_full` (bit 9), removed HID shutter OR-merge.
   - Shutter is now exclusively handled by the Pico via `pico_shutter_half` and `pico_shutter_full` GPIO inputs.

3. ~~DONE~~ Outputs of elements placed on customizable interface not being displayed correctly on frontend monitor.

   **What was done:**
   - Added `_notify_monitors_state()` helper in `output_manager.py` that broadcasts `element_state_update` messages to all browser monitor WebSocket clients.
   - `toggle()` and `set_value()` now call `_notify_monitors_state()` after changing LED state — browser UI updates immediately.
   - `handle_element_event()` now broadcasts button press/release and slider value changes to browser clients — RC-side interactions are reflected live.
   - Added `element_state_update` message handler in `app.js` that routes to `ConfigEditor.updateElementState()`.
   - Added `updateElementState()` in `config_editor.js` — updates local element cache and re-renders both the config table and the SVG visualizer.
   - Updated SVG `setScreenElements()` in `rc_visualizer.js` — buttons highlight on press (yellow dot + brighter border), sliders show a position bar, LEDs show green/grey dot. Each type visually distinct.
   - **Element positioning:** `merge_hello()` now stores `grid_x/y/w/h` from Flutter hello messages. Grid data is always updated on reconnect (user may have moved elements). The SVG visualizer positions elements at their actual grid coordinates scaled to the screen area.
   - **Dynamic grid dimensions:** Flutter hello message now includes `gridCols`/`gridRows` (computed from `MediaQuery` screen size and cellSize formula). Python stores and exposes them via REST `/api/status` and WebSocket `initial_state`/`registry_update`. Frontend uses these to scale the SVG screen grid accurately. Fallback to 16×9 if RC hasn't connected yet.
   - Added `_syncScreenElements()` call to `renderAll()` so the REST load path (initial page load, profile switches) also syncs the SVG screen — previously only the WebSocket path did.

4. ~~DONE~~ In Flutter app interface Pico status indicator not changing (leftover from time when it was not fully implemented).

   **What was done:**
   - Changed `connected: false` to `connected: picoService.status == 'connected'` in `settings_tab.dart`.
   - Verified `PicoService` extends `ChangeNotifier` and settings tab uses `context.watch<PicoService>()` — rebuilds automatically on status changes.

5. ~~DONE~~ On customizable interface on PC frontend displayed nonexistent "Test" button.

   **What was done:**
   - Fixed `merge_hello()` in `output_manager.py` to prune stale elements: any registry entry whose ID is NOT in the incoming Flutter hello elements list is deleted.
   - On each RC connection, the Flutter app sends its current element list via hello. Elements deleted on the RC are now automatically removed from the server registry and the PC frontend.
   - No more orphaned entries accumulating — the registry stays in sync with the Flutter app's actual interface layout.

6. ~~DONE~~ system_actions pycaw not available ('AudioDevice' object has no attribute 'Activate') — volume_set will not work.

   **What was done:**
   - Root cause: pycaw v20251023 changed `AudioUtilities.GetSpeakers()` to return an `AudioDevice` wrapper instead of a raw COM `IMMDevice`. The old code called `.Activate()` which doesn't exist on the wrapper.
   - Fixed by using `speakers.EndpointVolume` property (returns `IAudioEndpointVolume` directly) instead of manual `Activate()` + `QueryInterface()`.
   - Added `comtypes.CoInitialize()` before pycaw initialization for thread safety.
   - Elevated log level from `info` to `warning` on failure so it's visible in normal output.
   - Removed unused `IAudioEndpointVolume` and `CLSCTX_ALL` imports.

---

Improvements:

1. ~~DONE~~ RC input takes a few tries with app restarting to be captured.

   **What was done:**
   - Added retry logic in `RcPlugin.kt`: up to 5 attempts with 3s delays when device not found or reader fails to start. Retry counter resets on success or manual reconnect.
   - Added `USB_DEVICE_ATTACHED` broadcast receiver in `RcPlugin.kt` — automatically retries `handleStart()` when a new USB device is plugged in (covers late enumeration).
   - Moved RC initialization from `SettingsTab.initState()` to `main.dart` — `rcService.start()` now runs at app launch alongside Pico/Gyro services.
   - Added `reconnect` method channel command — stops existing reader, resets retry counter, and does a fresh start cycle. Exposed as `RcStateService.reconnect()` in Dart.
   - Added "Reconnect" button in Settings tab next to RC Input status row (shown only when disconnected).
   - Event stream listener is now idempotent (won't double-subscribe) and starts even on initial failure, so events flow immediately when Kotlin retries succeed later.
   - Each retry attempt is logged with attempt number (`RC start: scheduling retry 2/5 in 3000ms`).

2. ~~DONE (Phase 1)~~ Implement extendable configuration for adding more physical input devices (buttons/axes).

   **What was done (extra buttons + analog joystick):**
   - Extended Pico protocol from 3-byte to 9-byte frames: `[0xAA][core_lo][core_hi][extra_lo][extra_hi][joy_x_lo][joy_x_hi][joy_y_lo][joy_y_hi]`.
   - Core buttons (10) kept separate from extras (9) throughout the entire pipeline. Extras are build-specific — different RC builds can have different extras or none at all.
   - **Pico firmware** (`python/raspberry/main.py`): Added `EXTRA_BIT_MAP`, `DEFAULT_EXTRA_PINS`, `DEFAULT_ANALOG_PINS`, ADC setup with 4-sample moving average, debouncing for extra buttons. Config-driven pin assignments via `config.json`.
   - **Kotlin** (`PicoUsbReader.kt`): 9-byte frame parser with ring buffer. `PicoPlugin.kt`: frame callback changed from `Int` to `IntArray[core, extra, joyX, joyY]`.
   - **Flutter**: `PicoState` extended with `extraBitmask`, `analogX`, `analogY`. `PicoService` parses `List<int>` frames. `RcState` carries `picoExtraBitmask`, `picoAnalogX`, `picoAnalogY` to server.
   - **Python server** (`input_router.py`): `PICO_EXTRA_BUTTON_FIELDS`, `_PICO_EXTRA_BIT_MAP`, `decode_pico_extra_bitmask()`. Extras included in `BUTTON_FIELDS` for edge detection and action dispatch.
   - **Frontend**: Extras sidebar in `rc_visualizer.js` (hat switch cluster, analog joystick crosshair, switch 2, red button, joy click). Config editor includes extras with `source: "pico_extra"`.
   - **PC upload script** (`python/raspberry/upload_to_pico.py`): Pushes firmware files via ADB, restarts app; app auto-detects pending firmware on Pico reader start and uploads via raw REPL.
   - **Calibration** (`python/raspberry/calibrate.py`): Updated with ADC monitoring at 200ms intervals for joystick tracking.

   **Remaining (Phase 2 — future):**
   - [ ] Create abstract `InputDevice` base class for dynamic device registration.
   - [ ] Refactor `InputRouter` to build field sets from device registry instead of hardcoded frozensets.
   - [ ] Add analog joystick action mapping (currently raw values passed through, no vJoy/mouse mapping).

3. ~~DONE~~ Capture gyro/accelerometer data and use it as additional input axes.

   **What was done:**
   - Confirmed DJI RC has ICM4x6xx accelerometer + gyroscope (500Hz, no permissions required) via ADB `dumpsys sensorservice`.
   - Chose Game Rotation Vector (fused accel+gyro, Qualcomm hardware fusion) as primary sensor — no drift on pitch/roll, slow yaw drift. Runtime toggle to full Rotation Vector (adds magnetometer) available.
   - **Kotlin `SensorPlugin.kt`** (NEW): Native sensor reader implementing MethodCallHandler + StreamHandler + SensorEventListener. MethodChannel `com.dji.rc/sensor` (start/stop/zero/setSensorType/status), EventChannel `com.dji.rc/sensor_state` streaming `[pitch, yaw, roll]` radians at 50Hz. Computes relative orientation via `R_ref^T × R_current` matrix multiplication, Euler extraction via `SensorManager.getOrientation()`. Thread-safe `@Volatile refMatrix` with local snapshot pattern. NaN guard on output.
   - **Flutter `GyroService`** (NEW): ChangeNotifier storing pitch/yaw/roll doubles. Methods: start/stop/zero/setSensorType.
   - **Flutter `main_screen.dart`**: Merges gyro values into WebSocket state JSON (`gyroPitch`/`gyroYaw`/`gyroRoll`). Both rcService and gyroService trigger sendState. Listens for incoming `gyro_zero`/`gyro_set_sensor` WebSocket commands from PC.
   - **Python `input_router.py`**: Full gyro processing pipeline — push-to-activate gating (suppress activate button's normal mapping), PC-side auto-zero offset on activate press (no round-trip latency), per-axis deadzone→sensitivity→invert→action dispatch. vJoy axis output: radians scaled to ±660. Mouse output: tilt-as-velocity via `SystemActions.mouse_move()`. Axes zeroed on activate button release. NaN/Inf guard on all gyro values.
   - **Python `system_actions.py`**: Added `mouse_move(dx, dy)` using pynput MouseController for relative cursor movement.
   - **Python `config_manager.py`**: `DEFAULT_GYRO_CONFIG` with full defaults, `gyro_config()`/`set_gyro_config()` accessors.
   - **Python `server.py`**: REST endpoints GET/PATCH `/api/config/gyro`, POST `/api/gyro/zero`, POST `/api/gyro/sensor-type`. Deep merge on PATCH to preserve nested axis sub-dicts. Forwards zero/sensor-type commands to RC via WebSocket.
   - **Frontend config**: Dedicated "Gyro / Motion Control" collapsible section with enable toggle, sensor type dropdown, activate button dropdown, per-axis config (action/vjoy_axis/mouse_axis/sensitivity slider/invert), deadzone, mouse speed, zero button. Locked button row in input mappings shows "GYRO ACTIVATE" badge when a button is configured as gyro activator.
   - **Frontend monitor**: Horizontal bar gauges (pitch=blue, yaw=green, roll=orange) showing real-time gyro deflection below RC visualizer SVG. Center-origin bars with numeric labels.
   - **Profile JSON**: `gyro_config` block with `enabled`, `sensor_type`, `activate_button`, `deadzone`, `mouse_speed`, and per-axis `pitch`/`roll`/`yaw` sub-objects.
   - **Orientation lock**: Flutter app locked to landscape.

4. ~~DONE~~ Implement additional transports for PC-controller connection (Bluetooth/USB).

   **What was done:**

   *Transport abstraction layer (both sides):*
   - Defined `RcTransport` abstract base on Flutter (`flutter/lib/services/transport/rc_transport.dart`) and Python (`python/server/transport/base.py`) with `start()`, `stop()`, `send()`, status listeners, and incoming message streams.
   - `TransportManager` on both sides manages multiple transports, selects the best one by priority, and provides a unified interface. Priority order: USB > WiFi (WebSocket) > Bluetooth.
   - Python `TransportManager.make_message_handler()` filters incoming messages so only the active transport's data reaches the server — prevents dual-transport data conflicts.

   *USB transport (ADB tunnel):*
   - Python `UsbTransport` (`python/server/transport/usb_transport.py`): polls for ADB devices, auto-forwards port, delegates to internal `WebSocketTransport` connected to `127.0.0.1`.
   - Flutter detects USB vs WiFi by checking if the WebSocket client address is `127.0.0.1` (loopback = ADB tunnel).
   - Bundled `adb.exe` in `python/server/adb/` — no ADB installation required on the PC.

   *Bluetooth RFCOMM transport:*
   - Python `BluetoothTransport` (`python/server/transport/bluetooth_transport.py`): RFCOMM server on channel 4 using `AF_BTH` (Windows native). Threads for accept/read (IOCP doesn't support `AF_BTH`). SDP registered via `WSASetService` ctypes. Ping/pong handled directly in read thread (no asyncio roundtrip). Only latest `rc_state` per recv batch dispatched to avoid flooding.
   - Flutter `BluetoothTransport` (`flutter/lib/services/transport/bluetooth_transport.dart`): RFCOMM client using platform channels. Two send paths: `_sendRaw` (state, droppable via `AtomicReference`) and `_sendControl` (ping/hello, guaranteed via `ConcurrentLinkedQueue`). Auto-reconnect with backoff.
   - Kotlin `BluetoothPlugin` (`flutter/android/.../BluetoothPlugin.kt`): Native RFCOMM client with dedicated read and write threads. `createRfcommSocket(channel)` via reflection (bypasses SDP for DJI RC Android 10). Connection generation counter guards stale `endOfStream` from old read threads. Thread join with timeout on disconnect.

   *Transport manager features:*
   - Conflict-aware switching: USB and WiFi conflict (both use RC WebSocket server) — old one is stopped. Bluetooth is independent and never stopped when switching.
   - Fallback on disconnect: when active transport disconnects, manager checks for next-highest-priority connected transport and switches to it.
   - Preference enforcement: "Auto" / "WiFi only" / "Bluetooth only" dropdown in Flutter settings. Non-preferred transports are stopped to prevent dual-connection data conflicts.
   - BT target persisted to SharedPreferences; auto-starts on app launch if saved target exists.

   *UI:*
   - Flutter settings: transport preference dropdown, BT paired device list, connect/disconnect buttons, BT availability check (shows warning if BT is off), error display.
   - PC frontend (`app.js`): shows "RC: USB", "RC: WiFi", or "RC: BT" based on active transport type.

   *Key files:*
   - `flutter/lib/services/transport/` — `rc_transport.dart`, `transport_manager.dart`, `websocket_transport.dart`, `bluetooth_transport.dart`
   - `python/server/transport/` — `__init__.py`, `base.py`, `manager.py`, `websocket_transport.py`, `usb_transport.py`, `bluetooth_transport.py`
   - `flutter/android/.../BluetoothPlugin.kt`
   - `flutter/lib/screens/settings_tab.dart` — transport UI section

5. Improve interface customisation:

   5.1. Fix overlaying one item over another.

   **Root cause:** `BuilderOverlay` renders elements in list order with no z-index control. Last element in list is always on top.

   **Plan of approach:**
   - [ ] Add `zIndex` field to `InterfaceElement` model (default 0).
   - [ ] Sort elements by `zIndex` before rendering in `BuilderOverlay.build()`.
   - [ ] Add "Bring to Front" / "Send to Back" options in the element's long-press context menu.
   - [ ] Persist `zIndex` in `toJson()`/`fromJson()`.
   - **Estimated scope:** ~50 lines Dart.

   5.2. Add more input and output item types.

   **Currently available:** Button, Slider (input); LED (output).

   **Plan of approach:**
   - [ ] Design new element types: DPad (4-direction + center), Toggle Switch, Joystick (2D), Progress Bar, Gauge, Text Display.
   - [ ] Extend `InterfaceElement` sealed class with new subclasses.
   - [ ] Create widget for each type in `flutter/lib/widgets/`.
   - [ ] Update factory method in `InterfaceElement.fromJson()`.
   - [ ] Update server's `element_registry` schema to support new types.
   - [ ] Add new element types to the "Add Element" picker in the builder UI.
   - **Estimated scope:** ~800 lines Dart + ~200 lines Python.

   5.3. Implement bidirectional state sync for interface elements (PC→RC).

   **Currently:** One-way RC→PC for input, PC→RC only for LED state updates. Slider elements (e.g. volume_set) have no way to reflect the current system state back on the RC.

   **Research findings:**
   - `element_update` message already exists and is handled by Flutter for LEDs (`interface_tab.dart` line 73). Sliders are NOT handled — only `LedElement.copyWithState()` is called.
   - `SliderElement` model has no `currentValue` field (unlike `LedElement.currentState`).
   - pycaw v20251023 supports `IAudioEndpointVolumeCallback` via `RegisterControlChangeNotify()` for real-time volume change detection. Alternatively, polling `GetMasterVolumeLevelScalar()` in the existing 20Hz monitor loop avoids COM threading complexity.
   - The existing `_schedule_push_to_rc()` + `element_update` pattern works for pushing state to RC.
   - Reverse lookup needed: scan registry for elements with `on_change.action == "system"` and `on_change.fn == "volume_set"` to know which slider to update.

   **Plan of approach:**
   - [ ] Add `currentValue` field to `SliderElement` model (like `LedElement.currentState`), with `copyWithValue()`.
   - [ ] Extend `element_update` handler in `interface_tab.dart` to handle slider elements (update `currentValue`, rebuild UI).
   - [ ] Update `SliderElementWidget` to use `element.currentValue` as the slider position when receiving server updates.
   - [ ] Add `get_volume()` method to `SystemActions` that returns current volume (0.0–1.0) via `GetMasterVolumeLevelScalar()`.
   - [ ] Add volume polling in `OutputManager` or the monitor broadcast loop: compare with last known value, push `element_update` to RC + browser monitors when changed.
   - [ ] Generalize: `OutputManager.poll_system_state()` scans registry for `volume_set` sliders and pushes current volume as their state. Extensible to other system state sources later.
   - [ ] Include slider `current_value` in `get_full_state()` so RC gets correct positions on connect.
   - **Estimated scope:** ~80 lines Dart + ~60 lines Python.

   5.4. Add ability to paint elements in some colors.

   **Plan of approach:**
   - [ ] Add `backgroundColor`, `foregroundColor`, `textColor`, `borderColor` fields to `InterfaceElement`.
   - [ ] Add a color picker to the element editor dialog in the Flutter builder UI.
   - [ ] Update each element widget to use custom colors with fallback to theme defaults.
   - [ ] Persist colors in JSON (hex string format: `"#RRGGBB"`).
   - [ ] Sync color config to server via element registry.
   - **Estimated scope:** ~200 lines Dart + ~50 lines Python.

6. ~~DONE~~ Implement support for ViGEm Bus Driver for better compatibility with games.

   **What was done:**
   - Created abstract `GamepadOutput` base class in `python/server/gamepad_output.py` with `set_axis()`, `set_button()`, `start()`, `stop()`, `active`, `error`, `driver_name`.
   - Implemented `VJoyOutput(GamepadOutput)` — moved logic from `vjoy_handler.py` into new class.
   - Implemented `ViGEmOutput(GamepadOutput)` — supports both Xbox 360 (`VX360Gamepad`) and DualShock 4 (`VDS4Gamepad`) via `vgamepad` library.
   - `NullOutput` fallback when no driver is installed.
   - Three driver modes: `vjoy`, `vigem_xbox`, `vigem_ds4` — selectable at runtime.
   - **Trigger axes (LT/RT):** Center position = released, full deflection either way = fully pressed (`abs(value)` scaled 0–660 → 0.0–1.0).
   - **DS4 DPad:** Tracked as 4 individual buttons, combined into composite direction (N/S/E/W/NE/NW/SE/SW/NONE) via `_apply_ds4_dpad()`.
   - **Per-driver mapping storage:** Profile stores `driver_mappings` dict with saved mappings per driver. Switching drivers saves current mappings for old driver and loads saved mappings for new driver. No reconfiguration needed when switching back.
   - **Auto-detection:** `detect_available_drivers()` checks for `pyvjoy` and `vgamepad` imports.
   - `DRIVER_INFO` dict exposed via REST API — frontend uses it for driver-aware axis/button dropdowns.
   - **Server:** `POST /api/config/driver` switches driver live (stops old gamepad, creates new one, swaps mappings, rebuilds router). `GET /api/config/driver` returns current driver and available options.
   - **Frontend:** Driver selector dropdown in new "Output Driver" config section. Mapping editor shows driver-appropriate axis names (vJoy: X/Y/Z/RX/RY/RZ/SL0/SL1, Xbox: LX/LY/RX/RY/LT/RT, DS4: same). Button selector shows numbered input for vJoy (1–128) or named dropdown for Xbox/DS4 (A/B/X/Y/LB/RB/etc.). Trigger axes marked with "(trigger)" hint.
   - **Status pill:** Shows active driver name (vJoy/Xbox 360/DS4) instead of hardcoded "vJoy".
   - Updated `input_router.py`, `output_manager.py`, `server.py`, `main.py` to use `GamepadOutput` interface instead of `VJoyHandler`.
   - Deleted old `vjoy_handler.py` (fully superseded by `gamepad_output.py`).
   - **Rumble/haptic feedback:** ViGEm rumble events from games are forwarded to the DJI RC's built-in vibration motor.
     - `ViGEmOutput._register_notification()` registers a vgamepad callback that fires when a game sends rumble commands (large + small motor, 0–255).
     - Callback runs on ViGEm's background thread — uses `loop.call_soon_threadsafe()` to schedule transport send on the asyncio event loop.
     - `server.py::_on_rumble()` sends `{"type": "rumble", "large": N, "small": N}` to the RC via the active transport.
     - Flutter `main_screen.dart` handles incoming `rumble` messages and calls `HapticService.rumble()`.
     - `HapticService` (Dart) wraps a platform channel to `HapticPlugin` (Kotlin).
     - `HapticPlugin.kt` uses Android `Vibrator` with `VibrationEffect.createOneShot()` — 5-second duration, refreshed every 4 seconds for sustained vibration without pulsing. Amplitude = `max(large, small)` clamped to 1–255. Stops immediately when motors go to 0.
     - `VIBRATE` permission added to `AndroidManifest.xml`.
   - To enable ViGEm: `pip install vgamepad` (auto-installs ViGEmBus driver).

7. Implement support for more than one vJoy device in parallel to increase amount of axes that can be used.

   **Research findings:**
   - Current `VJoyHandler` manages a single `VJoyDevice` instance.
   - vJoy supports up to 16 devices, each with 8 axes + 128 buttons.
   - Single device = 8 axes max. Two devices = 16 axes.

   **Plan of approach:**
   - [ ] Refactor `VJoyHandler` to hold `dict[int, VJoyDevice]` instead of single `_device`.
   - [ ] Change `start()` to accept `device_ids: list[int]` and acquire multiple devices.
   - [ ] Add `device` field to input_mappings: `{"action": "vjoy_axis", "device": 2, "axis": "X"}`.
   - [ ] Default `device` to 1 for backward compatibility with existing profiles.
   - [ ] Update `_dispatch_axis()` and `_dispatch_button()` in `input_router.py` to pass `device_id`.
   - [ ] Add `vjoy_devices` list to `server.json` (fallback to single `vjoy_device_id` for compat).
   - [ ] Show per-device status in the PC frontend (axes in use, active/inactive).
   - **Estimated scope:** ~150 lines Python refactoring.

8. ~~DONE (PC-side)~~ Implement firmware update for Pico (no physical disconnect).

   **What was done:**
   - PC-side upload via `python/raspberry/upload_to_pico.py`: pushes files to RC via ADB, restarts the Flutter app which auto-detects and uploads firmware via raw REPL (~3 min for 10KB).
   - `PicoPlugin.uploadPendingFirmware()` runs automatically before reader start — checks app's external files dir for `.py`/`.json` files, uploads each via `PicoUsbReader.uploadFile()`, deletes after success.
   - Also exposed as `uploadFromStorage` method channel for programmatic triggering.

   **Remaining (in-app UI — future):**

   **Context:** The Pico is integrated into the RC and may be difficult to physically disconnect for firmware updates. Two approaches can flash new firmware over the existing USB connection without unplugging.

   **Approach A: Software BOOTSEL + UF2 mass storage**
   - Pico firmware listens for a "reboot to bootloader" command over USB CDC serial.
   - On receiving it, calls `reset_usb_boot(0, 0)` (Pico SDK) which reboots into BOOTSEL mode.
   - Pico re-enumerates as a USB mass storage device on the RC's USB port.
   - Android copies the `.uf2` firmware file to the mounted drive.
   - Pico automatically reboots with new firmware after the file is written.
   - **Pros:** Simple Pico-side implementation (one function call). Standard UF2 format.
   - **Cons:** Android USB mass storage write support varies by device/OS version. DJI RC (Android 10) may need custom USB host code to write to the mass storage device. Two USB re-enumerations (CDC → mass storage → CDC) add complexity to the Android side.

   **Approach B: Custom serial flashing protocol**
   - Pico firmware includes an update handler that stays on the same CDC serial connection.
   - Android sends a "start update" command; Pico erases flash sectors and enters receive mode.
   - Android streams the firmware binary in chunks (e.g. 4 KB); Pico writes each chunk to flash.
   - After all chunks, Pico verifies CRC/checksum and reboots into the new firmware.
   - **Pros:** No USB re-enumeration — stays on the same serial connection the app already uses. Full control over progress reporting, error handling, and retry logic from the Flutter app. Works reliably on any Android device.
   - **Cons:** Requires a custom bootloader or update stub in the Pico firmware (~200 lines C). Must handle flash write failures and power-loss safety (e.g. A/B partitions or a recovery stub).

   **Plan of approach:**
   - [ ] Choose approach (B recommended for reliability on DJI RC).
   - [ ] Implement update stub in Pico firmware: receive binary over CDC, write to flash, verify CRC, reboot.
   - [ ] Add firmware file picker in Flutter settings (select `.uf2` or `.bin` from device storage).
   - [ ] Implement streaming upload in `PicoPlugin.kt`: send chunks via bulk OUT, read ACK/progress from bulk IN.
   - [ ] Add progress UI in Flutter (progress bar, status text, error display).
   - [ ] Handle recovery: if update fails mid-write, Pico boots into update stub and waits for retry.
   - **Estimated scope:** ~200 lines C (Pico) + ~150 lines Kotlin + ~100 lines Dart.

---

Known issues (backlog):

- ~~**Pico connected detection flawed** (FIXED):~~ Changed `app.js` from `!!picoBitmask` to `"picoBitmask" in _lastRcState` — field presence check instead of truthy check.
- **Profile switch loses button/gyro state:** `_rebuild_router()` discards `_prev` state and `_gyro_offset`. Buttons held during profile switch get stuck; gyro offset resets causing a jump. Should carry over `_prev` or explicitly release all buttons/zero all axes on rebuild.
- **Profile name path traversal:** Profile names from REST API are used unsanitized in file paths. Names like `../../foo` could write outside the profiles directory. Need to validate profile names (alphanumeric + underscore only).
- **Flutter services not disposed on hot restart:** Services created in `main()` with `ChangeNotifierProvider.value()` are never disposed. Port conflicts on hot restart. Should use `ChangeNotifierProvider(create:)` or add explicit disposal.
- **Config editor "Save All" duplicate listeners:** Fixed with `_hasListener` guard, but ideally should move to `init()`.
- **Shallow copy of DEFAULT_PROFILE/DEFAULT_GYRO_CONFIG:** `{**DEFAULT_GYRO_CONFIG}` only shallow-copies top level; nested pitch/roll/yaw dicts are shared refs. Safe now (written to disk immediately) but latent bug if flow changes.
