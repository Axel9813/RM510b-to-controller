import 'package:flutter/material.dart';

import '../models/interface_element.dart';

/// A circular LED indicator element. Its state is driven by [element.currentState]
/// which is updated by the server via `element_update` / `elements_full_state`.
class LedElementWidget extends StatelessWidget {
  final LedElement element;
  final double cellSize;
  final bool editMode;
  final VoidCallback? onLongPress;

  const LedElementWidget({
    super.key,
    required this.element,
    required this.cellSize,
    this.editMode = false,
    this.onLongPress,
  });

  @override
  Widget build(BuildContext context) {
    final w = element.gridW * cellSize;
    final h = element.gridH * cellSize;
    final on = element.currentState;
    final ledSize = (cellSize * 0.65).clamp(24.0, 48.0);

    return GestureDetector(
      onLongPress: onLongPress,
      child: Container(
        width: w,
        height: h,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(10),
          color: Colors.blueGrey.shade900,
          border: Border.all(
            color: editMode
                ? Colors.amber.withValues(alpha: 0.8)
                : Colors.blueGrey.shade600,
            width: editMode ? 1.5 : 1,
          ),
        ),
        child: Stack(
          children: [
            Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 150),
                    width: ledSize,
                    height: ledSize,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: on ? Colors.greenAccent : Colors.grey.shade800,
                      boxShadow: on
                          ? [
                              BoxShadow(
                                color: Colors.greenAccent.withValues(alpha: 0.6),
                                blurRadius: 12,
                                spreadRadius: 2,
                              ),
                            ]
                          : [],
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    element.displayName,
                    style: TextStyle(
                      fontSize: 10,
                      color: Colors.grey.shade400,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
            if (editMode)
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
