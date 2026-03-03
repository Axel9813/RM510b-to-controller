sealed class InterfaceElement {
  final String id;
  final String displayName;
  final int gridX;
  final int gridY;
  final int gridW;
  final int gridH;

  const InterfaceElement({
    required this.id,
    required this.displayName,
    required this.gridX,
    required this.gridY,
    required this.gridW,
    required this.gridH,
  });

  String get elementType;

  Map<String, dynamic> toJson() => {
        'type': elementType,        // used by fromJson() for local deserialization
        'elementType': elementType, // used by server hello handler (merge_hello)
        'id': id,
        'displayName': displayName,
        'gridX': gridX,
        'gridY': gridY,
        'gridW': gridW,
        'gridH': gridH,
      };

  static InterfaceElement fromJson(Map<String, dynamic> json) {
    final type = json['type'] as String;
    return switch (type) {
      'button' => ButtonElement.fromJson(json),
      'slider' => SliderElement.fromJson(json),
      'led' => LedElement.fromJson(json),
      _ => throw ArgumentError('Unknown element type: $type'),
    };
  }

  InterfaceElement copyWithPosition({int? gridX, int? gridY});
  InterfaceElement copyWithName(String name);
}

class ButtonElement extends InterfaceElement {
  static const int defaultW = 3;
  static const int defaultH = 2;

  const ButtonElement({
    required super.id,
    required super.displayName,
    required super.gridX,
    required super.gridY,
    super.gridW = defaultW,
    super.gridH = defaultH,
  });

  @override
  String get elementType => 'button';

  factory ButtonElement.fromJson(Map<String, dynamic> json) => ButtonElement(
        id: json['id'] as String,
        displayName: json['displayName'] as String,
        gridX: json['gridX'] as int,
        gridY: json['gridY'] as int,
        gridW: json['gridW'] as int? ?? defaultW,
        gridH: json['gridH'] as int? ?? defaultH,
      );

  @override
  ButtonElement copyWithPosition({int? gridX, int? gridY}) => ButtonElement(
        id: id,
        displayName: displayName,
        gridX: gridX ?? this.gridX,
        gridY: gridY ?? this.gridY,
        gridW: gridW,
        gridH: gridH,
      );

  @override
  ButtonElement copyWithName(String name) => ButtonElement(
        id: id,
        displayName: name,
        gridX: gridX,
        gridY: gridY,
        gridW: gridW,
        gridH: gridH,
      );
}

class SliderElement extends InterfaceElement {
  static const int defaultW = 6;
  static const int defaultH = 2;

  const SliderElement({
    required super.id,
    required super.displayName,
    required super.gridX,
    required super.gridY,
    super.gridW = defaultW,
    super.gridH = defaultH,
  });

  @override
  String get elementType => 'slider';

  factory SliderElement.fromJson(Map<String, dynamic> json) => SliderElement(
        id: json['id'] as String,
        displayName: json['displayName'] as String,
        gridX: json['gridX'] as int,
        gridY: json['gridY'] as int,
        gridW: json['gridW'] as int? ?? defaultW,
        gridH: json['gridH'] as int? ?? defaultH,
      );

  @override
  SliderElement copyWithPosition({int? gridX, int? gridY}) => SliderElement(
        id: id,
        displayName: displayName,
        gridX: gridX ?? this.gridX,
        gridY: gridY ?? this.gridY,
        gridW: gridW,
        gridH: gridH,
      );

  @override
  SliderElement copyWithName(String name) => SliderElement(
        id: id,
        displayName: name,
        gridX: gridX,
        gridY: gridY,
        gridW: gridW,
        gridH: gridH,
      );
}

class LedElement extends InterfaceElement {
  static const int defaultW = 2;
  static const int defaultH = 2;

  final bool currentState;

  const LedElement({
    required super.id,
    required super.displayName,
    required super.gridX,
    required super.gridY,
    super.gridW = defaultW,
    super.gridH = defaultH,
    this.currentState = false,
  });

  @override
  String get elementType => 'led';

  @override
  Map<String, dynamic> toJson() => {
        ...super.toJson(),
        // currentState is runtime-only, not persisted
      };

  factory LedElement.fromJson(Map<String, dynamic> json) => LedElement(
        id: json['id'] as String,
        displayName: json['displayName'] as String,
        gridX: json['gridX'] as int,
        gridY: json['gridY'] as int,
        gridW: json['gridW'] as int? ?? defaultW,
        gridH: json['gridH'] as int? ?? defaultH,
      );

  @override
  LedElement copyWithPosition({int? gridX, int? gridY}) => LedElement(
        id: id,
        displayName: displayName,
        gridX: gridX ?? this.gridX,
        gridY: gridY ?? this.gridY,
        gridW: gridW,
        gridH: gridH,
        currentState: currentState,
      );

  @override
  LedElement copyWithName(String name) => LedElement(
        id: id,
        displayName: name,
        gridX: gridX,
        gridY: gridY,
        gridW: gridW,
        gridH: gridH,
        currentState: currentState,
      );

  LedElement copyWithState(bool state) => LedElement(
        id: id,
        displayName: displayName,
        gridX: gridX,
        gridY: gridY,
        gridW: gridW,
        gridH: gridH,
        currentState: state,
      );
}
