# RC-to-Controller Flutter App — Development Plan

## Project Overview

Flutter app running on a DJI RM510B remote controller (Android 10, ARM64).
Collects input from:
1. **RC's own USB HID joystick** — sticks, wheels, 5D joystick, record/shutter buttons
2. **Raspberry Pi Pico** (via USB, stub for now) — C1, C2, pause, home, shutter half-press,
   3-position switch, "circle" button, "arrow" button

Sends all state via WebSocket to a PC server, and receives back signals to drive
the configurable on-screen interface elements.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│  DJI RC (Android 10)                                             │
│                                                                  │
│  ┌─────────────────────┐    MethodChannel / EventChannel         │
│  │  Kotlin Native      │◄────────────────────────────────────┐  │
│  │  - RcUsbReader      │                                      │  │
│  │    (USB HID 18-byte)│                                      │  │
│  └─────────────────────┘                                      │  │
│                                                                │  │
│  ┌──────────────────────────────────────────────────────────┐ │  │
│  │  Flutter (Dart)                                          │ │  │
│  │                                                          │ │  │
│  │  Services:                                               │ │  │
│  │  ├── RcStateService   (consumes EventChannel)            │ │  │
│  │  ├── PicoService      (STUB — USB serial / HID TBD)      │ │  │
│  │  ├── DiscoveryService (UDP broadcast, port 8766)         │ │  │
│  │  ├── WebSocketService (WS client, auto-reconnect)        │ │  │
│  │  └── LayoutStorageService (SharedPreferences / JSON)     │ │  │
│  │                                                          │ │  │
│  │  UI:                                                     │ │  │
│  │  ├── Tab 1 – Settings / Status                           │ │  │
│  │  └── Tab 2 – Interface (clean) + builder overlay         │─┘  │
│  └──────────────────────────────────────────────────────────┘    │
│                     │ Wi-Fi WebSocket                             │
└─────────────────────┼────────────────────────────────────────────┘
                      │
              ┌───────▼────────┐
              │  PC – Python   │
              │  WebSocket srv │
              └────────────────┘
```

---

## Flutter Dependencies (`pubspec.yaml`)

```yaml
dependencies:
  flutter:
    sdk: flutter
  web_socket_channel: ^3.0.1      # WebSocket client
  shared_preferences: ^2.3.0      # Persistent layout storage
  provider: ^6.1.2                # State management
```

`dart:io` (built-in) is used for UDP discovery (`RawDatagramSocket`).

---

## Android Native Module (Kotlin)

### Files to create

```
android/app/src/main/kotlin/com/dji/rc_to_controller/
├── MainActivity.kt           ← register channels
├── RcPlugin.kt               ← MethodCallHandler + StreamHandler
├── RcUsbReader.kt            ← HID packet reader thread
└── RcState.kt                ← data class + toMap()

android/app/src/main/res/xml/
└── usb_device_filter.xml     ← vendor-id 11427 (0x2CA3)
```

### HID Packet format (18 bytes, Approach A)

```
Byte  0:     Report ID   (always 0x02)
Byte  1:     Constant    (always 0x0E)
Bytes 2–3:   Sequence counter (uint16 LE)
Bytes 4–5:   Right stick H  (uint16 LE, center=1024, range ~364–1684)
Bytes 6–7:   Right stick V  (uint16 LE, center=1024)
Bytes 8–9:   Left stick V   (uint16 LE, center=1024)
Bytes 10–11: Left stick H   (uint16 LE, center=1024)
Bytes 12–13: Left wheel     (uint16 LE, center=1024)
Bytes 14–15: Right wheel    (uint16 LE, center=1024)
Bytes 16–17: Button flags
  Byte 16 bit 2 (0x04) = Record
  Byte 16 bit 3 (0x08) = Shutter full press
  Byte 17 bit 0 (0x01) = 5D Up
  Byte 17 bit 1 (0x02) = 5D Down
  Byte 17 bit 2 (0x04) = 5D Left
  Byte 17 bit 3 (0x08) = 5D Right
  Byte 17 bit 4 (0x10) = 5D Center

