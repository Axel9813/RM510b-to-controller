# DJI RC Controller — Python Server (Phase 2)

PC-side server that receives RC inputs from the Flutter app over WebSocket,
translates them to vJoy / keyboard / system actions, and serves a browser-based
live monitor and configuration UI.

---

## Quick Start

```powershell
# 1. (one-time) install dependencies
cd C:\projects\rc_to_controller\python\server
pip install -r requirements.txt

# 2. run the server
python main.py
```

Web UI opens at **http://localhost:8080/**  
RC WebSocket listens on **ws://0.0.0.0:8080/ws/rc**

### Windows Firewall (run once as Administrator if the RC tablet can't reach the server)

```powershell
netsh advfirewall firewall delete rule name="DJI RC WS"
netsh advfirewall firewall add rule name="DJI RC WS" `
      dir=in action=allow protocol=TCP localport=8080
netsh advfirewall firewall add rule name="DJI RC Discovery" `
      dir=in action=allow protocol=UDP localport=8766
```

### Optional flags

```powershell
# custom config file location
python main.py --config C:\path\to\server.json
```

---

## File Map

```
python/server/
├── main.py              — entry point (argparse, asyncio.run)
├── server.py            — FastAPI app, all WebSocket + REST endpoints
├── config_manager.py    — singleton; loads/saves server.json + profiles/
├── input_router.py      — rc_state fields → vJoy / keyboard actions
├── output_manager.py    — LED state, element registry, push to RC
├── vjoy_handler.py      — pyvjoy wrapper (graceful no-op if driver absent)
├── system_actions.py    — pynput media keys, key combos, volume
├── discovery.py         — UDP broadcast responder (auto-discovery)
├── requirements.txt
├── config/
│   ├── server.json      — server-level settings + active_profile name
│   └── profiles/
│       └── default.json — input_mappings + element_registry
└── frontend/
    ├── index.html
    ├── style.css
    ├── app.js           — WS /ws/monitor client, tab/modal/toast
    ├── rc_visualizer.js — SVG RC diagram, updates at 20 Hz
    └── config_editor.js — mapping editor, element registry, profile CRUD
```

---

## WebSocket Protocols

### `/ws/rc` — Flutter app → Server

All messages are JSON text frames.

#### RC → Server

**`rc_state`** (50 Hz, every 20 ms)

```json
{
  "type": "rc_state",
  "seq": 12345,
  "stickLeftH": -330,
  "stickLeftV": 0,
  "stickRightH": 660,
  "stickRightV": 0,
  "leftWheel": 0,
  "rightWheel": 128,
  "record": false,
  "fiveDUp": false,
  "fiveDDown": false,
  "fiveDLeft": false,
  "fiveDRight": false,
  "fiveDCenter": false,
  "picoBitmask": 0
}
```

Stick / wheel range: **−660 … +660** (raw HID values).  
`picoBitmask` is a 16-bit integer; bit positions are defined below.

**`element_event`** — fired when user interacts with a screen element

```json
{
  "type": "element_event",
  "event": "press",
  "element_id": "btn_gimbal_up",
  "value": null
}
```

`event` values: `press`, `release`, `change` (slider).  
`value` is `null` for buttons, `0.0–1.0` for sliders.

**`hello`** — sent once immediately after WebSocket connection is established

```json
{
  "type": "hello",
  "elements": [
    {
      "type": "button",
      "id": "btn_gimbal_up",
      "displayName": "Gimbal Up",
      "gridX": 0,
      "gridY": 0,
      "gridW": 3,
      "gridH": 2
    },
    {
      "type": "led",
      "id": "led_record",
      "displayName": "Recording",
      "gridX": 3,
      "gridY": 0,
      "gridW": 2,
      "gridH": 2
    }
  ]
}
```

#### Server → RC

**`elements_full_state`** — sent on connect and after `hello`

```json
{
  "type": "elements_full_state",
  "states": {
    "led_record": true,
    "btn_gimbal_up": false
  }
}
```

**`element_update`** — sent when a single element's LED state changes

```json
{
  "type": "element_update",
  "id": "led_record",
  "state": true
}
```

---

### `/ws/monitor` — Browser → Server (read-only)

#### Server → Browser

**`initial_state`** — sent once on connect

```json
{
  "type": "initial_state",
  "rc_connected": false,
  "vjoy_active": true,
  "rc_state": {},
  "registry": {},
  "active_profile": "default",
  "profiles": ["default"]
}
```

**`monitor_update`** — broadcast at **20 Hz**

```json
{
  "type": "monitor_update",
  "rc_connected": true,
  "vjoy_active": true,
  "rc_state": { "stickLeftH": -330, "picoBitmask": 3, "...": "..." }
}
```

**`registry_update`** — pushed when Flutter `hello` adds new elements

```json
{
  "type": "registry_update",
  "registry": {
    "btn_gimbal_up": {
      "name": "Gimbal Up",
      "element_type": "button",
      "action": {}
    }
  }
}
```

**`profile_changed`** — pushed after a profile switch

```json
{
  "type": "profile_changed",
  "profile": "fpv-mode"
}
```

---

## picoBitmask Bit Positions

