import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../services/rc_state_service.dart';
import '../services/pico_service.dart';
import '../services/gyro_service.dart';
import '../services/discovery_service.dart';
import '../services/transport/transport_manager.dart';
import '../services/transport/websocket_transport.dart';
import '../services/transport/bluetooth_transport.dart';

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
    final transport = context.watch<TransportManager>();

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
            label: 'Transport',
            connected: transport.isConnected,
            detail: _transportDetail(transport),
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

          // ── Connection ──────────────────────────────────────────────────
          Row(
            children: [
              Text('Connection',
                  style: Theme.of(context).textTheme.titleMedium),
              const Spacer(),
              // Transport preference dropdown
              _TransportPreferenceDropdown(transport: transport),
            ],
          ),
          const SizedBox(height: 8),

          // WebSocket server card
          _WebSocketCard(transport: transport),

          const SizedBox(height: 8),

          // Bluetooth card
          _BluetoothSection(transport: transport),

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

  String _transportDetail(TransportManager transport) {
    if (!transport.isConnected) {
      final wsStatus = transport.transportStatus(TransportType.websocket);
      if (wsStatus == TransportStatus.listening) {
        return 'Listening (WiFi)';
      }
      return transport.error ?? 'Disconnected';
    }
    // Detect USB vs WiFi for WebSocket transport
    if (transport.activeType == TransportType.websocket) {
      final ws = transport.getTransport(TransportType.websocket);
      if (ws is WebSocketTransport && ws.isViaUsb) {
        return 'Connected via USB';
      }
      return 'Connected via WiFi';
    }
    final typeName = switch (transport.activeType) {
      TransportType.bluetooth => 'Bluetooth',
      TransportType.usb => 'USB',
      _ => '?',
    };
    return 'Connected via $typeName';
  }
}

// ── Transport preference dropdown ────────────────────────────────────────────

class _TransportPreferenceDropdown extends StatelessWidget {
  final TransportManager transport;

  const _TransportPreferenceDropdown({required this.transport});

  @override
  Widget build(BuildContext context) {
    return DropdownButton<TransportPreference>(
      value: transport.preference,
      isDense: true,
      underline: const SizedBox.shrink(),
      items: const [
        DropdownMenuItem(
          value: TransportPreference.auto,
          child: Text('Auto', style: TextStyle(fontSize: 13)),
        ),
        DropdownMenuItem(
          value: TransportPreference.websocket,
          child: Text('WiFi only', style: TextStyle(fontSize: 13)),
        ),
        DropdownMenuItem(
          value: TransportPreference.bluetooth,
          child: Text('Bluetooth only', style: TextStyle(fontSize: 13)),
        ),
      ],
      onChanged: (pref) {
        if (pref != null) {
          transport.setPreference(pref);
        }
      },
    );
  }
}

// ── WebSocket card ───────────────────────────────────────────────────────────

class _WebSocketCard extends StatelessWidget {
  final TransportManager transport;

  const _WebSocketCard({required this.transport});

  @override
  Widget build(BuildContext context) {
    final wsTransport = transport.getTransport(TransportType.websocket);
    final ws = wsTransport is WebSocketTransport ? wsTransport : null;
    final wsPort = ws?.listeningPort;
    final wsConnected =
        transport.isConnected && transport.activeType == TransportType.websocket;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  wsPort != null
                      ? Icons.wifi_tethering
                      : Icons.wifi_tethering_off,
                  color: wsPort != null ? Colors.green : Colors.grey,
                  size: 20,
                ),
                const SizedBox(width: 8),
                Text(
                  wsPort != null
                      ? 'WebSocket server on port $wsPort'
                      : 'WebSocket server not running',
                  style: const TextStyle(fontWeight: FontWeight.w500),
                ),
              ],
            ),
            if (wsConnected && ws != null) ...[
              const SizedBox(height: 8),
              Row(
                children: [
                  Icon(
                    ws.isViaUsb ? Icons.usb : Icons.wifi,
                    color: Colors.green,
                    size: 18,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    ws.isViaUsb
                        ? 'PC connected via USB'
                        : 'PC connected from ${ws.clientAddress}',
                    style: TextStyle(color: Colors.green.shade300),
                  ),
                ],
              ),
            ],
            if (!wsConnected && wsPort != null) ...[
              const SizedBox(height: 8),
              Text(
                'Waiting for PC to connect...',
                style: TextStyle(color: Colors.grey.shade400),
              ),
            ],
          ],
        ),
      ),
    );
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

class _BluetoothSection extends StatefulWidget {
  final TransportManager transport;

  const _BluetoothSection({required this.transport});

  @override
  State<_BluetoothSection> createState() => _BluetoothSectionState();
}

