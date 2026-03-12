import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app.dart';
import 'services/rc_state_service.dart';
import 'services/pico_service.dart';
import 'services/gyro_service.dart';
import 'services/discovery_service.dart';
import 'services/transport/transport_manager.dart';
import 'services/transport/websocket_transport.dart';
import 'services/transport/bluetooth_transport.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setPreferredOrientations([DeviceOrientation.landscapeLeft, DeviceOrientation.landscapeRight]);

  final transportManager = TransportManager();

  // Register WebSocket transport
  final wsTransport = WebSocketTransport(port: 8080);
  transportManager.registerTransport(wsTransport);

  // Register Bluetooth transport
  final btTransport = BluetoothTransport();
  transportManager.registerTransport(btTransport);

  final announceService = AnnouncementService(wsPort: 8080);
  final picoService = PicoService();
  final gyroService = GyroService();
  final rcService = RcStateService();

  // Auto-start
  wsTransport.start();
  announceService.start();
  picoService.start();
  gyroService.start();
  rcService.start();

  // Auto-start BT if a saved target exists
  final prefs = await SharedPreferences.getInstance();
  final btAddr = prefs.getString('bt_target_address');
  if (btAddr != null) {
    final btName = prefs.getString('bt_target_name');
    btTransport.setTarget(btAddr, name: btName, channel: 4);
    btTransport.start();
  }

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: rcService),
        ChangeNotifierProvider.value(value: picoService),
        ChangeNotifierProvider.value(value: gyroService),
        ChangeNotifierProvider.value(value: announceService),
        ChangeNotifierProvider.value(value: transportManager),
      ],
      child: const RcControllerApp(),
    ),
  );
}