| Bit | Field name          | Physical control          |
| --- | ------------------- | ------------------------- |
| 0   | `pico_c1`           | C1 button (top-left row)  |
| 1   | `pico_c2`           | C2 button (top-right row) |
| 2   | `pico_shutter_half` | Shutter half-press (AF)   |
| 3   | `pico_pause`        | Pause button (Row 4)      |
| 4   | `pico_rth`          | A / RTH button (Row 4)    |
| 5   | `pico_switch_f`     | F-N-S switch → F position |
| 6   | `pico_switch_s`     | F-N-S switch → S position |
| 7   | `pico_circle`       | Circle button (Row 2)     |
| 8   | `pico_arrow`        | Arrow (↕) button (Row 2)  |
| 9   | `pico_shutter_full` | Shutter full-press        |

N position = both bits 5 and 6 are 0.

Pico handles **both shutter stages** — bit 2 fires on half-press (autofocus),
bit 9 fires on full-press.

---

## REST API

| Method       | Path                            | Description                                                    |
| ------------ | ------------------------------- | -------------------------------------------------------------- |
| GET          | `/`                             | Serve `frontend/index.html`                                    |
| GET          | `/static/<file>`                | Serve frontend static assets                                   |
| GET          | `/api/status`                   | RC connection, vJoy status, active profile, mappings, elements |
| GET          | `/api/profiles`                 | List profiles + active name                                    |
| POST         | `/api/profiles`                 | Create profile `{name, clone_from?, data?}`                    |
| GET          | `/api/profiles/{name}`          | Export profile JSON                                            |
| PUT          | `/api/profiles/{name}`          | Overwrite profile JSON                                         |
| DELETE       | `/api/profiles/{name}`          | Delete profile (not "default")                                 |
| POST         | `/api/profiles/{name}/activate` | Switch active profile                                          |
| GET          | `/api/config/mappings`          | Get input_mappings for active profile                          |
| POST / PATCH | `/api/config/mappings`          | Replace / merge input_mappings                                 |
| GET          | `/api/config/elements`          | Get element_registry for active profile                        |
| PATCH        | `/api/config/elements`          | Bulk-update element entries                                    |
| POST         | `/api/config/elements/{id}`     | Update single element entry                                    |
| POST         | `/api/outputs/{id}/toggle`      | Toggle LED state → `{id, state, value}`                        |
| POST         | `/api/outputs/{id}/set`         | Set LED state `{value: true/false}`                            |

---

## Config Files

### `config/server.json`

```json
{
  "ws_port": 8765,
  "http_port": 8080,
  "discovery_port": 8766,
  "vjoy_device_id": 1,
  "active_profile": "default"
}
```

### `config/profiles/<name>.json`

```json
{
  "profile_name": "default",
  "input_mappings": {
    "stickLeftH": { "action": "vjoy_axis", "axis": "X" },
    "stickLeftV": { "action": "vjoy_axis", "axis": "Y", "invert": true },
    "record": { "action": "vjoy_button", "button": 1 },
    "pico_shutter_half": { "action": "vjoy_button", "button": 2 },
    "pico_shutter_full": { "action": "vjoy_button", "button": 3 },
    "pico_c1": { "action": "key", "keys": ["ctrl", "shift", "h"] },
    "fiveDUp": { "action": "none" }
  },
  "element_registry": {
    "btn_gimbal_up": {
      "name": "Gimbal Up",
      "element_type": "button",
      "action": { "type": "vjoy_button", "button_id": 10 },
      "state": false
    }
  }
}
```

#### Action object shapes

```jsonc
// vJoy axis (for stick / wheel inputs only)
{ "action": "vjoy_axis", "axis": "X", "invert": false, "dead_zone": 0.02 }

// vJoy button
{ "action": "vjoy_button", "button": 1 }

// Key combination (pynput key names)
{ "action": "key", "keys": ["ctrl", "shift", "h"] }

// System action
{ "action": "system", "fn": "media_play_pause" }
// fn options: media_play_pause | media_next | media_prev
//             volume_up | volume_down | mute | volume_set

// No action
{ "action": "none" }
```

---

## UDP Auto-Discovery

The Flutter app broadcasts to port **8766** on connect:

```
DJI_RC_DISCOVER|{"type":"discover"}
```

The server replies (unicast back to sender) with:

```json
{
  "type": "server",
  "ips": ["192.168.1.10"],
  "ws_port": 8765,
  "name": "DJI-RC-Server"
}
```

The Flutter app then connects to `ws://<ip>:8765/ws/rc`.

---

## vJoy Setup

1. Download and install **vJoy 2.1.9** from [sourceforge.net/projects/vjoystick](https://sourceforge.net/projects/vjoystick/)
2. Run **vJoy Configure** — device 1, enable at minimum: axes X Y Z Rx Ry Rz Sl0 Sl1, buttons 1–32
3. vJoy is optional — the server starts and runs in no-op mode if the driver is not installed

Axis scaling: raw stick value **±660** → vJoy **0–32767** (centre = 16383).

---

## Flutter Integration Notes

`WebSocketService.setHelloElements(elements)` must be called with the current
`AppLayout` elements list after loading from `LayoutStorageService`. This is done
in `MainScreen.initState()`. The hello fires automatically on every
(re-)connection so the server always has an up-to-date registry.

If the layout changes at runtime, call `setHelloElements` again — it will send
a new hello immediately if already connected.

```dart
// Typical call site (main_screen.dart)
LayoutStorageService().load().then((layout) {
  if (layout.elements.isNotEmpty) {
    wsService.setHelloElements(
      layout.elements.map((e) => e.toJson()).toList(),
    );
  }
});
```
