import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'rc_transport.dart';

/// WebSocket **server** transport running on the RC.
///
/// The PC connects to us (outbound from PC -> inbound to RC).
/// This reversal avoids Windows firewall issues since outbound TCP is
/// virtually never blocked.
class WebSocketTransport implements RcTransport {
  HttpServer? _httpServer;
  WebSocket? _client;
  StreamSubscription? _clientSub;
  Timer? _sendTimer;
  Timer? _pingTimer;

  TransportStatus _status = TransportStatus.stopped;
  String? _error;
  int? _listeningPort;
  String? _clientAddress;

  // Dead-connection detection: count consecutive send failures
  int _sendFailures = 0;
  static const int _maxSendFailures = 5;

  // Application-level ping: detect silent connection death
  DateTime? _lastPong;
  static const Duration _pingInterval = Duration(seconds: 10);
  static const Duration _pongTimeout = Duration(seconds: 25);

  // Incoming message stream
  final _incomingController =
      StreamController<Map<String, dynamic>>.broadcast();

  // Outgoing state (set externally, sent at 50 Hz)
  Map<String, dynamic>? _pendingState;

  // Elements sent in the hello handshake when a client connects
  List<Map<String, dynamic>>? _helloElements;
  int _helloGridCols = 0;
  int _helloGridRows = 0;

  // Status listeners
  final List<VoidCallback> _statusListeners = [];

  final int _port;

  WebSocketTransport({int port = 8080}) : _port = port;

  // ── RcTransport interface ────────────────────────────────────────────────

  @override
  TransportType get type => TransportType.websocket;

  @override
  TransportStatus get status => _status;

  @override
  String? get error => _error;

  @override
  String? get peerDescription => _clientAddress;

  @override
  Stream<Map<String, dynamic>> get incoming => _incomingController.stream;

  /// Extra getter for settings UI.
  int? get listeningPort => _listeningPort;
  String? get clientAddress => _clientAddress;

  /// True when the WS client connected from loopback (ADB USB tunnel).
  bool get isViaUsb =>
      _clientAddress == '127.0.0.1' || _clientAddress == '::1';

  // ── Server lifecycle ─────────────────────────────────────────────────────

  @override
  Future<void> start() async {
    if (_httpServer != null) return; // already running

    try {
      _httpServer = await HttpServer.bind(InternetAddress.anyIPv4, _port);
      _listeningPort = _port;
      _status = TransportStatus.listening;
      _error = null;
      _notifyStatusListeners();

      debugPrint('[WS Server] Listening on 0.0.0.0:$_port');

      _httpServer!.listen(
        (HttpRequest request) {
          if (WebSocketTransformer.isUpgradeRequest(request)) {
            _handleUpgrade(request);
          } else {
            request.response
              ..statusCode = HttpStatus.upgradeRequired
              ..write('WebSocket upgrade required')
              ..close();
          }
        },
        onError: (error) {
          debugPrint('[WS Server] HTTP server error: $error');
        },
      );
    } catch (e) {
      _status = TransportStatus.error;
      _error = 'Failed to start server: $e';
      debugPrint('[WS Server] $_error');
      _notifyStatusListeners();
    }
  }

  @override
  Future<void> stop() async {
    _cleanupClient();
    await _httpServer?.close(force: true);
    _httpServer = null;
    _listeningPort = null;
    _status = TransportStatus.stopped;
    _error = null;
    _clientAddress = null;
    _notifyStatusListeners();
  }

  // ── Outgoing messages ────────────────────────────────────────────────────

  @override
  void sendState(Map<String, dynamic> state) {
    _pendingState = state;
  }

  @override
  bool sendMessage(Map<String, dynamic> data) {
    return _sendRaw(data);
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

  // ── Internal: WebSocket upgrade ──────────────────────────────────────────

  Future<void> _handleUpgrade(HttpRequest request) async {
    final addr = request.connectionInfo?.remoteAddress.address ?? '?';
    final port = request.connectionInfo?.remotePort ?? 0;
    debugPrint('[WS Server] Incoming connection from $addr:$port');

    try {
      final ws = await WebSocketTransformer.upgrade(request);

      // Replace existing client (zombie handling)
      if (_client != null) {
        debugPrint('[WS Server] Replacing existing client');
        _cleanupClient();
      }

      _client = ws;
      _clientAddress = addr;
      _sendFailures = 0;
      _lastPong = DateTime.now();
      _status = TransportStatus.connected;
      _error = null;
      _notifyStatusListeners();

      debugPrint('[WS Server] Client connected: $addr:$port');

      // Send hello with element layout
      _sendHello();

      // Listen for incoming messages
      _clientSub = ws.listen(
        (dynamic message) {
          if (message is String) {
            try {
              final json = jsonDecode(message) as Map<String, dynamic>;
              if (json['type'] == 'pong') {
                _lastPong = DateTime.now();
                return;
              }
              _incomingController.add(json);
            } catch (_) {}
          }
        },
        onError: (dynamic error) {
          _onClientDisconnected('Connection error: $error');
        },
        onDone: () {
          _onClientDisconnected('Client disconnected');
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

      // Start application-level ping timer
      _pingTimer?.cancel();
      _pingTimer = Timer.periodic(_pingInterval, (_) => _checkAlive());
    } catch (e) {
      debugPrint('[WS Server] Upgrade failed: $e');
    }
  }

  // ── Internal: ping / alive check ─────────────────────────────────────────

  void _checkAlive() {
    if (_status != TransportStatus.connected) return;
    final lastPong = _lastPong;
    if (lastPong != null &&
        DateTime.now().difference(lastPong) > _pongTimeout) {
      debugPrint(
        '[WS Server] No response for ${_pongTimeout.inSeconds}s — declaring dead',
      );
      _onClientDisconnected('Connection timed out (no response)');
      return;
    }
    _sendRaw({'type': 'ping'});
  }

  // ── Internal: send ───────────────────────────────────────────────────────

  void _sendHello() {
    final elements = _helloElements;
    if (elements == null) return;
    _sendRaw({
      'type': 'hello',
      'elements': elements,
      'gridCols': _helloGridCols,
      'gridRows': _helloGridRows,
    });
  }

  bool _sendRaw(Map<String, dynamic> data) {
    try {
      _client?.add(jsonEncode(data));
      _sendFailures = 0;
      return true;
    } catch (e) {
      _sendFailures++;
      if (_sendFailures >= _maxSendFailures) {
        debugPrint(
          '[WS Server] $_sendFailures consecutive send failures — declaring dead',
        );
        _onClientDisconnected('Send failed: $e');
      }
      return false;
    }
  }

  // ── Internal: client disconnect ──────────────────────────────────────────

  void _onClientDisconnected(String reason) {
    if (_status != TransportStatus.connected &&
        _status != TransportStatus.listening) {
      return;
    }
    debugPrint('[WS Server] $reason');
    _cleanupClient();
    // Server keeps listening — next client will auto-connect
    _status = _httpServer != null
        ? TransportStatus.listening
        : TransportStatus.stopped;
    _error = null;
    _clientAddress = null;
    _notifyStatusListeners();
  }

  void _cleanupClient() {
    _sendTimer?.cancel();
    _sendTimer = null;
    _pingTimer?.cancel();
    _pingTimer = null;
    _clientSub?.cancel();
    _clientSub = null;
    _sendFailures = 0;
    _lastPong = null;
    try {
      _client?.close();
    } catch (_) {}
    _client = null;
  }
}
