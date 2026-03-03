import 'package:flutter_test/flutter_test.dart';

import 'package:rc_to_controller/app.dart';

void main() {
  testWidgets('App builds without error', (WidgetTester tester) async {
    await tester.pumpWidget(const RcControllerApp());
  });
}
