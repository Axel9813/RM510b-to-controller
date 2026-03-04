import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Reads orientation data from the device's game rotation vector sensor
/// (fused accelerometer + gyroscope) via a native SensorPlugin.
///
/// Provides relative pitch/yaw/roll in radians, relative to a reference
/// orientation set on start or via [zero].
class GyroService extends ChangeNotifier {
  static const _method = MethodChannel('com.dji.rc/sensor');
  static const _events = EventChannel('com.dji.rc/sensor_state');

  double _pitch = 0.0;
  double _yaw = 0.0;
  double _roll = 0.0;
  bool _running = false;
  StreamSubscription? _sub;

  double get pitch => _pitch;
  double get yaw => _yaw;
  double get roll => _roll;
  bool get running => _running;

  /// Start the sensor listener. Call once at app startup.
  Future<void> start() async {
    _sub ??= _events.receiveBroadcastStream().listen(
      (dynamic data) {
        if (data is List && data.length >= 3) {
          _pitch = (data[0] as num).toDouble();
          _yaw = (data[1] as num).toDouble();
          _roll = (data[2] as num).toDouble();
          _running = true;
          notifyListeners();
        }
      },
      onError: (dynamic error) {
        debugPrint('[GyroService] Event stream error: $error');
      },
    );

    try {
      final ok = await _method.invokeMethod<bool>('start') ?? false;
      _running = ok;
      notifyListeners();
      debugPrint('[GyroService] start returned: $ok');
    } catch (e) {
      debugPrint('[GyroService] start failed: $e');
    }
  }

  /// Stop the sensor listener.
  Future<void> stop() async {
    _sub?.cancel();
    _sub = null;
    try {
      await _method.invokeMethod('stop');
    } catch (_) {}
    _running = false;
    _pitch = 0.0;
    _yaw = 0.0;
    _roll = 0.0;
    notifyListeners();
  }

  /// Re-zero the reference orientation. The current position becomes "center".
  Future<void> zero() async {
    try {
      await _method.invokeMethod('zero');
    } catch (e) {
      debugPrint('[GyroService] zero failed: $e');
    }
  }

  /// Switch between "game" (no magnetometer) and "full" (with magnetometer).
  Future<void> setSensorType(String type) async {
    try {
      await _method.invokeMethod('setSensorType', {'type': type});
    } catch (e) {
      debugPrint('[GyroService] setSensorType failed: $e');
    }
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }
}
