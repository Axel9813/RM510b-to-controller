import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

enum ConnectionStatus { disconnected, connecting, connected, error }

/// WebSocket **server** running on the RC.
///
/// The PC connects to us (outbound from PC → inbound to RC).
/// This reversal avoids Windows firewall issues since outbound TCP is
/// virtually never blocked.
class WebSocketService extends ChangeNotifier {
  HttpServer? _httpServer;
  WebSocket? _client;
  StreamSubscription? _clientSub;
  Timer? _sendTimer;
  Timer? _pingTimer;

  ConnectionStatus _status = ConnectionStatus.disconnected;
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

  // ── Getters ──────────────────────────────────────────────────────────────

  ConnectionStatus get status => _status;
  String? get error => _error;
  int? get listeningPort => _listeningPort;
  String? get clientAddress => _clientAddress;
  Stream<Map<String, dynamic>> get incoming => _incomingController.stream;

  // ── Server lifecycle ─────────────────────────────────────────────────────

  /// Start the WebSocket server on [port].
  /// Listens on all interfaces (0.0.0.0) for incoming PC connections.
  Future<void> startServer([int port = 8080]) async {
    if (_httpServer != null) return; // already running

    try {
      _httpServer = await HttpServer.bind(InternetAddress.anyIPv4, port);
      _listeningPort = port;
      _status = ConnectionStatus.disconnected;
      _error = null;
      notifyListeners();

      debugPrint('[WS Server] Listening on 0.0.0.0:$port');

      _httpServer!.listen(
        (HttpRequest request) {
          if (WebSocketTransformer.isUpgradeRequest(request)) {
            _handleUpgrade(request);
          } else {
            // Not a WebSocket request — return 426
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
      _status = ConnectionStatus.error;
      _error = 'Failed to start server: $e';
      debugPrint('[WS Server] $error');
      notifyListeners();
    }
  }

  /// Stop the server and disconnect any active client.
  Future<void> stopServer() async {
    _cleanupClient();
    await _httpServer?.close(force: true);
    _httpServer = null;
    _listeningPort = null;
    _status = ConnectionStatus.disconnected;
    _error = null;
    _clientAddress = null;
    notifyListeners();
  }

  // ── Outgoing messages ────────────────────────────────────────────────────

  void sendState(Map<String, dynamic> state) {
    _pendingState = state;
  }

  void sendElementEvent(Map<String, dynamic> event) {
    _sendRaw(event);
  }

  /// Register the current interface layout for the hello handshake.
  void setHelloElements(List<Map<String, dynamic>> elements) {
    _helloElements = elements;
    // If a client is already connected, send hello now
    if (_status == ConnectionStatus.connected) {
      _sendHello();
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
      _status = ConnectionStatus.connected;
      _error = null;
      notifyListeners();

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
              _lastPong = DateTime.now();
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
    if (_status != ConnectionStatus.connected) return;
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
    _sendRaw({'type': 'hello', 'elements': elements});
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
    if (_status == ConnectionStatus.disconnected) return;
    debugPrint('[WS Server] $reason');
    _cleanupClient();
    _status = ConnectionStatus.disconnected;
    _error = null;
    _clientAddress = null;
    notifyListeners();
    // Server keeps listening — next client will auto-connect
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

  // ── Lifecycle ────────────────────────────────────────────────────────────

  @override
  void dispose() {
    _cleanupClient();
    _httpServer?.close(force: true);
    _incomingController.close();
    super.dispose();
  }
}
