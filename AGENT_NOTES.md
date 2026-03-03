# Agent Working Notes — rc_to_controller

_Last updated: 2026-02-26_

---

## Project Goal

Turn a **DJI RM510B remote controller** (Android 10, ARM64, locked) into a
PC **gaming controller**, while also showing custom UI on its built-in screen.

Three components:

| # | Component | Location | Status |
|---|-----------|----------|--------|
| 1 | **Flutter app** (runs ON the RC) | `flutter/` | Phase 1 ✅  Phase 2 ✅ |
| 2 | **Python server** (runs on PC) | `python/server/` | Phase 2 DONE |
| 3 | **Raspberry Pi Pico** (hardware wired to RC) | `python/raspberry/` (TODO) | Phase 3, Pico not arrived yet |

---

## What Is DONE

### Flutter App — Phase 1 ✅ Phase 2 ✅
**Android/Kotlin:** RcState.kt, RcUsbReader.kt (VID:0x2CA3/PID:0x1501, force=true),
RcPlugin.kt (MethodChannel + EventChannel), MainActivity.kt, usb_device_filter.xml

**Dart Models:** RcState, PicoState, InterfaceElement (sealed→Button/Slider/Led), AppLayout

**Dart Services:** RcStateService (50 Hz throttle), PicoService (stub), DiscoveryService (UDP),
WebSocketService (50 Hz send, 3-phase reconnect, hello handshake), LayoutStorageService

**UI:** Dark theme, Settings tab (RC/Pico/server status, discovery, connect), Interface tab (grid canvas, drag-to-move elements, add/rename/delete, edit-mode toggle, server LED state sync)

### Python Server — Phase 2 ✅
main.py, server.py (FastAPI /ws/rc /ws/monitor + REST), config_manager.py, input_router.py,
output_manager.py, vjoy_handler.py, system_actions.py, discovery.py, full web UI frontend

---

## What Is TODO

### Phase 3 — Raspberry Pi Pico (waiting for hardware)
- `python/raspberry/` MicroPython firmware + pin config JSON
- Replace PicoService stub in Flutter

---

## Key Architecture Facts

### HID Packet (18 bytes)
```
[0]=0x02  [1]=0x0E  [2-3]=seq(LE)
[4-5]=RightStickH  [6-7]=RightStickV
[8-9]=LeftStickV   [10-11]=LeftStickH
[12-13]=LeftWheel  [14-15]=RightWheel
[16]: bit2=Record  bit3=ShutterFull(HID)
[17]: bit0=5DUp  bit1=5DDown  bit2=5DLeft  bit3=5DRight  bit4=5DCenter
Center = 1024, range ≈ 364–1684, signed = raw - 1024 → ±660
```

### picoBitmask (16-bit)
```
bit 0 = pico_c1           bit 1 = pico_c2
bit 2 = pico_shutter_half bit 3 = pico_pause
bit 4 = pico_rth          bit 5 = pico_switch_f
bit 6 = pico_switch_s     bit 7 = pico_circle
bit 8 = pico_arrow        bit 9 = pico_shutter_full
Switch: bits 5,6 both 0 = N position
```

### WebSocket Protocol
**RC → Server** (`rc_state`, 50 Hz):
```json
{"type":"rc_state","seq":N,"stickLeftH":0,"stickLeftV":0,"stickRightH":0,
 "stickRightV":0,"leftWheel":0,"rightWheel":0,"record":false,"shutter":false,
 "fiveDUp":false,"fiveDDown":false,"fiveDLeft":false,"fiveDRight":false,
 "fiveDCenter":false,"picoBitmask":0}
```
**RC → Server** (`hello`, on connect):
```json
{"type":"hello","elements":[{"type":"button","elementType":"button","id":"btn_xxx",
  "displayName":"Boost","gridX":0,"gridY":0,"gridW":3,"gridH":2}]}
```
Note: `toJson()` emits both `'type'` (for local fromJson) AND `'elementType'` (for server merge_hello).

**RC → Server** (`element_event`):
```json
{"type":"element_event","id":"btn_xxx","event":"press"}
{"type":"element_event","id":"sld_xxx","event":"change","value":0.73}
```
Note: field is `"id"` not `"element_id"` — server reads `event.get("id")`.

**Server → RC** (`elements_full_state` / `element_update`):
```json
{"type":"elements_full_state","states":{"led_xxx":true}}
{"type":"element_update","id":"led_xxx","value":true}
```

### Server Config / Profile Format
Input mappings (flat, no nesting):
```json
{"action": "vjoy_axis",   "axis": "X",  "invert": false, "dead_zone": 0.02}
{"action": "vjoy_button", "button": 1}
{"action": "key",         "keys": ["ctrl","shift","h"]}
{"action": "system",      "fn": "media_play_pause"}
{"action": "none"}
```

