import 'package:flutter/material.dart';

import '../models/app_layout.dart';
import '../models/interface_element.dart';
import 'button_element_widget.dart';
import 'slider_element_widget.dart';
import 'led_element_widget.dart';
import 'element_picker.dart';
import 'element_options_menu.dart';
import 'grid_painter.dart';

/// Overlay that renders all interface elements onto the canvas.
/// In edit mode the grid is visible, elements can be dragged and long-pressed
/// to rename/delete. A FAB opens [ElementPicker] to add new elements.
///
/// [onLayoutChanged] is called whenever the layout mutates (add/move/rename/delete).
/// [onElementPress] / [onElementRelease] are called in view mode for buttons.
/// [onSliderChange] is called in view mode for sliders.
class BuilderOverlay extends StatefulWidget {
  final AppLayout layout;
  final bool editMode;
  final ValueChanged<AppLayout> onLayoutChanged;
  final void Function(String id)? onElementPress;
  final void Function(String id)? onElementRelease;
  final void Function(String id, double value)? onSliderChange;

  const BuilderOverlay({
    super.key,
    required this.layout,
    required this.editMode,
    required this.onLayoutChanged,
    this.onElementPress,
    this.onElementRelease,
    this.onSliderChange,
  });

  @override
  State<BuilderOverlay> createState() => _BuilderOverlayState();
}

class _BuilderOverlayState extends State<BuilderOverlay> {
  String? _draggingId;
  // _dragStartLocal kept for potential future use (e.g. within-element offset)
  // ignore: unused_field
  Offset _dragStartLocal = Offset.zero;
  int _dragStartGridX = 0;
  int _dragStartGridY = 0;
  // Live drag offset in pixels (applied on top of grid position while dragging)
  Offset _dragDelta = Offset.zero;

  double get _cellSize {
    final mq = MediaQuery.of(context);
    final size = mq.size;
    return (size.shortestSide / 8).clamp(40.0, 80.0);
  }

  @override
  Widget build(BuildContext context) {
    final cs = _cellSize;

    return Stack(
      children: [
        // Grid backdrop (edit mode only)
        if (widget.editMode)
          Positioned.fill(
            child: CustomPaint(painter: GridPainter(cellSize: cs)),
          ),

        // Render all elements
        ...widget.layout.elements.map((el) => _buildElement(el, cs)),

        // Add FAB (edit mode only)
        if (widget.editMode)
          Positioned(
            bottom: 20,
            right: 20,
            child: FloatingActionButton(
              heroTag: 'add_element_fab',
              onPressed: _addElement,
              child: const Icon(Icons.add),
            ),
          ),
      ],
    );
  }

  Widget _buildElement(InterfaceElement el, double cs) {
    final isDragging = _draggingId == el.id && widget.editMode;
    // Position: if dragging use live delta, else snap to grid
    final left = el.gridX * cs + (isDragging ? _dragDelta.dx : 0);
    final top = el.gridY * cs + (isDragging ? _dragDelta.dy : 0);

    Widget child = _elementWidget(el, cs);

    if (widget.editMode) {
      child = GestureDetector(
        onPanStart: (d) {
          setState(() {
            _draggingId = el.id;
            _dragStartLocal = d.localPosition;
            _dragStartGridX = el.gridX;
            _dragStartGridY = el.gridY;
            _dragDelta = Offset.zero;
          });
        },
        onPanUpdate: (d) {
          setState(() {
            _dragDelta += d.delta;
          });
        },
        onPanEnd: (_) => _commitDrag(el, cs),
        child: child,
      );
    }

    return AnimatedPositioned(
      key: ValueKey(el.id),
      duration: isDragging
          ? Duration.zero
          : const Duration(milliseconds: 150),
      left: left,
      top: top,
      child: child,
    );
  }

