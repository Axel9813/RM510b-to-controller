import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/app_layout.dart';
import '../models/interface_element.dart';
import '../services/layout_storage_service.dart';
import '../services/websocket_service.dart';
import '../widgets/builder_overlay.dart';

class InterfaceTab extends StatefulWidget {
  final VoidCallback onOpenSettings;

  const InterfaceTab({super.key, required this.onOpenSettings});

  @override
  State<InterfaceTab> createState() => _InterfaceTabState();
}

class _InterfaceTabState extends State<InterfaceTab> {
  AppLayout _layout = const AppLayout();
  bool _editMode = false;
  bool _loading = true;

  final _storage = LayoutStorageService();
  StreamSubscription<Map<String, dynamic>>? _wsSub;

  @override
  void initState() {
    super.initState();
    _loadLayout();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      // Subscribe to incoming server messages (LED state updates)
      _wsSub = context.read<WebSocketService>().incoming.listen(_handleServerMessage);
    });
  }

  @override
  void dispose() {
    _wsSub?.cancel();
    super.dispose();
  }

  Future<void> _loadLayout() async {
    final layout = await _storage.load();
    if (mounted) {
      setState(() {
        _layout = layout;
        _loading = false;
      });
    }
  }

  void _handleServerMessage(Map<String, dynamic> msg) {
    final type = msg['type'] as String?;
    if (type == 'elements_full_state') {
      final states = msg['states'] as Map<String, dynamic>? ?? {};
      setState(() {
        var updated = _layout;
        for (final entry in states.entries) {
          // Skip IDs not present in the local layout (avoids crash on empty layout)
          final idx = updated.elements.indexWhere((e) => e.id == entry.key);
          if (idx < 0) continue;
          final el = updated.elements[idx];
          if (el is LedElement) {
            updated = updated.updateElement(
                el.id, el.copyWithState(entry.value as bool? ?? false));
          }
        }
        _layout = updated;
      });
    } else if (type == 'element_update') {
      final id = msg['id'] as String?;
      final value = msg['value'];
      if (id == null) return;
      setState(() {
        final idx = _layout.elements.indexWhere((e) => e.id == id);
        if (idx < 0) return;
        final el = _layout.elements[idx];
        if (el is LedElement) {
          _layout = _layout.updateElement(
              id, el.copyWithState(value as bool? ?? false));
        }
      });
    }
  }

  void _onLayoutChanged(AppLayout updated) {
    setState(() => _layout = updated);
    _storage.save(updated);
    // Keep WebSocket hello in sync
    context.read<WebSocketService>().setHelloElements(
          updated.elements.map((e) => e.toJson()).toList(),
        );
  }

  void _onElementPress(String id) {
    final ws = context.read<WebSocketService>();
    if (ws.status != ConnectionStatus.connected) return;
    ws.sendElementEvent({'type': 'element_event', 'id': id, 'event': 'press'});
  }

  void _onElementRelease(String id) {
    final ws = context.read<WebSocketService>();
    if (ws.status != ConnectionStatus.connected) return;
    ws.sendElementEvent({'type': 'element_event', 'id': id, 'event': 'release'});
  }

  void _onSliderChange(String id, double value) {
    final ws = context.read<WebSocketService>();
    if (ws.status != ConnectionStatus.connected) return;
    ws.sendElementEvent({
      'type': 'element_event',
      'id': id,
      'event': 'change',
      'value': double.parse(value.toStringAsFixed(3)),
    });
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        // Main canvas + builder overlay
        if (_loading)
          const Center(child: CircularProgressIndicator())
        else
          BuilderOverlay(
            layout: _layout,
            editMode: _editMode,
            onLayoutChanged: _onLayoutChanged,
            onElementPress: _onElementPress,
            onElementRelease: _onElementRelease,
            onSliderChange: _onSliderChange,
          ),

        // Top-right toolbar
        Positioned(
          top: MediaQuery.of(context).padding.top + 8,
          right: 8,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Edit mode toggle
              AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(24),
                  color: _editMode
                      ? Colors.amber.withValues(alpha: 0.2)
                      : Colors.transparent,
                ),
                child: FloatingActionButton.small(
                  heroTag: 'edit_toggle_fab',
                  backgroundColor: _editMode ? Colors.amber.shade700 : null,
                  onPressed: () => setState(() => _editMode = !_editMode),
                  tooltip: _editMode ? 'Exit Edit Mode' : 'Edit Layout',
                  child: Icon(
                    _editMode ? Icons.check : Icons.edit,
                    size: 20,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              // Settings
              FloatingActionButton.small(
                heroTag: 'settings_fab',
                onPressed: widget.onOpenSettings,
                tooltip: 'Settings',
                child: const Icon(Icons.settings, size: 20),
              ),
            ],
          ),
        ),

        // Edit mode banner
        if (_editMode)
          Positioned(
            top: MediaQuery.of(context).padding.top + 8,
            left: 16,
            child: Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(12),
                color: Colors.amber.shade800.withValues(alpha: 0.85),
              ),
              child: const Text(
                'Edit Mode  •  Drag to move  •  Long-press to rename/delete',
                style: TextStyle(fontSize: 11, color: Colors.white),
              ),
            ),
          ),
      ],
    );
  }
}