Signed axis value = raw_uint16 - 1024  →  range ≈ ±660
```

### Platform Channels

```
MethodChannel  'com.dji.rc/control'
  invokeMethod('start')  → opens USB, starts read thread
  invokeMethod('stop')   → stops thread, releases USB
  invokeMethod('status') → returns Map with connection info

EventChannel   'com.dji.rc/state'
  Emits Map<String, dynamic> matching RcState fields
  Rate: every incoming packet (~100 Hz cap, throttled to 50 Hz in Dart)
```

### AndroidManifest.xml additions

```xml
<uses-feature android:name="android.hardware.usb.host" android:required="false" />
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
<uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />

<!-- Inside <activity>: -->
<intent-filter>
  <action android:name="android.hardware.usb.action.USB_DEVICE_ATTACHED" />
</intent-filter>
<meta-data
  android:name="android.hardware.usb.action.USB_DEVICE_ATTACHED"
  android:resource="@xml/usb_device_filter" />
```

### `build.gradle.kts` settings

```kotlin
minSdk = 26
ndk { abiFilters += listOf("arm64-v8a") }
compileOptions {
  sourceCompatibility = JavaVersion.VERSION_17
  targetCompatibility = JavaVersion.VERSION_17
}
```

---

## Raspberry Pi Pico Integration (STUB)

The Pico is not yet available (awaiting delivery). The app will include a
`PicoService` stub that:
- Exposes the same interface that the real implementation will use
- Returns a zeroed `PicoState` bitmask at all times
- Logs a "Pico not connected" status visible in Settings tab

### Button Bitmask (16-bit, planned)

Bit positions (to be finalized when Pico arrives):

```
Bit 0  – C1
Bit 1  – C2
Bit 2  – Shutter half-press
Bit 3  – Pause / Stop
Bit 4  – Return-to-Home
Bit 5  – 3-position switch state A (pin 1 shorted)
Bit 6  – 3-position switch state B (pin 2 shorted)
Bit 7  – "Circle" button
Bit 8  – "Arrow" button
Bits 9–15 reserved
```

Switch decoding: bits 5 and 6 encode position 1 / 2 / 3:
- `00` → position 2 (neither shorted)
- `01` → position 1 (pin 1 shorted)
- `10` → position 3 (pin 2 shorted)

### Pico pin config

Will be a human-readable text/JSON file uploaded alongside the MicroPython
firmware. Intent:

```json
{
  "C1":              { "pin": 2,  "active_low": true },
  "C2":              { "pin": 3,  "active_low": true },
  "shutter_half":    { "pin": 4,  "active_low": true },
  "pause":           { "pin": 5,  "active_low": true },
  "return_to_home":  { "pin": 6,  "active_low": true },
  "switch_pos1":     { "pin": 7,  "active_low": true },
  "switch_pos3":     { "pin": 8,  "active_low": true },
  "circle":          { "pin": 9,  "active_low": true },
  "arrow":           { "pin": 10, "active_low": true }
}
```

Connection method: Pico USB → RC USB-C hub (or OTG adapter).
Exact HID vs CDC-ACM behaviour will be determined on arrival.

---

## WebSocket Protocol

### RC → Server (`rc_state`)

```json
{
  "type": "rc_state",
  "seq": 1234,
  "stickLeftH":   0,
  "stickLeftV":   0,
  "stickRightH":  0,
  "stickRightV":  0,
  "leftWheel":    0,
  "rightWheel":   0,
  "record":       false,
  "shutter":      false,
  "fiveDUp":      false,
  "fiveDDown":    false,
  "fiveDLeft":    false,
  "fiveDRight":   false,
  "fiveDCenter":  false,
  "picoBitmask":  0
}
```

`picoBitmask` is 0 while the Pico stub is active. The server must treat
it as an opaque 16-bit integer so no server changes are needed when the
real Pico ships.

### Server → RC (`element_update`)

Used to drive LED/light elements on the interface screen:

```json
{
  "type": "element_update",
  "id": "my_led_01",
  "value": true
}
```

`id` matches the element's `id` field stored in the layout.

### Server → RC (`elements_full_state`) — sent on new connection

```json
{
  "type": "elements_full_state",
  "states": {
    "my_led_01": true,
    "my_led_02": false
  }
}
```

---

## Auto-Discovery Protocol

Port 8766 UDP. Magic prefix: `DJI_RC_DISCOVER|`

**RC → broadcast 255.255.255.255:8766:**
```
DJI_RC_DISCOVER|{"type":"discover"}
```

**Server → unicast back to RC:**
```
DJI_RC_DISCOVER|{"type":"dji_rc_server","name":"MyPC","port":8765,"ips":["192.168.1.10"]}
```

The app shows discovered servers as tappable cards. User taps one → WS connects.

---

## Reconnection Strategy

After initial connect or a lost connection, the `WebSocketService` runs
the following policy:

```
Phase 1 — First 60 seconds:
  Retry every 2 seconds (≈30 attempts)

