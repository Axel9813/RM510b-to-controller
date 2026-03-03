import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart';

import '../models/rc_state.dart';

class RcStateService extends ChangeNotifier {
  static const _methodChannel = MethodChannel('com.dji.rc/control');
  static const _eventChannel = EventChannel('com.dji.rc/state');

  RcState _state = const RcState();
  bool _connected = false;
  String? _error;
  StreamSubscription? _subscription;

  // Throttle: emit at most every 20ms (50 Hz)
  DateTime _lastEmit = DateTime.fromMillisecondsSinceEpoch(0);
  static const _minInterval = Duration(milliseconds: 20);

  RcState get state => _state;
  bool get connected => _connected;
  String? get error => _error;

  Future<bool> start() async {
    try {
      final result = await _methodChannel.invokeMethod<bool>('start');
      if (result == true) {
        _connected = true;
        _error = null;
        _listenEvents();
      } else {
        // Permission may have been requested; listen anyway for when it comes through
        _listenEvents();
      }
      notifyListeners();
      return result == true;
    } on PlatformException catch (e) {
      _error = e.message;
      _connected = false;
      notifyListeners();
      return false;
    }
  }

  Future<void> stop() async {
    _subscription?.cancel();
    _subscription = null;
    try {
      await _methodChannel.invokeMethod('stop');
    } catch (_) {}
    _connected = false;
    _state = const RcState();
    notifyListeners();
  }

  Future<Map<String, dynamic>?> getStatus() async {
    try {
      final result = await _methodChannel.invokeMethod<Map>('status');
      if (result != null) {
        _connected = result['connected'] as bool? ?? false;
        _error = result['error'] as String?;
        notifyListeners();
        return Map<String, dynamic>.from(result);
      }
    } on PlatformException catch (e) {
      _error = e.message;
    }
    return null;
  }

  void _listenEvents() {
    _subscription?.cancel();
    _subscription = _eventChannel.receiveBroadcastStream().listen(
      (dynamic event) {
        if (event is Map) {
          final now = DateTime.now();
          if (now.difference(_lastEmit) >= _minInterval) {
            _state = RcState.fromMap(event);
            _connected = true;
            _lastEmit = now;
            notifyListeners();
          }
        }
      },
      onError: (dynamic error) {
        _error = error.toString();
        _connected = false;
        notifyListeners();
      },
    );
  }

  @override
  void dispose() {
    _subscription?.cancel();
    super.dispose();
  }
}
