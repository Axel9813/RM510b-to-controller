import 'package:flutter/material.dart';

/// Paints a subtle dot-grid backdrop for the interface builder canvas.
class GridPainter extends CustomPainter {
  final double cellSize;
  final Color dotColor;

  const GridPainter({
    required this.cellSize,
    this.dotColor = const Color(0x33FFFFFF),
  });

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = dotColor
      ..strokeWidth = 1.5
      ..strokeCap = StrokeCap.round;

    final cols = (size.width / cellSize).ceil() + 1;
    final rows = (size.height / cellSize).ceil() + 1;

    for (int row = 0; row <= rows; row++) {
      for (int col = 0; col <= cols; col++) {
        canvas.drawCircle(
          Offset(col * cellSize, row * cellSize),
          1.5,
          paint,
        );
      }
    }
  }

  @override
  bool shouldRepaint(GridPainter old) =>
      old.cellSize != cellSize || old.dotColor != dotColor;
}