Phase 2 — 60 s to 600 s (next 9 minutes):
  Each consecutive failure adds 5 s to delay:
  2 → 7 → 12 → 17 → 22 → 27 → 32 → 37 → 42 → 47 → 52 → 57 → 60 (cap)

Phase 3 — After 600 s total elapsed:
  Give up. Show error banner on Settings tab:
  "Could not reach server. [Retry]"
  The [Retry] button resets the timer and restarts Phase 1.
```

Reconnect clock resets on any successful connection.

---

## Application UI Structure

### Tab 1 — Settings / Status

```
┌─────────────────────────────────────────────┐
│  RC Input         ● Connected / ✕ No device  │
│  Pico             ◌ Stub (awaiting device)   │
│  Server           ● 192.168.1.10:8765        │
│                   [Disconnect]               │
│─────────────────────────────────────────────│
│  Discovered servers (UDP scan)               │
│  ┌───────────────────────────────────────┐  │
│  │  MyPC  192.168.1.10  port 8765  [▶]   │  │
│  └───────────────────────────────────────┘  │
│  [Scan again]                                │
│─────────────────────────────────────────────│
│  [Open Interface Builder]                    │
└─────────────────────────────────────────────┘
```

### Tab 2 — Interface

```
┌─────────────────────────────────────────────┐
│                                             │
│   [configured elements only]               │
│                                             │
│                                             │
│                  ⚙ (small FAB, top-right)   │
└─────────────────────────────────────────────┘
```

Tapping ⚙ navigates back to Tab 1.

---

## Interface Builder Overlay

Opens as a bottom-sheet-style panel that slides up over the Interface tab.
When open, the screen is divided into a visible grid of equal squares.

### Grid System

- Grid cell size: calculated as `min(screenWidth, screenHeight) / 8`
  (approximately 48–64 dp on the RC's screen — exact value TBD after
  first run on device; exposed as a constant `kGridCell`).
- Grid origin: top-left corner of the usable screen area.
- Elements snap to grid cells.

### Element Default Sizes (in grid cells)

| Element | Width | Height |
|---------|-------|--------|
| Button  | 3     | 2      |
| Slider  | 6     | 2      |
| LED     | 2     | 2      |

All sizes will be configurable in the options menu in future iterations.

### Builder Interaction Flow

1. **Builder closed (Interface tab shown normally):**
   - Existing elements rendered in their grid positions.
   - ⚙ FAB visible.

2. **Builder open:**
   - Grid lines rendered over the screen.
   - Existing elements shown with a highlighted selection border on tap.
   - A builder bottom panel is visible with two actions:
     - **[+ Add Element]** — shows element picker (Button / Slider / LED).
       After picking, panel collapses and user taps a grid cell to place it.
     - **[✕ Close Builder]** — closes the overlay.

3. **Element selected (tap an existing element):**
   - Options menu appears:
     - **Rename** — inline text field for display name.
     - **Move** — element follows next grid-cell tap.
     - *(future: change color, resize)*
     - **Delete** — removes element.

4. **Placing a new element:**
   - Highlighted "ghost" follows pointer.
   - Tap on a free grid position to confirm placement.
   - Element is given a default name ("Button 1", "Slider 1", "LED 1") and a
     generated unique `id` (e.g. `btn_<timestamp>`).
   - Name can be edited immediately after placement.

### Rendered Element Descriptions

**Button** — Displays `displayName`. Sends to server on press/release:
```json
{ "type": "element_event", "id": "btn_xxx", "event": "press" }
{ "type": "element_event", "id": "btn_xxx", "event": "release" }
```

**Slider** — Displays `displayName` + current value. Sends on change:
```json
{ "type": "element_event", "id": "sld_xxx", "event": "change", "value": 0.73 }
```

**LED (Light)** — Displays `displayName` + a circular indicator.
Color: OFF = grey, ON = white/green (default).
State is set by `element_update` messages from the server.

---

## Data Models (Dart)

### `RcState`
```dart
class RcState {
  final int stickLeftH, stickLeftV, stickRightH, stickRightV;
  final int leftWheel, rightWheel;
  final bool record, shutter;
  final bool fiveDUp, fiveDDown, fiveDLeft, fiveDRight, fiveDCenter;
  final int picoBitmask;   // always 0 from stub
}
```

### `InterfaceElement` (sealed)
```dart
sealed class InterfaceElement {
  final String id;
  final String displayName;
  final int gridX, gridY;
  final int gridW, gridH;
}

