# Python Server — Development Plan (Phase 2)

## Overview

A Python server running on a PC that:

1. Accepts a persistent WebSocket connection from the RC Flutter app
2. Receives all RC input state at 50 Hz and routes it to vJoy / system actions / custom outputs
3. Serves a web configuration frontend (FastAPI + vanilla HTML/JS, opened in any browser)
4. Sends `element_update` messages back to the RC to drive on-screen LED elements

---

## Technology Stack

| Concern          | Choice                   | Reason                                       |
| ---------------- | ------------------------ | -------------------------------------------- |
| HTTP + WS server | FastAPI + uvicorn        | Async, serves both REST and WS               |
| WebSocket        | FastAPI WebSocket        | Built-in, same event loop as HTTP            |
| UDP discovery    | asyncio DatagramProtocol | Same event loop, no extra deps               |
| vJoy             | pyvjoy                   | Proven in POC (see dji_rc_knowledge/main.py) |
| System actions   | pynput                   | Cross-platform keyboard / media keys         |
| Config storage   | JSON files (config/)     | Human-readable, easy to hand-edit            |
| Frontend         | Vanilla HTML + JS        | Served as static files from FastAPI          |

Install:

```
pip install fastapi uvicorn websockets pyvjoy pynput
```

---

## RC Physical Layout Reference

Derived from photo + user description. Used for the input visualiser in the frontend.

```
┌─────────────────────────────────────────────────────────────────────┐
│  ROW 1 — Triggers                                                   │
│  [L.Trigger]                               [R.Trigger half/full]    │
├─────────────────────────────────────────────────────────────────────┤
│  ROW 2 — Wheels (shown as arcs with live position dot)              │
│  ╰──◄ Left Wheel ►──╯              ╰──◄ Right Wheel ►──╯           │
├─────────────────────────────────────────────────────────────────────┤
│  ROW 3 — Side buttons (flank the sticks)                            │
│  [◄ Arrow]  [C1]                   [C2]  [● Circle]                 │
├─────────────────────────────────────────────────────────────────────┤
│  ROW 4 — Sticks + centre buttons                                    │
│                                                                     │
│   ╔════════╗    [⏸ Pause]   [A]   [5D▲]    ╔════════╗             │
│   ║  LEFT  ║              [5D◄][5D●][5D►]   ║ RIGHT  ║             │
│   ║  STICK ║                  [5D▼]         ║  STICK ║             │
│   ╚════════╝                                ╚════════╝             │
├─────────────────────────────────────────────────────────────────────┤
│  ROW 5 — 3-position flight mode switch                              │
│               [  F ────●──── N ──────── S  ]                       │
├─────────────────────────────────────────────────────────────────────┤
│  ROW 6 — Screen (large rectangle)                                   │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              Flutter-managed screen area                    │   │
│  │          (custom buttons, sliders, LEDs placed here)        │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘

Back of remote (visible in photo):
  - Two silver thumbwheels top-back corners = Left Wheel / Right Wheel
    (these are the same wheels shown in Row 2, displayed front-view as arcs)
  - Two clickable buttons bottom-back edge = likely C1 / C2
    (intercepted by DJI firmware, provided via Pico in Phase 3)
  - Two trigger-style half-buttons on back = L/R Trigger shoulder buttons (row 1)

Input availability summary:
  Available via USB HID (Phase 1):  stickLeftH, stickLeftV, stickRightH,
    stickRightV, leftWheel, rightWheel, record, shutter (full), fiveDUp,
    fiveDDown, fiveDLeft, fiveDRight, fiveDCenter
  Available via Pico (Phase 3):     C1, C2, shutterHalf, pause, rth,
    switchF/N/S, circle, arrow
  Available via Flutter elements:   button press/release, slider value
```

**Input field → UI label mapping:**

