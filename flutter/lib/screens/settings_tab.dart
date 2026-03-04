import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/rc_state_service.dart';
import '../services/pico_service.dart';
import '../services/gyro_service.dart';
import '../services/discovery_service.dart';
import '../services/websocket_service.dart';

class SettingsTab extends StatefulWidget {
  final VoidCallback onOpenInterface;

  const SettingsTab({super.key, required this.onOpenInterface});

  @override
  State<SettingsTab> createState() => _SettingsTabState();
}

class _SettingsTabState extends State<SettingsTab> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<RcStateService>().start();
    });
  }

  @override
  Widget build(BuildContext context) {
    final rcService = context.watch<RcStateService>();
    final picoService = context.watch<PicoService>();
    final gyroService = context.watch<GyroService>();
    final announce = context.watch<AnnouncementService>();
    final ws = context.watch<WebSocketService>();

    return SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // ── Status ─────────────────────────────────────────────────────
          Text('Status', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          _StatusRow(
            label: 'RC Input',
            connected: rcService.connected,
            detail: rcService.connected
                ? 'Connected'
                : (rcService.error ?? 'No device'),
          ),
          _StatusRow(
            label: 'Pico',
            connected: picoService.status == 'connected',
            detail: picoService.status,
          ),
          _StatusRow(
            label: 'WS Server',
            connected: ws.status == ConnectionStatus.connected,
            detail: _serverDetail(ws),
          ),
          _StatusRow(
            label: 'Gyro',
            connected: gyroService.running,
            detail: gyroService.running ? 'Running' : 'Stopped',
          ),
          _StatusRow(
            label: 'Announce',
            connected: announce.announcing,
            detail: announce.announcing
                ? 'Broadcasting on UDP $_announcePortDisplay'
                : 'Stopped',
            icon: Icons.cell_tower,
          ),

          const Divider(height: 32),

          // ── Gyro controls ───────────────────────────────────────────────
          Text('Gyro', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Row(
            children: [
              FilledButton.tonalIcon(
                onPressed: gyroService.running ? gyroService.zero : null,
                icon: const Icon(Icons.my_location, size: 18),
                label: const Text('Zero Gyro'),
              ),
              const SizedBox(width: 12),
              if (gyroService.running)
                Text(
                  'P: ${gyroService.pitch.toStringAsFixed(2)}  '
                  'Y: ${gyroService.yaw.toStringAsFixed(2)}  '
                  'R: ${gyroService.roll.toStringAsFixed(2)}',
                  style: TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 12,
                    color: Colors.grey.shade400,
                  ),
                ),
            ],
          ),

          const Divider(height: 32),

          // ── Server info ─────────────────────────────────────────────────
          Text('WebSocket Server',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),

          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(
                        ws.listeningPort != null
                            ? Icons.wifi_tethering
                            : Icons.wifi_tethering_off,
                        color: ws.listeningPort != null
                            ? Colors.green
                            : Colors.grey,
                        size: 20,
                      ),
                      const SizedBox(width: 8),
                      Text(
                        ws.listeningPort != null
                            ? 'Listening on port ${ws.listeningPort}'
                            : 'Server not running',
                        style: const TextStyle(fontWeight: FontWeight.w500),
                      ),
                    ],
                  ),
                  if (ws.status == ConnectionStatus.connected) ...[
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        const Icon(Icons.computer,
                            color: Colors.green, size: 18),
                        const SizedBox(width: 8),
                        Text(
                          'PC connected from ${ws.clientAddress}',
                          style: TextStyle(color: Colors.green.shade300),
                        ),
                      ],
                    ),
                  ],
                  if (ws.status == ConnectionStatus.disconnected &&
                      ws.listeningPort != null) ...[
                    const SizedBox(height: 8),
                    Text(
                      'Waiting for PC to connect...',
                      style: TextStyle(color: Colors.grey.shade400),
                    ),
                  ],
                  if (ws.error != null) ...[
                    const SizedBox(height: 8),
                    Text(
                      ws.error!,
                      style: TextStyle(color: Colors.red.shade300),
                    ),
                  ],
                ],
              ),
            ),
          ),

          const Divider(height: 32),

          // ── Interface builder ──────────────────────────────────────────
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: widget.onOpenInterface,
              icon: const Icon(Icons.dashboard),
              label: const Text('Open Interface'),
            ),
          ),
        ],
      ),
    );
  }

  String get _announcePortDisplay => '8765';

  String _serverDetail(WebSocketService ws) {
    if (ws.listeningPort == null) return 'Server not started';
    return switch (ws.status) {
      ConnectionStatus.disconnected => 'Listening on :${ws.listeningPort}',
      ConnectionStatus.connecting => 'Connecting...',
      ConnectionStatus.connected =>
        'Connected from ${ws.clientAddress ?? "?"}',
      ConnectionStatus.error => ws.error ?? 'Error',
    };
  }
}

// ── Helper widgets ───────────────────────────────────────────────────────────

class _StatusRow extends StatelessWidget {
  final String label;
  final bool connected;
  final String detail;
  final IconData? icon;

  const _StatusRow({
    required this.label,
    required this.connected,
    required this.detail,
    this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Icon(
            icon ?? (connected ? Icons.circle : Icons.cancel),
            size: 14,
            color: connected ? Colors.green : Colors.red.shade300,
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 80,
            child: Text(label,
                style: const TextStyle(fontWeight: FontWeight.w500)),
          ),
          Expanded(
            child: Text(
              detail,
              style: TextStyle(color: Colors.grey.shade400),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}
