import 'dart:convert';

import 'interface_element.dart';

class AppLayout {
  final List<InterfaceElement> elements;

  const AppLayout({this.elements = const []});

  String toJsonString() {
    final list = elements.map((e) => e.toJson()).toList();
    return jsonEncode(list);
  }

  factory AppLayout.fromJsonString(String json) {
    final list = jsonDecode(json) as List<dynamic>;
    final elements = list
        .map((e) => InterfaceElement.fromJson(e as Map<String, dynamic>))
        .toList();
    return AppLayout(elements: elements);
  }

  AppLayout addElement(InterfaceElement element) {
    return AppLayout(elements: [...elements, element]);
  }

  AppLayout removeElement(String id) {
    return AppLayout(elements: elements.where((e) => e.id != id).toList());
  }

  AppLayout updateElement(String id, InterfaceElement updated) {
    return AppLayout(
      elements: elements.map((e) => e.id == id ? updated : e).toList(),
    );
  }
}
