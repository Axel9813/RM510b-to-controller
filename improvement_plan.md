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

2. Shutter stage 1 clearly being captured by Android app itself not by Raspberry, I think both should be handled by one way (Raspberry).

   **Root cause analysis:**
   - Shutter full-press is captured from HID byte 16 bit 3 in `RcState.kt` (Android app, via USB HID).
   - Pico captures `shutter_half` (bitmask bit 2) and `shutter_full` (bitmask bit 9) from dedicated GPIO buttons.
   - Two separate input sources exist for shutter, causing potential conflicts and inconsistent behaviour.

   **Plan of approach:**
   - [ ] Remove `shutter` from `RcState.kt` HID parsing (byte 16 bit 3) — it will no longer be sent from the Android side.
   - [ ] Ensure the Pico's `shutter_half` and `shutter_full` GPIO pins are properly wired and mapped in config.json.
   - [ ] Update `config_manager.py` default profile: remove old `"shutter"` HID mapping, keep only `pico_shutter_half` and `pico_shutter_full`.
   - [ ] Update `input_router.py` `HID_BUTTON_FIELDS` to remove `"shutter"`.
   - [ ] Update the web frontend visualizer to show both shutter states from Pico source.
   - [ ] Document which buttons come from HID vs Pico in the README.

3. Outputs of elements placed on customizable interface not being displayed correctly on frontend monitor.

   **Root cause analysis:**
   - `output_manager.py` `toggle()`/`set()` sends state changes to the RC via `_schedule_push_to_rc()`, but does NOT broadcast to the browser monitor WebSocket clients.
   - The frontend's `setScreenElements()` only updates on `registry_update` messages, which only fire during hello handshakes (rare).
   - After toggling a LED on the PC frontend, the change is applied server-side but the browser UI doesn't reflect it until page refresh.

   **Plan of approach:**
   - [ ] After any element state change in `output_manager.py`, broadcast an `element_state_update` message to all connected browser WebSocket clients (via `server.py`'s broadcast mechanism).
   - [ ] In the frontend JS (`app.js` or `rc_visualizer.js`), listen for `element_state_update` and call `setScreenElements()` to re-render affected elements.
   - [ ] Alternatively, send individual `element_update` messages (not full registry) for efficiency.
   - [ ] Verify that the RC → PC direction also triggers UI updates when elements change from the RC side.

4. In Flutter app interface Pico status indicator not changing (leftover from time when it was not fully implemented).

   **Root cause analysis:**
   - In `settings_tab.dart` line 50, the `connected` parameter is **hardcoded to `false`**: `_StatusRow(label: 'Pico', connected: false, ...)`.
   - The status text (`picoService.status`) updates correctly via `notifyListeners()`, but the visual indicator (green/red dot) never changes.

   **Plan of approach:**
   - [ ] Change `connected: false` to `connected: picoService.status == 'connected'` in `settings_tab.dart`.
   - [ ] Verify that `PicoService` is properly registered as a `ChangeNotifier` and that the settings tab rebuilds when status changes.

5. On customizable interface on PC frontend displayed nonexistent "Test" button.

   **Root cause analysis:**
   - No "Test" button found in the frontend source code (`index.html`, `config_editor.js`, `app.js`, `rc_visualizer.js`).
   - Likely a leftover entry in the element registry stored in the server profile or persisted in the Flutter app's SharedPreferences.

   **Plan of approach:**
   - [ ] Check the active profile's `element_registry` in `config/profiles/default.json` for a "Test" entry.
   - [ ] Check the Flutter app's SharedPreferences `interface_layout` key for stale elements.
   - [ ] Add validation in `output_manager.py` `merge_hello()` to skip unknown/orphaned elements.
   - [ ] Add a "delete element" button in the PC frontend config editor to remove stale entries.

6. system_actions pycaw not available ('AudioDevice' object has no attribute 'Activate') — volume_set will not work.

   **Root cause analysis:**
   - `system_actions.py` line 38 calls `_devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)` on the object returned by `AudioUtilities.GetSpeakers()`.
   - The installed pycaw version (>=20240210) may have a different API than what the code expects.
   - Missing COM initialization (`CoInitialize()`) before accessing COM objects at module import time.
   - The error is caught and pycaw is silently disabled, but volume control becomes unavailable.

   **Plan of approach:**
   - [ ] Add explicit `comtypes.CoInitialize()` call before pycaw initialization.
   - [ ] Update the `Activate()` call to use the correct pycaw API for the installed version. Modern pycaw: `_devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)` should work if `_devices` is the raw COM pointer — check if `GetSpeakers()` returns an `AudioDevice` wrapper instead.
   - [ ] If pycaw wraps the COM object, access the underlying pointer: `_devices._audio_device.Activate(...)` or use `AudioUtilities.CreateDevice(...)`.
   - [ ] Pin pycaw version in requirements.txt to a known working version if API keeps changing.
   - [ ] Add a fallback using `ctypes` + Windows `IAudioEndpointVolume` COM interface directly if pycaw fails.
   - [ ] Log the specific pycaw version on startup for easier debugging.

---

Improvements:

1. RC input takes a few tries with app restarting to be captured.

   **Root cause analysis:**
   - `RcStateService.start()` calls native `start()` only once — no retry logic.
   - RC startup only happens in `MainScreen.initState()` via `addPostFrameCallback`, which is asynchronous and delayed.
   - If USB device isn't enumerated yet or permission dialog is pending, the single `start()` call fails silently.
   - Pico has a 5-attempt retry loop with 3s delays, but RC does not have equivalent logic.
   - USB permission is requested asynchronously, but the result isn't awaited before giving up.

   **Plan of approach:**
   - [ ] Add retry logic to `RcStateService.start()` similar to PicoService: 5 attempts with 3s delays.
   - [ ] Move RC initialization to `main.dart` so it starts earlier (alongside PicoService).
   - [ ] In `RcPlugin.kt`, add a USB device attached broadcast receiver to automatically retry when a new USB device is connected.
   - [ ] Add a "Reconnect" button in the Flutter settings tab for manual retry.
   - [ ] Log each retry attempt with a clear reason (device not found / permission pending / claim failed).

2. Implement extendable configuration for adding more physical input devices (buttons/axes).

   **Research findings:**
   - Current input system hardcodes exactly two devices: RC HID (6 axes + 9 buttons) and Pico (10 buttons via bitmask).
   - `input_router.py` has hardcoded `AXIS_FIELDS`, `HID_BUTTON_FIELDS`, `PICO_BUTTON_FIELDS` frozensets.
   - Profile configs map field names to actions in a flat dict.

   **Plan of approach:**
   - [ ] Create a `DeviceRegistry` in server config (`server.json`) listing all input devices with their type, identifiers, and field definitions.
   - [ ] Refactor `InputRouter` to dynamically build axis/button field sets from the device registry instead of hardcoded frozensets.
   - [ ] Create an abstract `InputDevice` base class with `discover()`, `get_fields()`, `decode_state()` methods.
   - [ ] Implement concrete classes: `HidDevice`, `BitmaskDevice` (Pico), `SerialDevice`, `GenericGamepad`.
   - [ ] Add a `DeviceManager` that discovers connected devices and manages their lifecycle.
   - [ ] Update the config editor frontend to show device-aware field selection.
   - **Estimated scope:** ~300 lines Python.

3. Capture gyro/accelerometer data and use it as additional input axes.

   **Research findings:**
   - DJI RC uses Rockchip RK3399 which typically has integrated IMU sensors.
   - No sensor packages currently in pubspec.yaml.
   - Android sensor API is well-supported via `sensors_plus` Flutter package.
   - Sensor data would add 6 new axes: accelX/Y/Z + gyroX/Y/Z.

   **Plan of approach:**
   - [ ] First, verify sensor availability on actual DJI RC hardware by reading `/sys/class/input/` or using a test app.
   - [ ] Add `sensors_plus: ^4.0.0` to pubspec.yaml.
   - [ ] Create `MotionService` (ChangeNotifier) that subscribes to accelerometer and gyroscope streams.
   - [ ] Extend `RcState` (both Kotlin and Dart) with `accelX/Y/Z`, `gyroX/Y/Z` fields.
   - [ ] Merge motion data into the WebSocket rc_state payload at the existing 50Hz rate.
   - [ ] Add `accelX`, `gyroX` etc. to `AXIS_FIELDS` in `input_router.py` with configurable scaling.
   - [ ] Add optional low-pass filter (configurable alpha) to reduce jitter.
   - [ ] Add gyro/accel visualisation to the web frontend.
   - **Risk:** Android may restrict sensor access without root on DJI RC. Test first.
   - **Estimated scope:** ~200 lines Kotlin/Dart + ~100 lines Python.

4. Implement additional transports for PC-controller connection (Bluetooth/USB).

   **Research findings:**
   - Currently only WebSocket over WiFi. No transport abstraction layer exists.
   - A complete Bluetooth design already exists in `BLUETOOTH_PLAN.md` (398 lines).
   - WebSocket code is tightly coupled in both `websocket_service.dart` and `rc_client.py`.

   **Plan of approach:**
   - [ ] Define abstract `Transport` interface on both sides (Python and Flutter) with `connect()`, `disconnect()`, `send()`, `onMessage` methods.
   - [ ] Refactor existing WebSocket code into `WebSocketTransport` implementing the abstract interface.
   - [ ] Implement `BluetoothTransport` per existing `BLUETOOTH_PLAN.md` design:
     - Python: `AF_BTH` sockets (Windows native) or `pyserial` COM port fallback.
     - Flutter: `flutter_bluetooth_serial` package, newline-delimited JSON.
   - [ ] Implement `UsbTransport` for direct USB CDC connection (simpler than Bluetooth):
     - Python: `pyusb` to open RC as CDC device.
     - Flutter: reuse existing USB host infrastructure.
   - [ ] Add transport selection UI in Flutter settings and PC frontend.
   - [ ] Transport auto-discovery with priority order: USB > Bluetooth > WiFi.
   - **Estimated scope:** ~500 lines Python + ~400 lines Flutter.

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

   5.3. Implement interface for streaming data into PC app to be displayed on RC.

   **Currently:** One-way RC→PC for input, PC→RC only for LED state updates.

   **Plan of approach:**
   - [ ] Define new WebSocket message type `data_stream` (server→RC) carrying `{element_id, value}`.
   - [ ] Add batch variant `data_stream_batch` for efficiency.
   - [ ] In Flutter, handle `data_stream` messages and update output elements' display values.
   - [ ] In Python, add `stream_to_rc(element_id, value)` method to `output_manager.py`.
   - [ ] Create a simple plugin API for Python scripts to push data to RC display elements.
   - **Estimated scope:** ~100 lines Dart + ~150 lines Python.

   5.4. Add ability to paint elements in some colors.

   **Plan of approach:**
   - [ ] Add `backgroundColor`, `foregroundColor`, `textColor`, `borderColor` fields to `InterfaceElement`.
   - [ ] Add a color picker to the element editor dialog in the Flutter builder UI.
   - [ ] Update each element widget to use custom colors with fallback to theme defaults.
   - [ ] Persist colors in JSON (hex string format: `"#RRGGBB"`).
   - [ ] Sync color config to server via element registry.
   - **Estimated scope:** ~200 lines Dart + ~50 lines Python.

6. Implement support for ViGEm Bus Driver for better compatibility with games.

   **Research findings:**
   - ViGEm emulates native Xbox 360 / DualShock 4 controllers — ~95% game compatibility vs vJoy's ~70%.
   - Python library: `vigem-client` (COM wrapper).
   - Current `vjoy_handler.py` has no abstraction layer — all vJoy-specific.
   - ViGEm requires ViGEmBus driver installation (may need test-signing on some Windows 10 builds).

   **Plan of approach:**
   - [ ] Create abstract `GamepadOutput` base class with `set_axis()`, `set_button()`, `start()`, `stop()`.
   - [ ] Refactor existing `VJoyHandler` into `VJoyOutput(GamepadOutput)`.
   - [ ] Create `ViGEmOutput(GamepadOutput)` supporting Xbox 360 and DualShock 4 profiles.
   - [ ] Map RC axis names to ViGEm axis names (LX, LY, RX, RY, LT, RT).
   - [ ] Add `output_driver` setting to `server.json` ("vjoy" | "vigem").
   - [ ] Add `output_profile` setting ("xbox360" | "dualshock4") for ViGEm.
   - [ ] Auto-detect installed drivers: try importing `pyvjoy` and `vigem_client`.
   - [ ] Add driver selector to the PC frontend settings UI.
   - [ ] Add `vigem-client>=2.0.0` to requirements.txt as optional dependency.
   - **Estimated scope:** ~200 lines Python.

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
