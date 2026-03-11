class PicoState {
  final int bitmask;
  final int extraBitmask;
  final int analogX;
  final int analogY;

  const PicoState({
    this.bitmask = 0,
    this.extraBitmask = 0,
    this.analogX = 0,
    this.analogY = 0,
  });

  // ── Core button getters (bits 0-9 of bitmask) ──

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

  // ── Extra button getters (bits 0-8 of extraBitmask) ──

  bool get joyClick => (extraBitmask & 0x01) != 0;
  bool get hatPush => (extraBitmask & 0x02) != 0;
  bool get hatLeft => (extraBitmask & 0x04) != 0;
  bool get hatUp => (extraBitmask & 0x08) != 0;
  bool get hatDown => (extraBitmask & 0x10) != 0;
  bool get hatRight => (extraBitmask & 0x20) != 0;
  bool get switch2Up => (extraBitmask & 0x40) != 0;
  bool get switch2Down => (extraBitmask & 0x80) != 0;
  bool get redBtn => (extraBitmask & 0x100) != 0;

  /// Second 3-position switch: 1 (up), 2 (neutral), 3 (down).
  int get switch2Position {
    if (switch2Up) return 1;
    if (switch2Down) return 3;
    return 2;
  }
}
