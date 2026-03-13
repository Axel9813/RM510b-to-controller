import 'package:flutter/services.dart';

/// Thin wrapper around the native HapticPlugin for gamepad rumble feedback.
///
/// Call [rumble] with motor values (0–255) received from the PC server.
/// Call [cancel] to stop any ongoing vibration.
class HapticService {
  static const _channel = MethodChannel('com.dji.rc/haptic');

  /// Trigger vibration mapped from gamepad rumble motors.
  /// [large] = low-frequency heavy motor (0–255).
  /// [small] = high-frequency light motor (0–255).
  Future<void> rumble(int large, int small) async {
    await _channel.invokeMethod('rumble', {
      'large': large,
      'small': small,
    });
  }

  /// Stop any ongoing vibration.
  Future<void> cancel() async {
    await _channel.invokeMethod('cancel');
  }

  /// Check if the device has a vibration motor.
  Future<bool> hasVibrator() async {
    return await _channel.invokeMethod<bool>('hasVibrator') ?? false;
  }
}
