import 'package:arenamatch/api/arenamatch_api.dart';
import 'package:arenamatch/api/cliente_api.dart';
import 'package:arenamatch/api/sessao.dart';
import 'package:arenamatch/app.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'dados.dart';

Future<void> abrirApp(WidgetTester tester, Map<String, Object> respostas) async {
  SharedPreferences.setMockInitialValues({});
  final api = ArenaMatchApi(ClienteApi(cliente: clienteFalso(respostas), baseUrl: 'http://teste/api/'));
  final sessao = await Sessao.carregar(api);
  await tester.pumpWidget(ArenaMatchApp(sessao: sessao));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('abre no feed com as três abas e o botão Garantir vaga', (tester) async {
    final amanha = DateTime.now().add(const Duration(days: 1));
    final data = '${amanha.year}-${'${amanha.month}'.padLeft(2, '0')}-${'${amanha.day}'.padLeft(2, '0')}';
    await abrirApp(tester, {
      '/api/partidas/': pagina([
        partidaJson(data: data),
        partidaJson(id: 'p2', origem: 'pelada', data: data, hora: '21:00'),
      ]),
    });

    for (final aba in ['Jogos', 'Minhas Peladas', 'Perfil']) {
      expect(find.descendant(of: find.byType(BottomNavigationBar), matching: find.text(aba)), findsOneWidget);
    }
    expect(find.text('Bora jogar?'), findsOneWidget);
    expect(find.text('Amanhã'), findsWidgets);
    expect(find.text('R\$ 23,95'), findsNWidgets(2));
    expect(find.text('Pelada de grupo · por Ana S.'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Garantir vaga'), findsNWidgets(2));
  });

  testWidgets('sem login, Minhas Peladas e Perfil pedem para entrar', (tester) async {
    await abrirApp(tester, {'/api/partidas/': pagina([])});
    expect(find.text('Nenhum jogo com vaga'), findsOneWidget);

    await tester.tap(find.text('Minhas Peladas'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(FilledButton, 'Entrar para começar'), findsOneWidget);

    await tester.tap(find.text('Perfil'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(FilledButton, 'Entrar'), findsOneWidget);
  });

  testWidgets('Garantir vaga sem login abre a tela do celular', (tester) async {
    await abrirApp(tester, {
      '/api/partidas/': pagina([partidaJson()]),
    });
    await tester.tap(find.widgetWithText(FilledButton, 'Garantir vaga'));
    await tester.pumpAndSettle();
    expect(find.text('Entre com o celular'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Receber código'), findsOneWidget);
  });
}
