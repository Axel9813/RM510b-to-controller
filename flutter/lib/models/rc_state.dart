class RcState {
  final int seq;
  final int stickLeftH;
  final int stickLeftV;
  final int stickRightH;
  final int stickRightV;
  final int leftWheel;
  final int rightWheel;
  final bool record;
  final bool shutter;
  final bool fiveDUp;
  final bool fiveDDown;
  final bool fiveDLeft;
  final bool fiveDRight;
  final bool fiveDCenter;
  final int picoBitmask;

  const RcState({
    this.seq = 0,
    this.stickLeftH = 0,
    this.stickLeftV = 0,
    this.stickRightH = 0,
    this.stickRightV = 0,
    this.leftWheel = 0,
    this.rightWheel = 0,
    this.record = false,
    this.shutter = false,
    this.fiveDUp = false,
    this.fiveDDown = false,
    this.fiveDLeft = false,
    this.fiveDRight = false,
    this.fiveDCenter = false,
    this.picoBitmask = 0,
  });

  factory RcState.fromMap(Map<dynamic, dynamic> map) {
    return RcState(
      seq: map['seq'] as int? ?? 0,
      stickLeftH: map['stickLeftH'] as int? ?? 0,
      stickLeftV: map['stickLeftV'] as int? ?? 0,
      stickRightH: map['stickRightH'] as int? ?? 0,
      stickRightV: map['stickRightV'] as int? ?? 0,
      leftWheel: map['leftWheel'] as int? ?? 0,
      rightWheel: map['rightWheel'] as int? ?? 0,
      record: map['record'] as bool? ?? false,
      shutter: map['shutter'] as bool? ?? false,
      fiveDUp: map['fiveDUp'] as bool? ?? false,
      fiveDDown: map['fiveDDown'] as bool? ?? false,
      fiveDLeft: map['fiveDLeft'] as bool? ?? false,
      fiveDRight: map['fiveDRight'] as bool? ?? false,
      fiveDCenter: map['fiveDCenter'] as bool? ?? false,
    );
  }

  Map<String, dynamic> toJson() => {
        'type': 'rc_state',
        'seq': seq,
        'stickLeftH': stickLeftH,
        'stickLeftV': stickLeftV,
        'stickRightH': stickRightH,
        'stickRightV': stickRightV,
        'leftWheel': leftWheel,
        'rightWheel': rightWheel,
        'record': record,
        'shutter': shutter,
        'fiveDUp': fiveDUp,
        'fiveDDown': fiveDDown,
        'fiveDLeft': fiveDLeft,
        'fiveDRight': fiveDRight,
        'fiveDCenter': fiveDCenter,
        'picoBitmask': picoBitmask,
      };

  RcState copyWith({int? picoBitmask}) {
    return RcState(
      seq: seq,
      stickLeftH: stickLeftH,
      stickLeftV: stickLeftV,
      stickRightH: stickRightH,
      stickRightV: stickRightV,
      leftWheel: leftWheel,
      rightWheel: rightWheel,
      record: record,
      shutter: shutter,
      fiveDUp: fiveDUp,
      fiveDDown: fiveDDown,
      fiveDLeft: fiveDLeft,
      fiveDRight: fiveDRight,
      fiveDCenter: fiveDCenter,
      picoBitmask: picoBitmask ?? this.picoBitmask,
    );
  }
}
