import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'rc_transport.dart';

/// Bluetooth RFCOMM client transport running on the RC.
///
/// Connects OUT to the PC's RFCOMM server using a native platform channel
/// that supports both SDP-based and raw channel connections.
/// Uses newline-delimited JSON framing.
class BluetoothTransport implements RcTransport {
  static const _method = MethodChannel('com.dji.rc/bluetooth');
  static const _event = EventChannel('com.dji.rc/bluetooth_data');

  StreamSubscription? _dataSub;
  Timer? _sendTimer;
  Timer? _pingTimer;

  TransportStatus _status = TransportStatus.stopped;
  String? _error;
  String? _targetAddress;
  String? _targetName;
  int? _targetChannel; // null = use SDP, int = raw channel

  // Dead-connection detection
  int _sendFailures = 0;
  static const int _maxSendFailures = 5;

  // Application-level ping
  DateTime? _lastPong;
  static const Duration _pingInterval = Duration(seconds: 10);
  static const Duration _pongTimeout = Duration(seconds: 25);

  // Incoming message stream
  final _incomingController =
      StreamController<Map<String, dynamic>>.broadcast();

  // Outgoing state (set externally, sent at 50 Hz)
  Map<String, dynamic>? _pendingState;

  // Elements for hello handshake
  List<Map<String, dynamic>>? _helloElements;
  int _helloGridCols = 0;
  int _helloGridRows = 0;

  // Status listeners
  final List<VoidCallback> _statusListeners = [];

  // Buffer for incomplete lines
  String _rxBuffer = '';
  static const int _maxRxBufferSize = 64 * 1024; // 64 KB

  // Reconnection
  bool _running = false;
  Timer? _reconnectTimer;
  int _reconnectAttempts = 0;
  static const Duration _minReconnectDelay = Duration(seconds: 2);
  static const Duration _maxReconnectDelay = Duration(seconds: 15);

  // ── RcTransport interface ────────────────────────────────────────────────

  @override
  TransportType get type => TransportType.bluetooth;

  @override
  TransportStatus get status => _status;

  @override
  String? get error => _error;

  @override
  String? get peerDescription => _targetName ?? _targetAddress;

  @override
  Stream<Map<String, dynamic>> get incoming => _incomingController.stream;

  /// The target Bluetooth address.
  String? get targetAddress => _targetAddress;
  String? get targetName => _targetName;
  bool get hasTarget => _targetAddress != null;

  // ── Target management ────────────────────────────────────────────────────

  void setTarget(String address, {String? name, int? channel}) {
    _targetAddress = address;
    _targetName = name;
    _targetChannel = channel;
  }

  /// Get paired Bluetooth devices via platform channel.
  Future<List<Map<String, String>>> getPairedDevices() async {
    try {
      final result = await _method.invokeMethod('getPairedDevices');
      if (result is List) {
        return result.map((d) => Map<String, String>.from(d as Map)).toList();
      }
      return [];
    } catch (e) {
      debugPrint('[BT] Failed to get paired devices: $e');
      return [];
    }
  }

  /// Check if Bluetooth is available and enabled.
  Future<bool> get isAvailable async {
    try {
      return await _method.invokeMethod('isAvailable') ?? false;
    } catch (_) {
      return false;
    }
  }

  // ── Lifecycle ────────────────────────────────────────────────────────────

  @override
  Future<void> start() async {
    _running = true;
    if (_targetAddress == null) {
      _status = TransportStatus.stopped;
      _notifyStatusListeners();
      return;
    }
    _connect();
  }

  @override
  Future<void> stop() async {
    _running = false;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _reconnectAttempts = 0;
    await _cleanup();
    _status = TransportStatus.stopped;
    _error = null;
    _notifyStatusListeners();
  }

  // ── Outgoing messages ────────────────────────────────────────────────────

  @override
  void sendState(Map<String, dynamic> state) {
    _pendingState = state;
  }

  @override
  bool sendMessage(Map<String, dynamic> data) {
    _sendControl(data);
    return true;
  }

  @override
  void setHelloElements(List<Map<String, dynamic>> elements,
      {int gridCols = 0, int gridRows = 0}) {
    _helloElements = elements;
    _helloGridCols = gridCols;
    _helloGridRows = gridRows;
    if (_status == TransportStatus.connected) {
      _sendHello();
    }
  }

  // ── Status listeners ─────────────────────────────────────────────────────

  @override
  void addStatusListener(VoidCallback listener) {
    _statusListeners.add(listener);
  }

  @override
  void removeStatusListener(VoidCallback listener) {
    _statusListeners.remove(listener);
  }

  void _notifyStatusListeners() {
    for (final l in List.of(_statusListeners)) {
      l();
    }
  }

  // ── Internal: connection ────────────────────────────────────────────────