class _BluetoothSectionState extends State<_BluetoothSection> {
  List<Map<String, String>>? _pairedDevices;
  bool _loading = false;
  bool? _btAvailable;

  BluetoothTransport? get _bt {
    final t = widget.transport.getTransport(TransportType.bluetooth);
    return t is BluetoothTransport ? t : null;
  }

  @override
  void initState() {
    super.initState();
    _checkBtAvailable();
  }

  Future<void> _checkBtAvailable() async {
    final bt = _bt;
    if (bt == null) return;
    final available = await bt.isAvailable;
    if (mounted) setState(() => _btAvailable = available);
  }

  @override
  Widget build(BuildContext context) {
    final bt = _bt;
    if (bt == null) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Text('Bluetooth transport not available',
              style: TextStyle(color: Colors.grey.shade400)),
        ),
      );
    }

    // Show warning if Bluetooth is off
    if (_btAvailable == false) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              Icon(Icons.bluetooth_disabled, color: Colors.orange.shade300, size: 20),
              const SizedBox(width: 8),
              const Expanded(
                child: Text('Bluetooth is turned off. Enable it in system settings.',
                    style: TextStyle(fontWeight: FontWeight.w500)),
              ),
              IconButton(
                onPressed: _checkBtAvailable,
                icon: const Icon(Icons.refresh, size: 18),
                tooltip: 'Recheck',
              ),
            ],
          ),
        ),
      );
    }

    final btStatus = widget.transport.transportStatus(TransportType.bluetooth);
    final isConnected = btStatus == TransportStatus.connected;
    final btError = btStatus == TransportStatus.error ? bt.error : null;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Status row
            Row(
              children: [
                Icon(
                  isConnected ? Icons.bluetooth_connected : Icons.bluetooth,
                  color: isConnected ? Colors.blue : Colors.grey,
                  size: 20,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    isConnected
                        ? 'Bluetooth connected to ${bt.targetName ?? bt.targetAddress ?? "PC"}'
                        : bt.hasTarget
                            ? 'Target: ${bt.targetName ?? bt.targetAddress}'
                            : 'Bluetooth — no target set',
                    style: const TextStyle(fontWeight: FontWeight.w500),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),

            if (btError != null) ...[
              const SizedBox(height: 4),
              Text(btError,
                  style: TextStyle(color: Colors.red.shade300, fontSize: 12)),
            ],

            const SizedBox(height: 12),

            // Action buttons
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                FilledButton.tonalIcon(
                  onPressed: _loading ? null : _loadPairedDevices,
                  icon: const Icon(Icons.refresh, size: 18),
                  label: const Text('Paired Devices'),
                ),
                if (bt.hasTarget && !isConnected)
                  FilledButton.tonalIcon(
                    onPressed: () {
                      _checkBtAvailable();
                      bt.start();
                    },
                    icon: const Icon(Icons.play_arrow, size: 18),
                    label: const Text('Connect'),
                  ),
                if (isConnected)
                  FilledButton.tonalIcon(
                    onPressed: () {
                      bt.stop();
                    },
                    icon: const Icon(Icons.stop, size: 18),
                    label: const Text('Disconnect'),
                  ),
              ],
            ),

            if (_pairedDevices != null) ...[
              const SizedBox(height: 8),
              if (_pairedDevices!.isEmpty)
                Text('No paired devices found.',
                    style: TextStyle(color: Colors.grey.shade400)),
              for (final device in _pairedDevices!)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.bluetooth, size: 18),
                  title: Text(device['name'] ?? 'Unknown'),
                  subtitle: Text(device['address'] ?? '',
                      style: const TextStyle(fontSize: 11)),
                  trailing: bt.targetAddress == device['address']
                      ? const Icon(Icons.check_circle,
                          color: Colors.green, size: 18)
                      : null,
                  onTap: () => _selectDevice(device),
                ),
            ],
          ],
        ),
      ),
    );
  }

  Future<void> _selectDevice(Map<String, String> device) async {
    final bt = _bt;
    if (bt == null) return;

    final addr = device['address']!;
    final name = device['name'];

    bt.setTarget(addr, name: name, channel: 4);
    await bt.stop();
    bt.start();

    // Persist selection
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('bt_target_address', addr);
    if (name != null) {
      await prefs.setString('bt_target_name', name);
    }

    setState(() {});
  }

  Future<void> _loadPairedDevices() async {
    // Recheck BT availability when user taps Paired Devices
    _checkBtAvailable();
    setState(() => _loading = true);
    final bt = _bt;
    if (bt != null) {
      final devices = await bt.getPairedDevices();
      setState(() {
        _pairedDevices = devices;
        _loading = false;
      });
    } else {
      setState(() => _loading = false);
    }
  }
}
