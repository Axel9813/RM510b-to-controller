import 'package:shared_preferences/shared_preferences.dart';

import '../models/app_layout.dart';

class LayoutStorageService {
  static const _key = 'app_layout';

  Future<AppLayout> load() async {
    final prefs = await SharedPreferences.getInstance();
    final json = prefs.getString(_key);
    if (json == null || json.isEmpty) return const AppLayout();
    try {
      return AppLayout.fromJsonString(json);
    } catch (_) {
      return const AppLayout();
    }
  }

  Future<void> save(AppLayout layout) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, layout.toJsonString());
  }
}
