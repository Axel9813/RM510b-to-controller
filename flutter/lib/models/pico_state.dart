class PicoState {
  final int bitmask;

  const PicoState({this.bitmask = 0});

  bool get c1 => (bitmask & 0x01) != 0;
  bool get c2 => (bitmask & 0x02) != 0;
  bool get shutterHalf => (bitmask & 0x04) != 0;
  bool get pause => (bitmask & 0x08) != 0;
  bool get returnToHome => (bitmask & 0x10) != 0;
  bool get circle => (bitmask & 0x80) != 0;
  bool get arrow => (bitmask & 0x100) != 0;

  /// 3-position switch: 1, 2, or 3.
  /// Bit 5 = pos1 (pin 1 shorted), bit 6 = pos3 (pin 2 shorted).
  /// Neither = pos2.
  int get switchPosition {
    final pos1 = (bitmask & 0x20) != 0;
    final pos3 = (bitmask & 0x40) != 0;
    if (pos1) return 1;
    if (pos3) return 3;
    return 2;
  }
}
