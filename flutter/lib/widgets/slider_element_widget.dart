import 'package:flutter/material.dart';

import '../models/interface_element.dart';

/// A horizontal slider element rendered on the interface canvas.
/// In view mode it emits [onChanged] (0.0–1.0); in edit mode it is a drag target.
class SliderElementWidget extends StatefulWidget {
  final SliderElement element;
  final double cellSize;
  final bool editMode;
  final ValueChanged<double>? onChanged; // value 0.0–1.0
  final VoidCallback? onLongPress;

  const SliderElementWidget({
    super.key,
    required this.element,
    required this.cellSize,
    this.editMode = false,
    this.onChanged,
    this.onLongPress,
  });

  @override
  State<SliderElementWidget> createState() => _SliderElementWidgetState();
}

class _SliderElementWidgetState extends State<SliderElementWidget> {
  double _value = 0.5;

  double get _trackPadH => 24.0;
  double get _trackPadV => 16.0;

  @override
  Widget build(BuildContext context) {
    final w = widget.element.gridW * widget.cellSize;
    final h = widget.element.gridH * widget.cellSize;

    return GestureDetector(
      onLongPress: widget.onLongPress,
      onHorizontalDragUpdate: widget.editMode
          ? null
          : (details) {
              final trackW = w - _trackPadH * 2;
              final newValue =
                  (_value + details.delta.dx / trackW).clamp(0.0, 1.0);
              setState(() => _value = newValue);
              widget.onChanged?.call(newValue);
            },
      child: Container(
        width: w,
        height: h,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(10),
          color: Colors.blueGrey.shade800,
          border: Border.all(
            color: widget.editMode
                ? Colors.amber.withValues(alpha: 0.8)
                : Colors.blueGrey.shade500,
            width: widget.editMode ? 1.5 : 1,
          ),
        ),
        child: Stack(
          children: [
            // Label
            Positioned(
              top: 6,
              left: 10,
              right: 10,
              child: Text(
                widget.element.displayName,
                style: TextStyle(
                  fontSize: 11,
                  color: Colors.grey.shade400,
                ),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            // Track
            Positioned(
              left: _trackPadH,
              right: _trackPadH,
              bottom: _trackPadV,
              child: _TrackPainter(value: _value, editMode: widget.editMode),
            ),
            if (widget.editMode)
              Positioned(
                top: 2,
                right: 2,
                child: Icon(Icons.drag_indicator,
                    size: 14, color: Colors.amber.withValues(alpha: 0.7)),
              ),
          ],
        ),
      ),
    );
  }
}

class _TrackPainter extends StatelessWidget {
  final double value;
  final bool editMode;
  const _TrackPainter({required this.value, required this.editMode});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, constraints) {
      final w = constraints.maxWidth;
      return SizedBox(
        height: 10,
        child: Stack(
          children: [
            // Background track
            Positioned.fill(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(5),
                  color: Colors.blueGrey.shade600,
                ),
              ),
            ),
            // Fill
            Positioned(
              left: 0,
              top: 0,
              bottom: 0,
              width: w * value,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(5),
                  color: editMode ? Colors.amber.shade600 : Colors.blueAccent,
                ),
              ),
            ),
            // Thumb
            Positioned(
              left: (w * value - 6).clamp(0, w - 12),
              top: -3,
              child: Container(
                width: 16,
                height: 16,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: editMode ? Colors.amber : Colors.white,
                  boxShadow: [
                    BoxShadow(
                        color: Colors.black.withValues(alpha: 0.5),
                        blurRadius: 3)
                  ],
                ),
              ),
            ),
          ],
        ),
      );
    });
  }
}
