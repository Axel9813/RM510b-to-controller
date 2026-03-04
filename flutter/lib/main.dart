import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import 'app.dart';
import 'services/rc_state_service.dart';
import 'services/pico_service.dart';
import 'services/gyro_service.dart';
import 'services/discovery_service.dart';
import 'services/websocket_service.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setPreferredOrientations([DeviceOrientation.landscapeLeft, DeviceOrientation.landscapeRight]);

  final wsService = WebSocketService();
  final announceService = AnnouncementService(wsPort: 8080);
  final picoService = PicoService();
  final gyroService = GyroService();

  // Auto-start: RC runs a WebSocket server and broadcasts its identity
  wsService.startServer(8080);
  announceService.start();
  picoService.start();
  gyroService.start();

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => RcStateService()),
        ChangeNotifierProvider.value(value: picoService),
        ChangeNotifierProvider.value(value: gyroService),
        ChangeNotifierProvider.value(value: announceService),
        ChangeNotifierProvider.value(value: wsService),
      ],
      child: const RcControllerApp(),
    ),
  );
}
