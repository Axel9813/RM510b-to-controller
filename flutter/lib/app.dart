import 'package:flutter/material.dart';

import 'screens/main_screen.dart';

class RcControllerApp extends StatelessWidget {
  const RcControllerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'RC Controller',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        colorSchemeSeed: Colors.blueGrey,
        useMaterial3: true,
      ),
      home: const MainScreen(),
    );
  }
}
