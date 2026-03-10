import 'dart:async';

import 'package:flutter/foundation.dart';

enum TransportType { websocket, bluetooth, usb }
enum TransportStatus { stopped, listening, connected, error }

/// Abstract base for all RC-side transports.
///
/// Each transport is responsible for:
///   - Accepting or establishing a connection to a PC peer
///   - Providing an incoming message stream
///   - Sending outgoing messages (state at 50Hz, hello, element_event, ping)
///   - Ping/pong keepalive and dead-connection detection
abstract class RcTransport {
  TransportType get type;
  TransportStatus get status;
  String? get error;
  String? get peerDescription;

  /// Incoming messages from the PC.
  Stream<Map<String, dynamic>> get incoming;

  /// Start the transport (begin listening / advertising).
  Future<void> start();

  /// Stop the transport completely.
  Future<void> stop();

  /// Send a JSON message to the connected peer. Returns false if not connected.
  bool sendMessage(Map<String, dynamic> data);

  /// Throttled state send — stores pending, actual send at 50Hz.
  void sendState(Map<String, dynamic> state);

  /// Register hello elements for handshake on (re)connection.
  void setHelloElements(List<Map<String, dynamic>> elements,
      {int gridCols = 0, int gridRows = 0});

  /// Listen for status changes.
  void addStatusListener(VoidCallback listener);
  void removeStatusListener(VoidCallback listener);
}
