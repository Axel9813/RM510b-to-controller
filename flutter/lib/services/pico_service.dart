import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../models/pico_state.dart';

/// Reads button state from a Raspberry Pi Pico connected via USB CDC serial.
///
/// Uses platform channels to communicate with the native PicoPlugin/PicoUsbReader
/// on Android which handles USB host access and frame parsing.
class PicoService extends ChangeNotifier {
  static const _method = MethodChannel('com.dji.rc/pico');
  static const _events = EventChannel('com.dji.rc/pico_state');

  PicoState _state = const PicoState();
  String _status = 'disconnected';
  StreamSubscription? _sub;

  PicoState get state => _state;
  String get status => _status;
  int get bitmask => _state.bitmask;

  /// Start reading from the Pico. Call once at app startup.
  Future<void> start() async {
    debugPrint('[PicoService] start() called');

    // Subscribe to bitmask events from native side
    try {
      _sub ??= _events.receiveBroadcastStream().listen(
        (dynamic data) {
          final mask = data as int;
          if (mask != _state.bitmask) {
            _state = PicoState(bitmask: mask);
            _status = 'connected';
            notifyListeners();
          }
        },
        onError: (dynamic error) {
          debugPrint('[PicoService] Event stream error: $error');
          _status = 'error: $error';
          notifyListeners();
        },
      );
    } catch (e) {
      debugPrint('[PicoService] Failed to subscribe to events: $e');
    }

    // Try to start the native USB reader.
    // First call may return false while waiting for USB permission dialog.
    // Retry a few times to handle the async permission grant.
    for (var attempt = 1; attempt <= 5; attempt++) {
      try {
        debugPrint('[PicoService] Calling native start (attempt $attempt)...');
        final ok = await _method.invokeMethod<bool>('start') ?? false;
        debugPrint('[PicoService] Native start returned: $ok');
        if (ok) {
          _status = 'connected';
          notifyListeners();
          return;
        }
        _status = 'waiting for device/permission';
        notifyListeners();
      } catch (e) {
        _status = 'error: $e';
        debugPrint('[PicoService] start failed: $e');
        notifyListeners();
        return;
      }
      // Wait before retrying (give user time to approve permission dialog)
      await Future.delayed(const Duration(seconds: 3));
    }
    debugPrint('[PicoService] gave up after 5 attempts');
  }

  /// Stop reading from the Pico.
  Future<void> stop() async {
    _sub?.cancel();
    _sub = null;
    try {
      await _method.invokeMethod('stop');
    } catch (_) {}
    _state = const PicoState();
    _status = 'disconnected';
    notifyListeners();
  }

  /// Query the current native-side status (for diagnostics).
  Future<Map<String, dynamic>> queryStatus() async {
    try {
      final result = await _method.invokeMethod<Map>('status');
      return Map<String, dynamic>.from(result ?? {});
    } catch (e) {
      return {'error': e.toString()};
    }
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }
}
