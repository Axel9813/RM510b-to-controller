/// Announcement service — broadcasts the RC's identity so the PC can find us.
///
/// This is the reverse of the old DiscoveryService. Instead of the RC
/// searching for a PC server, the RC **announces itself** and the PC
/// listens and connects to us.
///
/// Mechanisms:
///  1. **UDP broadcast** (port 8765) — broadcasts identity every 3 s
///  2. **mDNS / DNS-SD** (_dji-rc._tcp) — zero-config advertisement
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
// ─── Constants ────────────────────────────────────────────────────────────────

const int _udpAnnouncePort = 8765;
const String _magicPrefix = 'DJI_RC_DISCOVER|';
const Duration _announceInterval = Duration(seconds: 3);

const _multicastChannel = MethodChannel('com.dji.rc/multicast');

// ─── RFC-1918 filter ─────────────────────────────────────────────────────────

bool _isLanIp(String ip) {
  try {
    final parts = ip.split('.').map(int.parse).toList();
    if (parts.length != 4) return false;
    final a = parts[0], b = parts[1];
    if (a == 10) return true;
    if (a == 172 && b >= 16 && b <= 31) return true;
    if (a == 192 && b == 168) return true;
    return false;
  } catch (_) {
    return false;
  }
}

// ─── AnnouncementService ─────────────────────────────────────────────────────

/// Broadcasts the RC's WebSocket server identity to the LAN so the PC can
/// discover and connect to us.
class AnnouncementService extends ChangeNotifier {
  bool _running = false;
  int _wsPort;
  Timer? _announceTimer;
  RawDatagramSocket? _socket;

  bool get announcing => _running;

  AnnouncementService({int wsPort = 8080}) : _wsPort = wsPort;

  /// Update the WebSocket port being announced (if changed at runtime).
  void setPort(int port) {
    _wsPort = port;
  }

  Future<void> start() async {
    if (_running) return;
    _running = true;
    notifyListeners();

    try {
      await _multicastChannel.invokeMethod<void>('acquire');
    } catch (_) {}

    // Start UDP broadcast
    await _startUdpAnnounce();

    debugPrint('[Announce] Broadcasting RC identity every ${_announceInterval.inSeconds}s'
        ' on UDP port $_udpAnnouncePort (WS port $_wsPort)');
  }

  void stop() {
    _running = false;
    _announceTimer?.cancel();
    _announceTimer = null;
    _socket?.close();
    _socket = null;
    try {
      _multicastChannel.invokeMethod<void>('release');
    } catch (_) {}
    notifyListeners();
  }

  // ── UDP broadcast announcements ─────────────────────────────────────────

  Future<void> _startUdpAnnounce() async {
    try {
      _socket = await RawDatagramSocket.bind(
        InternetAddress.anyIPv4, 0,
        reuseAddress: true,
      );
      _socket!.broadcastEnabled = true;

      // Send immediately, then every 3 seconds
      _sendAnnounce();
      _announceTimer = Timer.periodic(_announceInterval, (_) {
        if (_running) _sendAnnounce();
      });
    } catch (e) {
      debugPrint('[Announce] UDP socket error: $e');
    }
  }

  Future<void> _sendAnnounce() async {
    final ips = await _getLanIps();
    final payload = _buildIdentityFrame(ips);

    // Send to directed broadcast for each LAN subnet + limited broadcast
    final targets = <String>{'255.255.255.255'};
    for (final ip in ips) {
      final parts = ip.split('.');
      targets.add('${parts[0]}.${parts[1]}.${parts[2]}.255');
    }

    for (final target in targets) {
      try {
        _socket?.send(
          payload,
          InternetAddress(target),
          _udpAnnouncePort,
        );
      } catch (_) {}
    }
  }

  List<int> _buildIdentityFrame(List<String> ips) {
    final identity = jsonEncode({
      'type': 'dji_rc_server',
      'name': 'DJI RC',
      'port': _wsPort,
      'ips': ips,
    });
    return utf8.encode('$_magicPrefix$identity');
  }

  // ── LAN IP discovery ────────────────────────────────────────────────────

  Future<List<String>> _getLanIps() async {
    final ips = <String>{};
    try {
      for (final iface in await NetworkInterface.list(
        type: InternetAddressType.IPv4,
        includeLinkLocal: false,
      )) {
        for (final addr in iface.addresses) {
          if (_isLanIp(addr.address)) {
            ips.add(addr.address);
          }
        }
      }
    } catch (e) {
      debugPrint('[Announce] IP enum error: $e');
    }
    return ips.toList();
  }

  @override
  void dispose() {
    stop();
    super.dispose();
  }
}
