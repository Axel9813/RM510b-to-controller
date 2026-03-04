import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/layout_storage_service.dart';
import '../services/rc_state_service.dart';
import '../services/pico_service.dart';
import '../services/gyro_service.dart';
import '../services/websocket_service.dart';
import 'settings_tab.dart';
import 'interface_tab.dart';

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  int _tabIndex = 0;
  VoidCallback? _rcListener;
  VoidCallback? _gyroListener;
  StreamSubscription? _incomingSub;

  // Store service refs for safe dispose (context may be deactivated)
  RcStateService? _rcService;
  GyroService? _gyroService;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final rcService = context.read<RcStateService>();
      final picoService = context.read<PicoService>();
      final gyroService = context.read<GyroService>();
      final wsService = context.read<WebSocketService>();
      _rcService = rcService;
      _gyroService = gyroService;

      // Bridge: push RC state + gyro into WebSocket whenever either changes
      void sendState() {
        if (wsService.status == ConnectionStatus.connected) {
          final state = rcService.state.copyWith(
            picoBitmask: picoService.bitmask,
          );
          final json = state.toJson();
          json['gyroPitch'] = gyroService.pitch;
          json['gyroYaw'] = gyroService.yaw;
          json['gyroRoll'] = gyroService.roll;
          wsService.sendState(json);
        }
      }

      _rcListener = sendState;
      _gyroListener = () => sendState();
      rcService.addListener(_rcListener!);
      gyroService.addListener(_gyroListener!);

      // Listen for commands from PC (e.g. gyro_zero, gyro_set_sensor)
      _incomingSub = wsService.incoming.listen((msg) {
        final type = msg['type'] as String?;
        if (type == 'gyro_zero') {
          gyroService.zero();
        } else if (type == 'gyro_set_sensor') {
          final sensorType = msg['sensor_type'] as String?;
          if (sensorType != null) {
            gyroService.setSensorType(sensorType);
          }
        }
      });

      // Load saved layout and pre-register elements with WebSocket
      // so the hello handshake fires immediately on (re-)connection.
      final mq = MediaQuery.of(context);
      final cs = (mq.size.shortestSide / 8).clamp(40.0, 80.0);
      final gridCols = (mq.size.width / cs).floor();
      final gridRows = (mq.size.height / cs).floor();
      LayoutStorageService().load().then((layout) {
        if (layout.elements.isNotEmpty) {
          wsService.setHelloElements(
            layout.elements.map((e) => e.toJson()).toList(),
            gridCols: gridCols,
            gridRows: gridRows,
          );
        }
      });
    });
  }

  @override
  void dispose() {
    if (_rcListener != null) {
      _rcService?.removeListener(_rcListener!);
    }
    if (_gyroListener != null) {
      _gyroService?.removeListener(_gyroListener!);
    }
    _incomingSub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _tabIndex,
        children: [
          SettingsTab(onOpenInterface: () => setState(() => _tabIndex = 1)),
          InterfaceTab(onOpenSettings: () => setState(() => _tabIndex = 0)),
        ],
      ),
    );
  }
}
