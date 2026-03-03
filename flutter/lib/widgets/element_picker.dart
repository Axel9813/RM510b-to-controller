import 'package:flutter/material.dart';

/// Bottom sheet that lets the user pick which type of element to add.
class ElementPicker extends StatelessWidget {
  const ElementPicker({super.key});

  /// Show the picker and return one of: `'button'`, `'slider'`, `'led'`, or null.
  static Future<String?> show(BuildContext context) {
    return showModalBottomSheet<String>(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (_) => const ElementPicker(),
    );
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Add Element',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                _PickerItem(
                  icon: Icons.smart_button,
                  label: 'Button',
                  color: Colors.blueGrey.shade400,
                  onTap: () => Navigator.pop(context, 'button'),
                ),
                _PickerItem(
                  icon: Icons.linear_scale,
                  label: 'Slider',
                  color: Colors.blueAccent.shade200,
                  onTap: () => Navigator.pop(context, 'slider'),
                ),
                _PickerItem(
                  icon: Icons.circle,
                  label: 'LED',
                  color: Colors.greenAccent.shade400,
                  onTap: () => Navigator.pop(context, 'led'),
                ),
              ],
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }
}

class _PickerItem extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  const _PickerItem({
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: onTap,
      child: Container(
        width: 90,
        padding: const EdgeInsets.symmetric(vertical: 16),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          color: Colors.blueGrey.shade800,
          border: Border.all(color: Colors.blueGrey.shade600),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, color: color, size: 32),
            const SizedBox(height: 8),
            Text(label, style: const TextStyle(fontSize: 13)),
          ],
        ),
      ),
    );
  }
}