  Future<void> _connect() async {
    if (!_running || _targetAddress == null) return;

    // Don't change status to listening — BT is a client, not a server.
    _error = null;

    try {
      debugPrint('[BT] Connecting to $_targetAddress (channel: $_targetChannel)...');

      final args = <String, dynamic>{
        'address': _targetAddress,
      };
      if (_targetChannel != null) {
        args['channel'] = _targetChannel;
      }

      await _method.invokeMethod('connect', args);
      debugPrint('[BT] Connected to $_targetAddress');

      _sendFailures = 0;
      _lastPong = DateTime.now();
      _rxBuffer = '';
      _reconnectAttempts = 0;
      _status = TransportStatus.connected;
      _error = null;
      _notifyStatusListeners();

      // Send hello
      _sendHello();

      // Listen for incoming data via EventChannel
      _dataSub = _event.receiveBroadcastStream().listen(
        _onDataReceived,
        onError: (dynamic error) {
          _onDisconnected('Data stream error: $error');
        },
        onDone: () {
          _onDisconnected('Connection closed');
        },
      );

      // Start 50 Hz send loop
      _sendTimer?.cancel();
      _sendTimer = Timer.periodic(const Duration(milliseconds: 20), (_) {
        final state = _pendingState;
        if (state != null) {
          _sendRaw(state);
        }
      });

      // Start ping timer
      _pingTimer?.cancel();
      _pingTimer = Timer.periodic(_pingInterval, (_) => _checkAlive());
    } catch (e) {
      debugPrint('[BT] Connection failed: $e');
      _reconnectAttempts++;
      _error = '$e';
      _status = TransportStatus.error;
      _notifyStatusListeners();

      if (_running) {
        _scheduleReconnect();
      }
    }
  }

  void _onDataReceived(dynamic data) {
    if (data is Uint8List) {
      _rxBuffer += utf8.decode(data, allowMalformed: true);
    } else {
      return;
    }

    // Guard against unbounded buffer growth from malformed data
    if (_rxBuffer.length > _maxRxBufferSize) {
      debugPrint('[BT] rx buffer overflow (${_rxBuffer.length} bytes), discarding');
      _rxBuffer = '';
      return;
    }

    // Process complete newline-delimited JSON messages
    while (true) {
      final nlIndex = _rxBuffer.indexOf('\n');
      if (nlIndex < 0) break;

      final line = _rxBuffer.substring(0, nlIndex).trim();
      _rxBuffer = _rxBuffer.substring(nlIndex + 1);

      if (line.isEmpty) continue;

      try {
        final json = jsonDecode(line) as Map<String, dynamic>;
        if (json['type'] == 'pong') {
          _lastPong = DateTime.now();
          continue;
        }
        _incomingController.add(json);
      } catch (_) {
        debugPrint('[BT] Invalid JSON: $line');
      }
    }
  }

  // ── Internal: ping / alive ─────────────────────────────────────────────

  void _checkAlive() {
    if (_status != TransportStatus.connected) return;
    final lastPong = _lastPong;
    if (lastPong != null &&
        DateTime.now().difference(lastPong) > _pongTimeout) {
      debugPrint('[BT] No response for ${_pongTimeout.inSeconds}s — dead');
      _onDisconnected('Connection timed out');
      return;
    }
    _sendControl({'type': 'ping'});
  }

  // ── Internal: send ──────────────────────────────────────────────────────

  void _sendHello() {
    final elements = _helloElements;
    if (elements == null) return;
    _sendControl({
      'type': 'hello',
      'elements': elements,
      'gridCols': _helloGridCols,
      'gridRows': _helloGridRows,
    });
  }

  /// Send state data (droppable — only latest is kept).
  void _sendRaw(Map<String, dynamic> data) {
    if (_status != TransportStatus.connected) return;
    final line = '${jsonEncode(data)}\n';
    _method.invokeMethod('send', {'data': Uint8List.fromList(utf8.encode(line))}).then((_) {
      _sendFailures = 0;
    }).catchError((Object e) {
      _sendFailures++;
      if (_sendFailures >= _maxSendFailures) {
        debugPrint('[BT] $_sendFailures send failures — declaring dead');
        _onDisconnected('Send failed: $e');
      }
    });
  }

  /// Send control message (queued, guaranteed delivery).
  void _sendControl(Map<String, dynamic> data) {
    if (_status != TransportStatus.connected) return;
    final line = '${jsonEncode(data)}\n';
    _method.invokeMethod('sendControl', {'data': Uint8List.fromList(utf8.encode(line))}).catchError((Object e) {
      debugPrint('[BT] sendControl failed: $e');
    });
  }

  // ── Internal: disconnect / reconnect ───────────────────────────────────

  void _onDisconnected(String reason) {
    if (_status != TransportStatus.connected &&
        _status != TransportStatus.listening) {
      return;
    }
    debugPrint('[BT] $reason');
    _cleanup();
    _error = reason;
    _status = TransportStatus.error;
    _notifyStatusListeners();

    if (_running) {
      _scheduleReconnect();
    }
  }

  Future<void> _cleanup() async {
    _sendTimer?.cancel();
    _sendTimer = null;
    _pingTimer?.cancel();
    _pingTimer = null;
    _dataSub?.cancel();
    _dataSub = null;
    _sendFailures = 0;
    _lastPong = null;
    _rxBuffer = '';
    try {
      await _method.invokeMethod('disconnect');
    } catch (_) {}
  }

  void _scheduleReconnect() {
    if (!_running || _targetAddress == null) return;
    _reconnectTimer?.cancel();
    final delay = Duration(
      milliseconds: (_minReconnectDelay.inMilliseconds +
              _reconnectAttempts * 1000)
          .clamp(
              _minReconnectDelay.inMilliseconds,
              _maxReconnectDelay.inMilliseconds),
    );
    debugPrint('[BT] Reconnecting in ${delay.inSeconds}s...');
    _reconnectTimer = Timer(delay, _connect);
  }
}
