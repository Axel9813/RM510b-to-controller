# Bluetooth RFCOMM Implementation Plan

## Overview

Add Bluetooth Classic (RFCOMM/SPP) as a third transport alongside WebSocket (WiFi) and ADB (USB).
This gives zero-setup connectivity on any PC with a Bluetooth adapter — no ADB, no firewall rules.

## Why Bluetooth Classic (not BLE)

| Aspect | Classic RFCOMM | BLE GATT |
|--------|---------------|----------|
| Throughput | 100+ KB/s | 20-100 KB/s |
| Latency | 10-50ms | 50-200ms |
| Message model | Stream (socket-like) | Request/Response |
| 50Hz viable? | Yes, easily | Marginal |
| Pairing | Required (one-time) | Optional |
| Setup complexity | Lower | Higher (GATT profiles) |

Our workload: 200-byte JSON at 50Hz = ~10 KB/s. Classic RFCOMM handles this easily.

## Architecture

```
Flutter (RC)                         Python (PC)
BluetoothService ──RFCOMM/SPP──► BluetoothTransport
  (client)                           (server)
     │                                  │
     ├─ sendState() ──json+newline──►   ├─ feeds InputRouter
     └─ incoming   ◄──json+newline──    └─ sends from OutputManager
```

- **Python = RFCOMM server** (listens for connections, matches existing WS pattern)
- **Flutter = RFCOMM client** (connects to paired PC)
- **Protocol**: newline-delimited JSON (`\n` terminated), same message types as WebSocket

## Message Framing

RFCOMM is a byte stream (like TCP). We need framing. Use newline-delimited JSON:

```
{"type":"rc_state","sticks":{"lx":0,"ly":0}}\n
{"type":"ping"}\n
{"type":"pong"}\n
{"type":"element_event","element":"led1","color":"red"}\n
```

Both sides accumulate bytes in a buffer, split on `\n`, parse each line as JSON.

## One-Time Setup

1. Enable Bluetooth on both RC and PC
2. Pair devices via system Bluetooth settings (RC Settings > Bluetooth > find PC)
3. Confirm PIN on both devices
4. After pairing, reconnection is automatic — no re-pairing needed

---

## Flutter Side

### 1. Dependencies

**pubspec.yaml** — add:
```yaml
flutter_bluetooth_serial: ^0.4.0
```

If maintenance issues arise, switch to `flutter_bluetooth_serial_plus` (same API).

### 2. Android Permissions

**android/app/src/main/AndroidManifest.xml** — add:
```xml
<uses-permission android:name="android.permission.BLUETOOTH" />
<uses-permission android:name="android.permission.BLUETOOTH_ADMIN" />
<uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
<uses-permission android:name="android.permission.BLUETOOTH_SCAN" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
```

Note: Android 10 (API 29) requires ACCESS_FINE_LOCATION for Bluetooth device discovery.

### 3. BluetoothService (`flutter/lib/services/bluetooth_service.dart`)

New file. Mirrors `WebSocketService` API:

```dart
class BluetoothService extends ChangeNotifier {
  // --- State (same as WebSocketService) ---
  ConnectionStatus _status = ConnectionStatus.disconnected;
  String? _error;
  String? _connectedDeviceName;
  String? _connectedDeviceAddress;

  // --- Incoming messages ---
  final _incomingController = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get incoming => _incomingController.stream;

  // --- Connection ---
  BluetoothConnection? _connection;
  final StringBuffer _buffer = StringBuffer(); // for newline-delimited framing

  // --- 50Hz send loop (same as WS) ---
  Map<String, dynamic>? _pendingState;
  Timer? _sendTimer;

  // --- Reconnection (same backoff as WS: 2s → 15s) ---
  int _consecutiveFailures = 0;
  Timer? _reconnectTimer;
  DateTime? _disconnectedAt;

  // --- Ping/pong (10s interval, 25s timeout) ---
  Timer? _pingTimer;
  DateTime? _lastPong;

  // --- Public API ---
  Future<void> connect(String address, {String? name});
  void disconnect();
  void sendState(Map<String, dynamic> state);  // throttled at 50Hz
  Future<List<BluetoothDevice>> getPairedDevices();
  Future<List<BluetoothDevice>> startScan();
  void stopScan();

  // --- Getters ---
  ConnectionStatus get status;
  String? get error;
  String? get connectedDeviceName;
  String? get connectedDeviceAddress;
}
```

**Key implementation details:**

