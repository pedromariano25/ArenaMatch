import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../modelos/usuario.dart';
import 'arenamatch_api.dart';
import 'cliente_api.dart';

/// Quem está usando o app: o token (guardado no aparelho) e os dados do usuário.
class Sessao extends ChangeNotifier {
  Sessao(this.api, this._preferencias);

  static const _chaveToken = 'arenamatch.token';

  final ArenaMatchApi api;
  final SharedPreferences _preferencias;
  Usuario? usuario;

  bool get logado => api.cliente.token != null;

  /// Abre a sessão salva no aparelho. Token recusado pelo servidor é descartado.
  static Future<Sessao> carregar(ArenaMatchApi api) async {
    final sessao = Sessao(api, await SharedPreferences.getInstance());
    api.cliente.token = sessao._preferencias.getString(_chaveToken);
    if (sessao.logado) {
      try {
        sessao.usuario = await api.eu();
      } on ApiErro catch (erro) {
        if (erro.naoAutenticado) await sessao.sair();
      }
    }
    return sessao;
  }

  Future<void> entrar(String token) async {
    api.cliente.token = token;
    await _preferencias.setString(_chaveToken, token);
    usuario = await api.eu();
    notifyListeners();
  }

  Future<void> atualizarUsuario() async {
    usuario = await api.eu();
    notifyListeners();
  }

  Future<void> sair() async {
    api.cliente.token = null;
    usuario = null;
    await _preferencias.remove(_chaveToken);
    notifyListeners();
  }
}

/// Dá acesso à [Sessao] em qualquer tela e reconstrói quem depende dela ao entrar ou sair.
class EscopoSessao extends InheritedNotifier<Sessao> {
  const EscopoSessao({super.key, required Sessao sessao, required super.child}) : super(notifier: sessao);

  static Sessao of(BuildContext context, {bool ouvir = true}) {
    final escopo = ouvir
        ? context.dependOnInheritedWidgetOfExactType<EscopoSessao>()
        : context.getInheritedWidgetOfExactType<EscopoSessao>();
    assert(escopo != null, 'EscopoSessao não encontrado acima deste widget.');
    return escopo!.notifier!;
  }
}