class ButtonElement  extends InterfaceElement { ... }
class SliderElement  extends InterfaceElement { ... }
class LedElement     extends InterfaceElement { bool currentState = false; }
```

### `AppLayout`
```dart
class AppLayout {
  final List<InterfaceElement> elements;
  // serialise / deserialise to JSON for SharedPreferences
}
```

---

## File Structure (Flutter `lib/`)

```
lib/
├── main.dart                        ← app entry, theme, MaterialApp
├── app.dart                         ← top-level Navigator/tabs
│
├── models/
│   ├── rc_state.dart
│   ├── pico_state.dart
│   ├── interface_element.dart       ← sealed class + 3 subtypes
│   └── app_layout.dart
│
├── services/
│   ├── rc_state_service.dart        ← EventChannel consumer
│   ├── pico_service.dart            ← STUB
│   ├── discovery_service.dart       ← UDP broadcast
│   ├── websocket_service.dart       ← WS client + reconnect
│   └── layout_storage_service.dart  ← SharedPreferences
│
├── screens/
│   ├── main_screen.dart             ← TabBar (tab 1 + tab 2)
│   ├── settings_tab.dart
│   └── interface_tab.dart
│
└── widgets/
    ├── builder_overlay.dart         ← foldable builder panel
    ├── element_picker.dart          ← modal: choose type to add
    ├── element_options_menu.dart    ← rename / move / delete
    ├── grid_painter.dart            ← CustomPainter for grid lines
    ├── button_element_widget.dart
    ├── slider_element_widget.dart
    └── led_element_widget.dart
```

---

## Kotlin / Android File Structure

```
android/app/src/main/kotlin/com/dji/rc_to_controller/
├── MainActivity.kt
├── RcPlugin.kt
├── RcUsbReader.kt
└── RcState.kt