| JSON field     | Display name   | Input type    | Visual region   |
| -------------- | -------------- | ------------- | --------------- |
| stickLeftH     | Left Stick H   | axis ±660     | Row 4 L-stick   |
| stickLeftV     | Left Stick V   | axis ±660     | Row 4 L-stick   |
| stickRightH    | Right Stick H  | axis ±660     | Row 4 R-stick   |
| stickRightV    | Right Stick V  | axis ±660     | Row 4 R-stick   |
| leftWheel      | Left Wheel     | axis ±660     | Row 2 left      |
| rightWheel     | Right Wheel    | axis ±660     | Row 2 right     |
| record         | Record         | button        | Row 1 L-trigger |
| shutter        | Shutter (full) | button        | Row 1 R-trigger |
| fiveDUp        | 5D Up          | button        | Row 4 centre    |
| fiveDDown      | 5D Down        | button        | Row 4 centre    |
| fiveDLeft      | 5D Left        | button        | Row 4 centre    |
| fiveDRight     | 5D Right       | button        | Row 4 centre    |
| fiveDCenter    | 5D Center      | button        | Row 4 centre    |
| picoBitmask b0 | C1             | button (Pico) | Row 3           |
| picoBitmask b1 | C2             | button (Pico) | Row 3           |
| picoBitmask b2 | Shutter (half) | button (Pico) | Row 1 R-trigger |
| picoBitmask b3 | Pause          | button (Pico) | Row 4 centre    |
| picoBitmask b4 | RTH [A]        | button (Pico) | Row 4 centre    |
| picoBitmask b5 | Switch F       | switch (Pico) | Row 5           |
| picoBitmask b6 | Switch S       | switch (Pico) | Row 5           |
| picoBitmask b7 | Circle         | button (Pico) | Row 3           |
| picoBitmask b8 | Arrow          | button (Pico) | Row 3           |

Elements from Flutter app arrive as `element_event` messages:
| field + context | Display name | Input type |
|-----------------|---------------------|-------------------|
| id + press | \<user-defined name> | button press/rel |
| id + change | \<user-defined name> | slider 0.0–1.0 |

---

## WebSocket Protocol (RC ↔ Server)

### Received from RC

**`rc_state`** (50 Hz):

```json
{
  "type": "rc_state",
  "seq": 1234,
  "stickLeftH": 0,
  "stickLeftV": 0,
  "stickRightH": 0,
  "stickRightV": 0,
  "leftWheel": 0,
  "rightWheel": 0,
  "record": false,
  "shutter": false,
  "fiveDUp": false,
  "fiveDDown": false,
  "fiveDLeft": false,
  "fiveDRight": false,
  "fiveDCenter": false,
  "picoBitmask": 0
}
```

**`element_event`** (on user interaction with a Flutter-side element):

```json
{ "type": "element_event", "id": "btn_xxx", "event": "press" }
{ "type": "element_event", "id": "btn_xxx", "event": "release" }
{ "type": "element_event", "id": "sld_xxx", "event": "change", "value": 0.73 }
```

### Sent to RC

**`element_update`** (sent whenever an output value changes):

```json
{ "type": "element_update", "id": "my_led_01", "value": true }
```

**`elements_full_state`** (sent immediately on new connection):

```json
{
  "type": "elements_full_state",
  "states": { "my_led_01": true, "my_led_02": false }
}
```

---

## UDP Discovery Protocol

Matches what the Flutter app already implements (port 8766):

```python
# Server sends this on receiving DJI_RC_DISCOVER|{"type":"discover"}:
DJI_RC_DISCOVER|{"type":"dji_rc_server","name":"<hostname>","port":8765,"ips":["192.168.x.x"]}
```

---

## Configuration Files (`config/`)

Configuration is split into two layers:

### `config/server.json` — server-level settings (not part of any profile)

```json
{
  "ws_port": 8765,
  "http_port": 8080,
  "discovery_port": 8766,
  "vjoy_device_id": 1,
  "active_profile": "default"
}
```

### Profile files — `config/profiles/<name>.json`

All per-use-case configuration lives in a single JSON profile file.
Profiles are named (e.g. `default`, `gaming`, `presentation`) and can be
switched from the frontend without restarting the server.
The active profile name is stored in `server.json`.

**Full profile schema:**

