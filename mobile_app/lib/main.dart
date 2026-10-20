import 'package:flutter/material.dart';

import 'api/arenamatch_api.dart';
import 'api/cliente_api.dart';
import 'api/sessao.dart';
import 'app.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final sessao = await Sessao.carregar(ArenaMatchApi(ClienteApi()));
  runApp(ArenaMatchApp(sessao: sessao));
}