android/app/src/main/res/xml/
└── usb_device_filter.xml
```

---

## Implementation Phases

### Phase 1 — Foundation (current sprint)

Goal: data flows end-to-end from RC sticks to PC vJoy.

**1.1 Android/Kotlin — USB HID reader**
- [ ] `RcState.kt` data class
- [ ] `RcUsbReader.kt`: find VID:0x2CA3/PID:0x1501, request permission,
      claimInterface(force=true), read thread, parse 18-byte packet
- [ ] `RcPlugin.kt`: MethodChannel (start/stop/status) + EventChannel (state stream)
- [ ] `MainActivity.kt`: register both channels
- [ ] `AndroidManifest.xml` + `usb_device_filter.xml` updates
- [ ] `build.gradle.kts` updates (minSdk=26, arm64, Java 17)

**1.2 Dart services**
- [ ] `RcStateService`: subscribe EventChannel, expose `Stream<RcState>`
- [ ] `PicoService` (stub): returns zero bitmask, exposes status string
- [ ] `DiscoveryService`: UDP broadcast scan, returns `List<ServerEntry>`
- [ ] `WebSocketService`: connect, send `rc_state` at 50 Hz, receive messages,
      reconnect policy (Phases 1–3 as described above)
- [ ] `LayoutStorageService`: load/save `AppLayout` JSON

**1.3 Basic UI**
- [ ] `main.dart` / `app.dart`: dark theme, TabBar shell
- [ ] `settings_tab.dart`: RC status, Pico stub status, server discovery,
      connect/disconnect, "Open Interface Builder" button
- [ ] `interface_tab.dart`: empty clean canvas + ⚙ FAB

**1.4 Data models**
- [ ] All model classes with `toMap()` / `fromMap()` / `toJson()` / `fromJson()`

---

### Phase 2 — Interface Builder

**2.1 Grid + layout engine**
- [ ] `grid_painter.dart`: draw grid lines when builder is open
- [ ] Snap-to-grid utility functions
- [ ] Collision detection (no element overlap)

**2.2 Element widgets**
- [ ] `button_element_widget.dart`
- [ ] `slider_element_widget.dart`
- [ ] `led_element_widget.dart` — subscribes to server `element_update` messages

**2.3 Builder overlay**
- [ ] `builder_overlay.dart`: slide-up panel
- [ ] `element_picker.dart`: Button / Slider / LED choice
- [ ] `element_options_menu.dart`: rename, move, delete
- [ ] Placement flow (ghost preview → tap to confirm)
- [ ] Persistence: save layout on every change via `LayoutStorageService`

---

### Phase 3 — Raspberry Pi Pico (post-delivery)

- Evaluate HID vs CDC-ACM on the actual hardware
- Replace `PicoService` stub with real implementation:
  - Reads bitmask from USB
  - Merges into `rc_state` payload
- Upload MicroPython firmware + `pico_config.json` to device
- Validate all 9 button/switch inputs end-to-end

---

### Phase 4 — Polish & Extended Features (future)

- RC state visualisation sub-screen (stick positions, button states)
- Colour customisation for elements
- Element resize handles
- Server-side configuration frontend
- Additional element types (multi-state indicators, numeric displays, etc.)

---

## Open Questions / Notes

- **Pico USB on RC**: The RC has a single USB-C port. If a USB hub is used,
  both the Pico and any charging cable share it. Power draw must be checked.
- **Pico HID vs CDC**: MicroPython `usb.device.get()` with a custom HID
  descriptor may be simpler than CDC-ACM for low-latency bitmask streaming,
  but CDC-ACM (`machine.UART` over USB) is easier to debug. Decision deferred.
- **Grid cell size**: `kGridCell = 56.0` is the starting value. Should be
  tuned after first run on the RC's actual screen dimensions.
- **50 Hz send rate**: Confirmed acceptable from the proof-of-concept.
  May lower to 20 Hz if Wi-Fi congestion is observed.
- **Server compatibility**: The `picoBitmask: 0` field is additive — existing
  server code that ignores unknown fields will continue to work unchanged.