```json
{
  "profile_name": "default",
  "input_mappings": {
    "stickLeftH": { "action": "vjoy_axis", "axis": "X" },
    "stickLeftV": { "action": "vjoy_axis", "axis": "Y", "invert": true },
    "stickRightH": { "action": "vjoy_axis", "axis": "RX" },
    "stickRightV": { "action": "vjoy_axis", "axis": "RY", "invert": true },
    "leftWheel": { "action": "vjoy_axis", "axis": "Z" },
    "rightWheel": { "action": "vjoy_axis", "axis": "RZ" },
    "record": { "action": "vjoy_button", "button": 1 },
    "shutter": { "action": "vjoy_button", "button": 2 },
    "fiveDUp": { "action": "vjoy_button", "button": 3 },
    "fiveDDown": { "action": "vjoy_button", "button": 4 },
    "fiveDLeft": { "action": "vjoy_button", "button": 5 },
    "fiveDRight": { "action": "vjoy_button", "button": 6 },
    "fiveDCenter": { "action": "vjoy_button", "button": 7 },
    "pico_c1": { "action": "vjoy_button", "button": 8 },
    "pico_c2": { "action": "vjoy_button", "button": 9 },
    "pico_pause": { "action": "system", "fn": "media_play_pause" },
    "pico_rth": { "action": "key", "keys": ["ctrl", "shift", "h"] },
    "pico_circle": { "action": "none" },
    "pico_arrow": { "action": "none" }
  },
  "element_registry": {
    "btn_1234": {
      "display_name": "Boost",
      "element_type": "button",
      "on_press": { "action": "key", "keys": ["shift"] },
      "on_release": { "action": "none" }
    },
    "sld_5678": {
      "display_name": "Volume",
      "element_type": "slider",
      "on_change": { "action": "system", "fn": "volume_set" }
    },
    "led_9012": {
      "display_name": "Status LED",
      "element_type": "led",
      "current_value": false,
      "trigger": "manual"
    }
  }
}
```

Notes on `element_registry`:

- Entries are **created automatically** when the RC app connects and sends a
  `hello` message listing all elements configured in the Flutter layout.
- New elements are added with `action: none` / `trigger: manual`; existing
  entries are preserved (actions the user previously configured are not reset).
- Elements removed from the Flutter layout are **not** automatically deleted
  from the profile — the user can remove them manually via the frontend.
- LED `current_value` is persisted so the last-known state survives server restarts.
- `trigger` values: `"manual"` (frontend toggle) or `"rule"` (future).

Supported `action` values for `input_mappings` and `element_registry`:
| action | extra fields | description |
|----------------|---------------------------------|--------------------------------------|
| `none` | — | input ignored |
| `vjoy_axis` | `axis`, `invert?` | map to a vJoy axis |
| `vjoy_button` | `button` (1-128) | map to a vJoy button |
| `key` | `keys` (list of key names) | send keyboard combo via pynput |
| `system` | `fn` | system function (see list below) |

Supported `fn` values for `system` action:

```
media_play_pause, media_next, media_prev,
volume_up, volume_down, volume_mute
```

---

## vJoy Axis Mapping

Input axis range from RC: ±660 (signed int).
vJoy axis range: 0–32767, center = 16383.

```python
def rc_to_vjoy(value: int, invert: bool = False) -> int:
    # value is in range approx ±660
    clamped = max(-660, min(660, value))
    scaled = int((clamped + 660) / 1320 * 32767)
    return 32767 - scaled if invert else scaled
```

vJoy axis name → pyvjoy constant:

```
X  → HID_USAGE_X     RX → HID_USAGE_RX
Y  → HID_USAGE_Y     RY → HID_USAGE_RY
Z  → HID_USAGE_Z     RZ → HID_USAGE_RZ
S0 → HID_USAGE_SL0   S1 → HID_USAGE_SL1
```

---

## File Structure