Element registry entries:
```json
// LED:
{"display_name":"...", "element_type":"led",    "current_value":false, "trigger":"manual", "on_press":{action}}
// Button:
{"display_name":"...", "element_type":"button", "on_press":{action}, "on_release":{action}}
// Slider:
{"display_name":"...", "element_type":"slider", "on_change":{action}}
```

### Platform Channels
```
MethodChannel: 'com.dji.rc/control'   (start/stop/status)
EventChannel:  'com.dji.rc/state'     (stream of rc_state Maps at 50 Hz)
```

### Discovery — Three Parallel Methods

**1. mDNS / DNS-SD** (zero-config, best-effort)
- Server: `zeroconf` library advertises `_dji-rc._tcp.local.` on the WS port
- Flutter: `multicast_dns` package scans `_dji-rc._tcp`, resolves SRV→A records
- Requires WiFi Multicast Lock (acquired via `WifiMulticastLockPlugin`)
- Rescans every 15 s

**2. TCP Beacon** (port 8767, survives GPO firewalls that block UDP)
- Server: asyncio TCP server; on accept writes identity frame + `\n` and closes
- Flutter: scans local /24 subnet (64 concurrent, 300 ms timeout) + known hosts
- Rescans every 20 s
- Frame: `DJI_RC_DISCOVER|{"type":"dji_rc_server","name":"PC","port":8080,"ips":[...]}\n`

**3. UDP Broadcast** (port 8766, fast on open LANs)
- Flutter → 255.255.255.255:8766  probe every 3 s
- Server → unicast reply with same identity frame (no prefix+\n)

**Firewall rules (run as Admin once):**
```powershell
netsh advfirewall firewall add rule name="DJI RC WS"       dir=in action=allow protocol=TCP localport=8080
netsh advfirewall firewall add rule name="DJI RC Beacon"   dir=in action=allow protocol=TCP localport=8767
netsh advfirewall firewall add rule name="DJI RC Discovery" dir=in action=allow protocol=UDP localport=8766
```

### Reconnection Policy
Phase 1 (0–60s): retry every 2s
Phase 2 (60–600s): delay += 5s/failure, cap 60s
Phase 3 (>600s): give up, show Retry banner

### Grid System (Interface Builder — Phase 2)
kGridCell = min(screenW, screenH) / 8 (≈56dp)
Button: 3×2  Slider: 6×2  LED: 2×2
IDs: "btn_<timestamp>", "sld_<timestamp>", "led_<timestamp>"

---

## Fixed Issues (2026-02-26)

### `rc_visualizer.js`
- Field names corrected: `stickLeftH/V`, `stickRightH/V`, `leftWheel`, `rightWheel`,
  `record`, `shutter`, `fiveDUp/Down/Left/Right/Center`, `picoBitmask`
- Pico bitmask bits: `0x001=c1, 0x002=c2, 0x080=circle, 0x100=arrow` (were wrong)
- `shutterFull` ReferenceError fixed — all consts declared before use
- `rtrig_half_bar` now updated every frame (was built but never set)
- Switch decoded from `picoBitmask` bits 5/6 (was reading nonexistent `s.switch_pos`)
- HID `shutter` shown on right trigger (was ignored)

### `config_editor.js`
- INPUT_LABELS keys match protocol field names exactly
- `record` reclassified as button (was wrongly axis); `shutter` added as new HID button entry
- Action format unified: `{action, axis, button, fn, keys}` throughout
- Element registry uses `display_name`/`current_value` (server format)
- Element editor patches correct server fields per element type
- `loadRegistry()` passes `display_name`/`current_value` to screen chips

### Flutter `interface_element.dart`
- `toJson()` now emits both `'type'` and `'elementType'` so server `merge_hello`
  correctly identifies button/slider/led types

### `default.json` + `config_manager.py`
- Added `"shutter": {"action":"vjoy_button","button":3}` (HID full-press was silently dropped)

---

## Build Commands

### Flutter APK
```bash
cd /c/projects/rc_to_controller/flutter
flutter build apk --release --target-platform android-arm64
adb install -r build/app/outputs/flutter-apk/app-release.apk
```

### Python Server
```bash
cd /c/projects/rc_to_controller/python/server
pip install -r requirements.txt
python main.py
# Web UI: http://localhost:8080/
```

### Windows Firewall (run as Admin once)
```powershell
netsh advfirewall firewall add rule name="DJI RC WS"       dir=in action=allow protocol=TCP localport=8080
netsh advfirewall firewall add rule name="DJI RC Beacon"   dir=in action=allow protocol=TCP localport=8767
netsh advfirewall firewall add rule name="DJI RC Discovery" dir=in action=allow protocol=UDP localport=8766
```