  Widget _elementWidget(InterfaceElement el, double cs) {
    return switch (el) {
      ButtonElement b => ButtonElementWidget(
          element: b,
          cellSize: cs,
          editMode: widget.editMode,
          onPress: () => widget.onElementPress?.call(el.id),
          onRelease: () => widget.onElementRelease?.call(el.id),
          onLongPress: widget.editMode ? () => _openOptions(el) : null,
        ),
      SliderElement s => SliderElementWidget(
          element: s,
          cellSize: cs,
          editMode: widget.editMode,
          onChanged: (v) => widget.onSliderChange?.call(el.id, v),
          onLongPress: widget.editMode ? () => _openOptions(el) : null,
        ),
      LedElement l => LedElementWidget(
          element: l,
          cellSize: cs,
          editMode: widget.editMode,
          onLongPress: widget.editMode ? () => _openOptions(el) : null,
        ),
    };
  }

  void _commitDrag(InterfaceElement el, double cs) {
    if (_draggingId != el.id) return;
    // Convert pixel delta to grid cells
    final newX = (_dragStartGridX + _dragDelta.dx / cs).round();
    final newY = (_dragStartGridY + _dragDelta.dy / cs).round();
    final clampedX = newX.clamp(0, 31);
    final clampedY = newY.clamp(0, 31);

    setState(() {
      _draggingId = null;
      _dragDelta = Offset.zero;
    });

    if (clampedX != el.gridX || clampedY != el.gridY) {
      final updated = el.copyWithPosition(gridX: clampedX, gridY: clampedY);
      widget.onLayoutChanged(
          widget.layout.updateElement(el.id, updated));
    }
  }

  Future<void> _openOptions(InterfaceElement el) async {
    final result = await ElementOptionsMenu.show(context, el);
    if (result == null) return;

    switch (result['action'] as String) {
      case 'rename':
        final name = result['name'] as String;
        widget.onLayoutChanged(
            widget.layout.updateElement(el.id, el.copyWithName(name)));
      case 'delete':
        widget.onLayoutChanged(widget.layout.removeElement(el.id));
    }
  }

  Future<void> _addElement() async {
    final type = await ElementPicker.show(context);
    if (type == null) return;

    final id = '${type.substring(0, 3)}_${DateTime.now().millisecondsSinceEpoch}';
    final cs = _cellSize;
    // Find a free top-left position heuristically
    final pos = _findFreePosition(type, cs);

    final InterfaceElement el = switch (type) {
      'button' => ButtonElement(
          id: id,
          displayName: 'Button',
          gridX: pos.$1,
          gridY: pos.$2,
        ),
      'slider' => SliderElement(
          id: id,
          displayName: 'Slider',
          gridX: pos.$1,
          gridY: pos.$2,
        ),
      'led' => LedElement(
          id: id,
          displayName: 'LED',
          gridX: pos.$1,
          gridY: pos.$2,
        ),
      _ => throw ArgumentError('Unknown type: $type'),
    };

    widget.onLayoutChanged(widget.layout.addElement(el));
  }

  /// Returns (gridX, gridY) for a new element, trying to avoid overlap.
  (int, int) _findFreePosition(String type, double cs) {
    final (int w, int h) = switch (type) {
      'button' => (ButtonElement.defaultW, ButtonElement.defaultH),
      'slider' => (SliderElement.defaultW, SliderElement.defaultH),
      _ => (LedElement.defaultW, LedElement.defaultH),
    };

    final mq = MediaQuery.of(context);
    final maxCols = (mq.size.width / cs).floor();
    final maxRows = (mq.size.height / cs).floor();

    // Try each row, each column
    for (int row = 0; row + h <= maxRows; row++) {
      for (int col = 0; col + w <= maxCols; col++) {
        if (!_overlaps(col, row, w, h)) return (col, row);
      }
    }
    return (0, 0); // fallback
  }

  bool _overlaps(int x, int y, int w, int h) {
    for (final el in widget.layout.elements) {
      final r1Left = x;
      final r1Right = x + w;
      final r1Top = y;
      final r1Bottom = y + h;
      final r2Left = el.gridX;
      final r2Right = el.gridX + el.gridW;
      final r2Top = el.gridY;
      final r2Bottom = el.gridY + el.gridH;
      if (r1Left < r2Right &&
          r1Right > r2Left &&
          r1Top < r2Bottom &&
          r1Bottom > r2Top) {
        return true;
      }
    }
    return false;
  }
}