```
python/server/
├── DEVELOPMENT_PLAN.md      ← this file
├── main.py                  ← entry point: starts uvicorn + UDP discovery
├── server.py                ← FastAPI app, WebSocket handler, REST routes
├── vjoy_handler.py          ← pyvjoy wrapper (start/stop/set axis+button)
├── input_router.py          ← maps incoming rc_state fields → actions
├── system_actions.py        ← pynput-based system functions
├── output_manager.py        ← manages LED/output states, sends to RC
├── config_manager.py        ← load/save config + profiles, hot-reload
├── discovery.py             ← asyncio UDP broadcast responder
│
├── config/
│   ├── server.json          ← server-level settings + active_profile name
│   └── profiles/
│       └── default.json     ← auto-created on first run
│
└── frontend/
    ├── index.html           ← single-page app shell
    ├── style.css
    ├── app.js               ← main JS: tabs, WS connection to server
    ├── rc_visualizer.js     ← SVG-based RC input display
    └── config_editor.js     ← mapping editor, output toggle panel
```

---

## Frontend Structure

Single HTML page served at `http://localhost:8080/`.
Two sections/tabs:

### Tab A — Live Monitor

Shows a stylised top-down SVG diagram of the RC with live input animation.

**SVG RC layout (proportional to the photo):**

```
┌────────────────────────────────────────────────────┐
│  [LTrig]                            [RTrig ½/●]   │
│  ╰─L.Wheel─╯                        ╰─R.Wheel─╯   │
│  [◄]  [C1]                       [C2]  [●]        │
│  ╔══L.Stick══╗  [⏸][A] 5D↑       ╔══R.Stick══╗   │
│              ╚═╗  5D← ● →5D     ╔╝                │
│                    5D↓                             │
│            [F ────●──── N ──────── S]              │
│  ┌──────────────────────────────────────────────┐  │
│  │             Screen (informational box)       │  │
│  └──────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────┘
```

Each element in the SVG responds to live WebSocket state from the server's
internal broadcast:

- Sticks: a dot moves inside a circle proportional to axis values
- Wheels: an arc needle rotates
- Buttons: highlighted when pressed (CSS class toggle)
- 3-position switch: indicator moves to F / N / S position
- Right trigger: two-zone indicator (outer half-ring for half-press, inner for full)
- Screen box: shows custom element names from `element_registry.json`

The frontend opens its own WebSocket to the server's `/ws/monitor` endpoint
which pushes `rc_state` messages at the current live rate.

### Tab B — Configuration

Three collapsible sections:

**1. Input → Action Mapping**

- Table: one row per input. Columns: Input name / Current action / [Edit button]
- Edit opens a modal with a dropdown for action type + fields for that type
- "Save" button writes to `/api/config/input_mappings`
- Note: Pico inputs shown in a separate sub-section, greyed out until Pico connects

**2. Output (RC Screen Elements) + Element Registry**

- Combined section: lists all elements registered in the active profile's
  `element_registry`.
- Elements are populated automatically when the RC app connects and sends a
  `hello` message — the server merges new element IDs into the active profile.
- For LED elements: shows current state + a manual toggle button.
- For button/slider elements: shows assigned action.
- User can assign / edit actions for on_press / on_release / on_change / toggle.
- Toggle calls `POST /api/outputs/{id}/toggle`.
- Future: "Add rule" button per LED entry opens a rule editor.

**3. Profile Management**

- Shows the currently active profile name
- Dropdown to switch between existing profiles (hot-reloads router + output manager)
- [New Profile] button — clones current profile under a new name
- [Rename] / [Delete] buttons per profile
- [Export] / [Import] buttons to download/upload a profile JSON file

---

## REST API (FastAPI routes)

```
GET  /                              → serves index.html
GET  /static/{path}                 → serves JS/CSS
GET  /ws/monitor                    → WebSocket: pushes rc_state to browser

GET  /api/status                    → { connected: bool, last_seq: int, vjoy_active: bool }

# Profile management
GET  /api/profiles                  → list all profile names + active profile
POST /api/profiles                  → create new profile (body: {name, clone_from?})
DELETE /api/profiles/{name}         → delete a profile (cannot delete active)
POST /api/profiles/{name}/activate  → switch active profile, hot-reload everything
GET  /api/profiles/{name}           → download full profile JSON
PUT  /api/profiles/{name}           → upload / replace full profile JSON

# Per-input and per-element config (operates on active profile)
GET  /api/config/mappings           → returns input_mappings section of active profile
POST /api/config/mappings           → saves updated mappings, hot-reloads router
GET  /api/config/elements           → returns element_registry of active profile
POST /api/config/elements/{id}      → update a single element's config in active profile

# Output toggles — LED elements only
POST /api/outputs/{id}/toggle       → toggle LED value, push element_update to RC, save profile
POST /api/outputs/{id}/set          → set LED to specific value, push element_update to RC, save profile
```