- `connect()`: Uses `BluetoothConnection.toAddress(address)`, starts send timer + ping timer
- `_onDataReceived(Uint8List data)`: Appends to `_buffer`, splits on `\n`, parses each line as JSON
- `_sendRaw(Map<String, dynamic> data)`: `jsonEncode(data) + '\n'` → `connection.output.add()`
- `_onDisconnected()`: Same pattern as WS — cleanup, increment failures, `notifyListeners()`, schedule reconnect
- `_scheduleReconnect()`: Exponential backoff 2s→15s, same guard against re-entrant `notifyListeners()` as WS
- `getPairedDevices()`: Returns `FlutterBluetoothSerial.instance.getBondedDevices()`
- `startScan()`: Returns discovered devices via `FlutterBluetoothSerial.instance.startDiscovery()`

### 4. Discovery Integration (`flutter/lib/services/discovery_service.dart`)

Add a `_BluetoothScanner` alongside existing mechanisms:

```dart
class _BluetoothScanner {
  // Periodically check paired devices for known service name
  // Add found devices as ServerEntry(discoveryMethod: 'bluetooth')
  // Priority: ADB > Bluetooth > WiFi (UDP/mDNS)
}
```

Or keep Bluetooth discovery separate (in BluetoothService.getPairedDevices()) and let the UI handle it.

**Recommendation**: Keep Bluetooth device selection separate from WiFi server discovery.
The settings_tab shows a "Bluetooth" section with paired devices list and connect button.

### 5. Settings UI (`flutter/lib/screens/settings_tab.dart`)

Add a Bluetooth section below the existing server list:

```
┌─────────────────────────────────┐
│ Servers (WiFi / USB)            │
│  ● USB (ADB) @ 127.0.0.1:8080  │
│  ○ 192.168.0.227:8080 (WiFi)   │
├─────────────────────────────────┤
│ Bluetooth                       │
│  [Toggle: Enable Bluetooth]     │
│  Paired devices:                │
│    ● DESKTOP-ABC123   [Connect] │
│    ○ Other-Device              │
│  [Scan for devices]            │
├─────────────────────────────────┤
│ Status: Connected via Bluetooth │
│ Device: DESKTOP-ABC123          │
└─────────────────────────────────┘
```

### 6. Provider Registration (`flutter/lib/main.dart`)

Add `BluetoothService` to `MultiProvider`:

```dart
ChangeNotifierProvider(create: (_) => BluetoothService()),
```

---

## Python Side

### 7. RFCOMM Server — Primary Approach: Windows AF_BTH Sockets

**`python/server/bluetooth_rfcomm.py`** — new file:

```python
import socket
import asyncio
import json
import logging

AF_BTH = 32          # Windows Bluetooth address family
BTHPROTO_RFCOMM = 3  # RFCOMM protocol

class BluetoothTransport:
    """RFCOMM server using Windows native Bluetooth sockets."""

    def __init__(self, on_rc_state, on_element_event, send_queue):
        self.on_rc_state = on_rc_state      # callback: InputRouter.process
        self.on_element_event = on_element_event  # callback: OutputManager.handle
        self.send_queue = send_queue         # asyncio.Queue for outgoing msgs
        self._server_sock = None
        self._client_sock = None
        self._running = False

    async def start(self, channel: int = 1):
        """Start RFCOMM server on given channel."""
        loop = asyncio.get_running_loop()
        self._server_sock = socket.socket(AF_BTH, socket.SOCK_STREAM, BTHPROTO_RFCOMM)
        self._server_sock.bind(("", channel))
        self._server_sock.listen(1)
        self._server_sock.setblocking(False)
        self._running = True
        log.info(f"Bluetooth RFCOMM server listening on channel {channel}")
        asyncio.create_task(self._accept_loop(loop))

    async def _accept_loop(self, loop):
        while self._running:
            try:
                client, addr = await loop.sock_accept(self._server_sock)
                log.info(f"Bluetooth connection from {addr}")
                # Replace existing connection (zombie handling, same as WS)
                if self._client_sock:
                    self._client_sock.close()
                self._client_sock = client
                client.setblocking(False)
                asyncio.create_task(self._read_loop(client, loop))
                asyncio.create_task(self._write_loop(client, loop))
            except Exception as e:
                if self._running:
                    log.error(f"Bluetooth accept error: {e}")
                    await asyncio.sleep(1)

    async def _read_loop(self, sock, loop):
        buffer = ""
        try:
            while True:
                data = await loop.sock_recv(sock, 4096)
                if not data:
                    break
                buffer += data.decode('utf-8')
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if not line.strip():
                        continue
                    msg = json.loads(line)
                    self._dispatch(msg)
        except Exception as e:
            log.warning(f"Bluetooth read error: {e}")
        finally:
            sock.close()
            if self._client_sock is sock:
                self._client_sock = None

    async def _write_loop(self, sock, loop):
        try:
            while self._client_sock is sock:
                msg = await self.send_queue.get()
                line = json.dumps(msg) + '\n'
                await loop.sock_sendall(sock, line.encode('utf-8'))
        except Exception:
            pass

    def _dispatch(self, msg):
        msg_type = msg.get("type")
        if msg_type == "rc_state":
            self.on_rc_state(msg)
        elif msg_type == "element_event":
            self.on_element_event(msg)
        elif msg_type == "ping":
            # Queue pong response
            self.send_queue.put_nowait({"type": "pong"})
        elif msg_type == "hello":
            pass  # handle hello/registration

    async def stop(self):
        self._running = False
        if self._client_sock:
            self._client_sock.close()
        if self._server_sock:
            self._server_sock.close()
```

