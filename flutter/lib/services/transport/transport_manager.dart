import 'dart:async';

import 'package:flutter/foundation.dart';

import 'rc_transport.dart';

export 'rc_transport.dart';

enum TransportPreference { auto, websocket, bluetooth, usb }

/// Manages multiple transports, selects the best one, and exposes a unified
/// interface to the rest of the app.
///
/// All registered transports run simultaneously (listening/advertising).
/// Only one is "active" for data flow. When a higher-priority transport
/// connects, the manager switches automatically.
class TransportManager extends ChangeNotifier {
  /// Priority order for auto mode: USB > WiFi > Bluetooth.
  static const _autoPriority = [
    TransportType.usb,
    TransportType.websocket,
    TransportType.bluetooth,
  ];

  final Map<TransportType, RcTransport> _transports = {};
  TransportPreference _preference = TransportPreference.auto;
  RcTransport? _activeTransport;

  final _incomingController =
      StreamController<Map<String, dynamic>>.broadcast();
  StreamSubscription? _activeSub;

  // ── Getters ──────────────────────────────────────────────────────────────

  TransportPreference get preference => _preference;
  RcTransport? get activeTransport => _activeTransport;
  TransportType? get activeType => _activeTransport?.type;
  TransportStatus get status =>
      _activeTransport?.status ?? TransportStatus.stopped;
  String? get error => _activeTransport?.error;
  String? get peerDescription => _activeTransport?.peerDescription;
  bool get isConnected =>
      _activeTransport?.status == TransportStatus.connected;

  /// Unified incoming message stream (re-piped from the active transport).
  Stream<Map<String, dynamic>> get incoming => _incomingController.stream;

  // ── Registration ─────────────────────────────────────────────────────────

  void registerTransport(RcTransport transport) {
    _transports[transport.type] = transport;
    transport.addStatusListener(() => _onTransportStatusChanged(transport));
  }

  // ── Preference ───────────────────────────────────────────────────────────

  void setPreference(TransportPreference pref) {
    _preference = pref;
    _enforcePreference();
    _evaluateActiveTransport();
    notifyListeners();
  }

  // ── Lifecycle ────────────────────────────────────────────────────────────

  Future<void> startAll() async {
    for (final t in _transports.values) {
      await t.start();
    }
  }

  Future<void> stopAll() async {
    for (final t in _transports.values) {
      await t.stop();
    }
  }

  // ── Outgoing messages ────────────────────────────────────────────────────

  void sendState(Map<String, dynamic> state) {
    _activeTransport?.sendState(state);
  }

  void setHelloElements(List<Map<String, dynamic>> elements,
      {int gridCols = 0, int gridRows = 0}) {
    // Set on ALL transports so any transport that connects later has the data.
    for (final t in _transports.values) {
      t.setHelloElements(elements, gridCols: gridCols, gridRows: gridRows);
    }
  }

  void sendElementEvent(Map<String, dynamic> event) {
    _activeTransport?.sendMessage(event);
  }

  bool sendMessage(Map<String, dynamic> data) {
    return _activeTransport?.sendMessage(data) ?? false;
  }

  // ── Transport status helpers (for settings UI) ───────────────────────────

  /// Get status of a specific transport type.
  TransportStatus transportStatus(TransportType type) =>
      _transports[type]?.status ?? TransportStatus.stopped;

  String? transportError(TransportType type) => _transports[type]?.error;

  String? transportPeer(TransportType type) =>
      _transports[type]?.peerDescription;

  /// Get a registered transport by type (for UI access to transport-specific features).
  RcTransport? getTransport(TransportType type) => _transports[type];

  // ── Internal ─────────────────────────────────────────────────────────────

  /// Stop non-preferred transports in forced mode; restart all in auto mode.
  void _enforcePreference() {
    if (_preference == TransportPreference.auto) {
      // Restart any previously stopped transports
      for (final t in _transports.values) {
        if (t.status == TransportStatus.stopped) {
          t.start();
        }
      }
    } else {
      // Stop all transports that don't match the forced preference
      final preferred = _preferenceToType(_preference);
      for (final entry in _transports.entries) {
        if (entry.key != preferred) {
          entry.value.stop();
        } else if (entry.value.status == TransportStatus.stopped) {
          entry.value.start();
        }
      }
    }
  }

  void _onTransportStatusChanged(RcTransport transport) {
    _evaluateActiveTransport();
    notifyListeners();
  }

  void _evaluateActiveTransport() {
    RcTransport? best;

    if (_preference != TransportPreference.auto) {
      // Forced mode: use the specified transport type
      final type = _preferenceToType(_preference);
      if (type != null) best = _transports[type];
    } else {
      // Auto mode: pick highest-priority connected transport
      for (final type in _autoPriority) {
        final t = _transports[type];
        if (t != null && t.status == TransportStatus.connected) {
          best = t;
          break;
        }
      }
      // Nothing connected: pick highest-priority listening transport
      if (best == null) {
        for (final type in _autoPriority) {
          final t = _transports[type];
          if (t != null && t.status == TransportStatus.listening) {
            best = t;
            break;
          }
        }
      }
      // Fall back to anything registered
      best ??= _transports.values.firstOrNull;
    }

    if (best != _activeTransport) {
      _activeTransport = best;
      _switchIncomingStream();
    }
  }

  void _switchIncomingStream() {
    _activeSub?.cancel();
    _activeSub = _activeTransport?.incoming.listen(
      (msg) => _incomingController.add(msg),
    );
  }

  static TransportType? _preferenceToType(TransportPreference pref) {
    return switch (pref) {
      TransportPreference.websocket => TransportType.websocket,
      TransportPreference.bluetooth => TransportType.bluetooth,
      TransportPreference.usb => TransportType.usb,
      TransportPreference.auto => null,
    };
  }

  @override
  void dispose() {
    for (final t in _transports.values) {
      t.stop();
    }
    _activeSub?.cancel();
    _incomingController.close();
    super.dispose();
  }
}