Hot-reload: changing input mappings via the API re-instantiates `InputRouter`
in-place without restarting the server.

---

## Module Responsibilities

### `main.py`

- Reads `config/server.json`
- Starts asyncio UDP discovery responder
- Starts uvicorn (FastAPI) with configured ports
- Initialises vJoy device; logs warning if vJoy not installed

### `server.py` (FastAPI app)

Two WebSocket endpoints on the same server:

`/ws/rc` — RC device connection:

- Authenticates magic hello message (optional, simple token)
- Passes `rc_state` to `InputRouter.process(state)` on each frame
- Passes `element_event` to `OutputManager.handle_element_event(event)`
- At connect: sends `elements_full_state` from `OutputManager`
- Maintains a reference used by `OutputManager.push_to_rc(msg)`

`/ws/monitor` — browser monitor connection:

- Receives last `rc_state` from a shared variable, pushes at ~20 Hz to browser
  (rate-limited so browser doesn't get overwhelmed)

### `input_router.py`

```python
class InputRouter:
    def __init__(self, mappings: dict, vjoy: VJoyHandler, sys: SystemActions):
        ...
    def process(self, state: dict) -> None:
        # For each mapped field, compute delta from previous state
        # and dispatch to vjoy_handler or system_actions
        # Axis: always set; Button: set on change only
```

Keeps previous state copy to detect button edge transitions (press/release).

### `vjoy_handler.py`

```python
class VJoyHandler:
    def start(self, device_id: int) -> bool  # returns False if pyvjoy unavailable
    def stop(self)
    def set_axis(self, axis_name: str, rc_value: int, invert: bool)
    def set_button(self, button_id: int, pressed: bool)
```

Graceful fallback: if `import pyvjoy` fails (not installed or vJoy driver not
present), `VJoyHandler` runs in no-op mode and logs warnings. The rest of the
server continues to function.

### `system_actions.py`

Uses `pynput.keyboard.Controller` and platform-specific media key codes.

```python
class SystemActions:
    def execute(self, fn: str, value: float = 0.0) -> None
    # fn: media_play_pause, media_next, media_prev,
    #     volume_up, volume_down, volume_mute, volume_set
```

### `output_manager.py`

```python
class OutputManager:
    def load(self, profile: dict) -> None  # reads element_registry from active profile
    def save(self) -> None                 # persists LED current_values back to active profile
    def toggle(self, id: str) -> bool
    def set_value(self, id: str, value) -> None
    def get_full_state(self) -> dict       # for elements_full_state message
    def merge_hello(self, elements: list) -> None  # add new elements from hello message
    async def push_to_rc(self, msg: dict) -> None  # sends to connected RC WS
    def handle_element_event(self, event: dict) -> None  # routes to element_registry actions
```

### `config_manager.py`

Singleton that manages `server.json` and the `profiles/` directory.

```python
class ConfigManager:
    def load_server(self) -> dict          # reads server.json
    def save_server(self) -> None
    def list_profiles(self) -> list[str]   # filenames in profiles/
    def load_profile(self, name: str) -> dict
    def save_profile(self, name: str, data: dict) -> None
    def delete_profile(self, name: str) -> None
    def active_profile_name(self) -> str
    def set_active_profile(self, name: str) -> None  # saves server.json
    def ensure_defaults(self) -> None      # creates default profile if missing
```

Fires a `on_profile_changed` callback so `InputRouter` and `OutputManager`
hot-reload from the new profile without restarting the server.

### `discovery.py`

```python
class DiscoveryProtocol(asyncio.DatagramProtocol):
    def datagram_received(self, data, addr):
        if data.startswith(b"DJI_RC_DISCOVER|"):
            # parse, respond with server name + IPs + port
```

Gets local IPs by connecting a UDP socket to 8.8.8.8 (no packet sent, reads
socket's own bound address — reliable cross-platform way to find LAN IP).

---

## RC Handshake Addition

When the Flutter app connects it should send a **`hello`** message listing all
configured element IDs and their display names. This allows the server to
auto-populate the `element_registry` section of the active profile without
manual configuration.

This is a small addition to the Flutter `WebSocketService`:

```dart
// Sent immediately after WebSocket connection is established:
channel.sink.add(jsonEncode({
  'type': 'hello',
  'elements': layout.elements.map((e) => {
    'id': e.id,
    'displayName': e.displayName,
    'elementType': e.elementType,  // 'button' | 'slider' | 'led'
  }).toList(),
}));
```

Server `hello` handling sequence:

1. `OutputManager.merge_hello(elements)` — adds any unknown IDs to the active
   profile's `element_registry` with defaults (`action: none`, `trigger: manual`);
   existing entries are left unchanged.
2. Profile is saved to disk.
3. Server sends `elements_full_state` back so all LED states are synced.
4. Browser monitor WebSocket clients are notified of the updated registry
   so the frontend element list refreshes automatically.

---

## Implementation Phases

### Phase 2.0 — Core Server + vJoy + Discovery

- [ ] `config_manager.py` — load/save `server.json` + profiles, create `default` profile if missing, profile switch hot-reload
- [ ] `discovery.py` — UDP responder matching Flutter protocol
- [ ] `vjoy_handler.py` — pyvjoy wrapper with graceful no-op fallback
- [ ] `system_actions.py` — media + volume functions via pynput
- [ ] `input_router.py` — dispatch rc_state fields to actions based on config
- [ ] `output_manager.py` — LED state store + push to RC
- [ ] `server.py` — FastAPI app: `/ws/rc`, `/ws/monitor`, all REST routes
- [ ] `main.py` — entry point, startup sequence

### Phase 2.1 — Frontend Monitor

- [ ] `frontend/index.html` — tab shell, WS connection to `/ws/monitor`
- [ ] `frontend/rc_visualizer.js` — SVG RC diagram, live input animation
  - Sticks: dot in circle
  - Wheels: arc needle
  - Buttons: highlight on press
  - 3-pos switch: sliding indicator
  - Right trigger: two-stage highlight
- [ ] `frontend/style.css` — dark theme, RC outline styling

### Phase 2.2 — Frontend Configuration

- [ ] `frontend/config_editor.js`
  - Input mapping table + edit modal
  - Combined element registry + output toggle panel
  - Profile management section (list, switch, new, export, import)

### Phase 2.3 — Flutter `hello` Handshake

- [ ] Add `hello` message sending in `WebSocketService` (Flutter side)
- [ ] Server-side handling: populate `element_registry.json` from received elements

---

## Phase 3 Notes (Pico, deferred)

When Pico arrives, `input_router.py` already handles `pico_*` keys.
The only change needed is populating `picoBitmask` correctly from the Flutter
`PicoService`. No server changes required — the bitmask fields are already
decoded in the router using the bit positions defined in the Flutter plan.

---

## Open Questions / Notes

- **vJoy driver requirement**: vJoy must be installed on the PC separately.
  `vjoy_handler.py` checks at startup and logs a clear error if missing.
  The server runs without it (all `vjoy_axis`/`vjoy_button` actions become no-ops).
- **Windows Firewall**: `main.py` will print firewall setup instructions at
  first run. Optionally add auto-firewall-rule creation via `subprocess` running
  `netsh advfirewall` with admin check.
- **`volume_set` action for slider**: volume level from Flutter slider (0.0–1.0)
  maps to absolute system volume. Implementation differs per OS:
  Windows → `pycaw` or `nircmd`; macOS → `osascript`; Linux → `pactl`.
  Phase 2 implements Windows only; others as stubs.
- **Monitor WS rate-limiting**: The browser monitor receives at 20 Hz max to
  avoid overwhelming the browser. A simple `asyncio.sleep(0.05)` loop keeps
  the last received state and pushes it to all connected browser clients.
- **Multiple browser clients**: `output_manager.push_to_rc` uses a single RC
  connection reference. Multiple browser tabs for monitoring are supported via
  a simple set of active monitor WebSocket connections.