### 8. Fallback: COM Port + pyserial

If `AF_BTH` doesn't work on the target Windows version, fallback plan:

1. User sets up incoming Bluetooth COM port in Windows Bluetooth settings
2. Or: use `serial.tools.list_ports` to auto-detect Bluetooth COM ports
3. Python opens COM port with pyserial, same newline-delimited JSON protocol

```python
import serial
import serial.tools.list_ports

def find_bluetooth_port():
    """Find Bluetooth COM port."""
    for port in serial.tools.list_ports.comports():
        if 'Bluetooth' in (port.description or ''):
            return port.device
    return None

# Open and use like a regular serial port
ser = serial.Serial(port_name, baudrate=115200, timeout=1)
ser.write(json.dumps(msg).encode() + b'\n')
line = ser.readline().decode()
```

**Add to requirements.txt** (needed for fallback):
```
pyserial>=3.5
```

### 9. Integration with server.py

Modify `server.py` to support multiple transports:

```python
# In server.py, the message handlers are already functions.
# BluetoothTransport just calls the same handlers:
#   on_rc_state  → InputRouter.process()
#   on_element_event → OutputManager.handle()
#   outgoing messages → send_queue → BluetoothTransport._write_loop
```

The key change: `_rc_ws` global becomes transport-agnostic. When sending to RC:
- If connected via WebSocket → send via WS
- If connected via Bluetooth → send via BT send_queue
- Priority: use whichever is currently connected

### 10. Integration with main.py

```python
# In main.py startup:
bt_transport = BluetoothTransport(
    on_rc_state=input_router.process,
    on_element_event=output_manager.handle,
    send_queue=asyncio.Queue()
)
try:
    await bt_transport.start(channel=1)
    log.info("Bluetooth RFCOMM server started")
except OSError as e:
    log.warning(f"Bluetooth not available: {e}")
    # Non-fatal — WiFi/ADB still work
```

---

## File Change Summary

### New Files
| File | Description |
|------|-------------|
| `flutter/lib/services/bluetooth_service.dart` | RFCOMM client, mirrors WebSocketService API |
| `python/server/bluetooth_rfcomm.py` | RFCOMM server using AF_BTH sockets |

### Modified Files
| File | Change |
|------|--------|
| `flutter/pubspec.yaml` | Add `flutter_bluetooth_serial` dependency |
| `flutter/android/app/src/main/AndroidManifest.xml` | Add Bluetooth permissions |
| `flutter/lib/main.dart` | Register BluetoothService in MultiProvider |
| `flutter/lib/screens/settings_tab.dart` | Add Bluetooth section (paired devices, connect) |
| `python/server/server.py` | Transport-agnostic RC messaging |
| `python/server/main.py` | Start BluetoothTransport on startup |
| `python/requirements.txt` | Add `pyserial` (fallback) |

---

## Implementation Order

1. **Python RFCOMM server** — test AF_BTH socket on Windows first
2. **Flutter BluetoothService** — core connect/disconnect/send/receive
3. **Android permissions** — manifest + runtime permission requests
4. **Settings UI** — paired device list + connect button
5. **Message routing** — wire into existing InputRouter/OutputManager
6. **Auto-reconnect** — exponential backoff, ping/pong
7. **Testing** — pair devices, verify bidirectional JSON flow

## Known Challenges

1. **AF_BTH on Windows**: May not work in all Python builds. Test first, fall back to pyserial.
2. **flutter_bluetooth_serial maintenance**: If issues arise, switch to `flutter_bluetooth_serial_plus`.
3. **Android 12+ permissions**: BLUETOOTH_CONNECT/SCAN needed. Our target is API 29 but minSdk may change.
4. **DJI RC Bluetooth**: Hardware confirmed present (RK3399 boards include BT). May need testing for any DJI restrictions.
5. **Concurrent transports**: Both WS and BT connected simultaneously needs careful state management.
