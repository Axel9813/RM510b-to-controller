import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/layout_storage_service.dart';
import '../services/rc_state_service.dart';
import '../services/pico_service.dart';
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

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final rcService = context.read<RcStateService>();
      final picoService = context.read<PicoService>();
      final wsService = context.read<WebSocketService>();

      // Bridge: push RC state into WebSocket whenever it changes
      _rcListener = () {
        if (wsService.status == ConnectionStatus.connected) {
          final state = rcService.state.copyWith(
            picoBitmask: picoService.bitmask,
          );
          wsService.sendState(state.toJson());
        }
      };
      rcService.addListener(_rcListener!);

      // Load saved layout and pre-register elements with WebSocket
      // so the hello handshake fires immediately on (re-)connection.
      LayoutStorageService().load().then((layout) {
        if (layout.elements.isNotEmpty) {
          wsService.setHelloElements(
            layout.elements.map((e) => e.toJson()).toList(),
          );
        }
      });
    });
  }

  @override
  void dispose() {
    if (_rcListener != null) {
      context.read<RcStateService>().removeListener(_rcListener!);
    }
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
