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
  static const _monitorEvents = EventChannel('com.dji.rc/pico_monitor');

  PicoState _state = const PicoState();
  String _status = 'disconnected';
  StreamSubscription? _sub;
  StreamSubscription? _monitorSub;
  bool _monitoring = false;
  final List<String> _monitorLines = [];

  PicoState get state => _state;
  String get status => _status;
  int get bitmask => _state.bitmask;
  int get extraBitmask => _state.extraBitmask;
  int get analogX => _state.analogX;
  int get analogY => _state.analogY;
  bool get isMonitoring => _monitoring;
  List<String> get monitorLines => _monitorLines;

  /// Start reading from the Pico. Call once at app startup.
  Future<void> start() async {
    debugPrint('[PicoService] start() called');

    // Subscribe to bitmask events from native side
    try {
      _sub ??= _events.receiveBroadcastStream().listen(
        (dynamic data) {
          final frame = List<int>.from(data as List);
          final core = frame.isNotEmpty ? frame[0] : 0;
          final extra = frame.length > 1 ? frame[1] : 0;
          final ax = frame.length > 2 ? frame[2] : 0;
          final ay = frame.length > 3 ? frame[3] : 0;
          _state = PicoState(
            bitmask: core,
            extraBitmask: extra,
            analogX: ax,
            analogY: ay,
          );
          _status = 'connected';
          notifyListeners();
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

  /// Upload pending firmware files from /sdcard/pico_firmware/ to the Pico.
  /// Files are pushed there by the PC-side upload_to_pico.py script.
  Future<String> uploadFromStorage() async {
    try {
      final result = await _method.invokeMethod<String>('uploadFromStorage');
      return result ?? 'No result';
    } catch (e) {
      return 'Upload error: $e';
    }
  }

  /// Upload a file to the Pico's filesystem via raw REPL.
  /// Stops the reader, uploads, then soft-reboots and restarts reader.
  Future<String> uploadFile(String filename, Uint8List content) async {
    try {
      final result = await _method.invokeMethod<String>('uploadFile', {
        'filename': filename,
        'content': content,
      });
      return result ?? 'Unknown error';
    } catch (e) {
      return 'Upload error: $e';
    }
  }

  /// Execute Python code on the Pico via raw REPL and return stdout.
  Future<String> executeCode(String code, {bool softReboot = true}) async {
    try {
      final result = await _method.invokeMethod<String>('executeCode', {
        'code': code,
        'softReboot': softReboot,
      });
      return result ?? '';
    } catch (e) {
      return 'Execute error: $e';
    }
  }

  /// Start streaming GPIO monitor. Lines arrive via [monitorLines].
  Future<bool> startMonitor(String code) async {
    _monitorLines.clear();
    _monitorSub = _monitorEvents.receiveBroadcastStream().listen(
      (dynamic data) {
        _monitorLines.add(data as String);
        notifyListeners();
      },
      onError: (dynamic error) {
        debugPrint('[PicoService] Monitor stream error: $error');
      },
    );

    try {
      final ok = await _method.invokeMethod<bool>(
        'startMonitor',
        {'code': code},
      ) ?? false;
      _monitoring = ok;
      if (!ok) {
        _monitorSub?.cancel();
        _monitorSub = null;
      }
      _status = ok ? 'monitoring' : _status;
      notifyListeners();
      return ok;
    } catch (e) {
      _monitorSub?.cancel();
      _monitorSub = null;
      debugPrint('[PicoService] startMonitor failed: $e');
      return false;
    }
  }

  /// Stop the streaming GPIO monitor and restart normal reader.
  Future<void> stopMonitor() async {
    _monitorSub?.cancel();
    _monitorSub = null;
    _monitoring = false;
    notifyListeners();
    try {
      await _method.invokeMethod('stopMonitor');
      _status = 'connected';
      notifyListeners();
    } catch (e) {
      debugPrint('[PicoService] stopMonitor failed: $e');
    }
  }

  @override
  void dispose() {
    _sub?.cancel();
    _monitorSub?.cancel();
    super.dispose();
  }
}
