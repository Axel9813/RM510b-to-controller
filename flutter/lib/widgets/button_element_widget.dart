import 'package:flutter/material.dart';

import '../models/interface_element.dart';

/// A tappable button element rendered on the interface canvas.
/// In view mode it fires [onPress]/[onRelease]; in edit mode it is draggable.
class ButtonElementWidget extends StatefulWidget {
  final ButtonElement element;
  final double cellSize;
  final bool editMode;
  final VoidCallback? onPress;
  final VoidCallback? onRelease;
  final VoidCallback? onLongPress; // opens options in edit mode

  const ButtonElementWidget({
    super.key,
    required this.element,
    required this.cellSize,
    this.editMode = false,
    this.onPress,
    this.onRelease,
    this.onLongPress,
  });

  @override
  State<ButtonElementWidget> createState() => _ButtonElementWidgetState();
}

class _ButtonElementWidgetState extends State<ButtonElementWidget> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    final w = widget.element.gridW * widget.cellSize;
    final h = widget.element.gridH * widget.cellSize;

    Widget child = GestureDetector(
      onTapDown: widget.editMode
          ? null
          : (_) {
              setState(() => _pressed = true);
              widget.onPress?.call();
            },
      onTapUp: widget.editMode
          ? null
          : (_) {
              setState(() => _pressed = false);
              widget.onRelease?.call();
            },
      onTapCancel: widget.editMode
          ? null
          : () {
              setState(() => _pressed = false);
              widget.onRelease?.call();
            },
      onLongPress: widget.onLongPress,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 80),
        width: w,
        height: h,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(10),
          color: _pressed
              ? Colors.blueGrey.shade300
              : Colors.blueGrey.shade700,
          border: Border.all(
            color: widget.editMode
                ? Colors.amber.withValues(alpha: 0.8)
                : Colors.blueGrey.shade400,
            width: widget.editMode ? 1.5 : 1,
          ),
          boxShadow: _pressed
              ? []
              : [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.4),
                    blurRadius: 4,
                    offset: const Offset(0, 2),
                  ),
                ],
        ),
        child: Center(
          child: Text(
            widget.element.displayName,
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: Colors.white,
            ),
            textAlign: TextAlign.center,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ),
    );

    if (widget.editMode) {
      child = Stack(
        children: [
          child,
          Positioned(
            top: 2,
            right: 2,
            child: Icon(Icons.drag_indicator,
                size: 14, color: Colors.amber.withValues(alpha: 0.7)),
          ),
        ],
      );
    }

    return SizedBox(width: w, height: h, child: child);
  }
}
