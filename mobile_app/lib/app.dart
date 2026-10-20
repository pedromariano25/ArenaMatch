import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'api/sessao.dart';
import 'tema.dart';
import 'telas/tela_jogos.dart';
import 'telas/tela_minhas_peladas.dart';
import 'telas/tela_perfil.dart';

class ArenaMatchApp extends StatelessWidget {
  const ArenaMatchApp({super.key, required this.sessao});

  final Sessao sessao;

  @override
  Widget build(BuildContext context) {
    return EscopoSessao(
      sessao: sessao,
      child: MaterialApp(
        title: 'ArenaMatch',
        debugShowCheckedModeBanner: false,
        theme: temaArenaMatch(),
        locale: const Locale('pt', 'BR'),
        supportedLocales: const [Locale('pt', 'BR')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        home: const Inicio(),
      ),
    );
  }
}

/// As três abas do app: o feed de jogos, as peladas que eu organizo e o perfil.
class Inicio extends StatefulWidget {
  const Inicio({super.key});

  @override
  State<Inicio> createState() => _InicioState();
}

class _InicioState extends State<Inicio> {
  var _aba = 0;

  static const _telas = [TelaJogos(), TelaMinhasPeladas(), TelaPerfil()];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(index: _aba, children: _telas),
      bottomNavigationBar: DecoratedBox(
        decoration: const BoxDecoration(
          border: Border(top: BorderSide(color: Cores.borda)),
        ),
        child: BottomNavigationBar(
          currentIndex: _aba,
          onTap: (aba) => setState(() => _aba = aba),
          items: const [
            BottomNavigationBarItem(
              icon: Icon(Icons.sports_soccer_outlined),
              activeIcon: Icon(Icons.sports_soccer),
              label: 'Jogos',
            ),
            BottomNavigationBarItem(
              icon: Icon(Icons.groups_outlined),
              activeIcon: Icon(Icons.groups),
              label: 'Minhas Peladas',
            ),
            BottomNavigationBarItem(icon: Icon(Icons.person_outline), activeIcon: Icon(Icons.person), label: 'Perfil'),
          ],
        ),
      ),
    );
  }
}
