import 'package:flutter/material.dart';

import '../models/interface_element.dart';

/// Context menu that appears (as a bottom sheet) when the user long-presses
/// an element in edit mode. Offers rename and delete.
class ElementOptionsMenu extends StatefulWidget {
  final InterfaceElement element;

  const ElementOptionsMenu({super.key, required this.element});

  /// Shows the options menu and returns the chosen action/result.
  /// Returns `{'action': 'rename', 'name': '...'}` or `{'action': 'delete'}`.
  static Future<Map<String, dynamic>?> show(
      BuildContext context, InterfaceElement element) {
    return showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (_) => ElementOptionsMenu(element: element),
    );
  }

  @override
  State<ElementOptionsMenu> createState() => _ElementOptionsMenuState();
}

class _ElementOptionsMenuState extends State<ElementOptionsMenu> {
  late TextEditingController _nameCtrl;

  @override
  void initState() {
    super.initState();
    _nameCtrl = TextEditingController(text: widget.element.displayName);
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 24,
        right: 24,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 16,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                '${_typeLabel(widget.element.elementType)} Options',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const Spacer(),
              Text(
                widget.element.id,
                style: TextStyle(fontSize: 10, color: Colors.grey.shade600),
              ),
            ],
          ),
          const SizedBox(height: 16),
          // Rename field
          TextField(
            controller: _nameCtrl,
            decoration: const InputDecoration(
              labelText: 'Display Name',
              border: OutlineInputBorder(),
              isDense: true,
            ),
            onSubmitted: (_) => _rename(),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: _rename,
                  icon: const Icon(Icons.check, size: 18),
                  label: const Text('Rename'),
                ),
              ),
              const SizedBox(width: 12),
              OutlinedButton.icon(
                onPressed: () =>
                    Navigator.pop(context, {'action': 'delete'}),
                icon: const Icon(Icons.delete_outline, size: 18),
                label: const Text('Delete'),
                style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.red.shade300),
              ),
            ],
          ),
        ],
      ),
    );
  }

  void _rename() {
    final name = _nameCtrl.text.trim();
    if (name.isEmpty) return;
    Navigator.pop(context, {'action': 'rename', 'name': name});
  }

  String _typeLabel(String type) => switch (type) {
        'button' => 'Button',
        'slider' => 'Slider',
        'led' => 'LED',
        _ => type,
      };
}
