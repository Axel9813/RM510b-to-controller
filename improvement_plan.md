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
