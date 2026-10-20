import '../formato.dart';
import '../modelos/carteira.dart';
import '../modelos/inscricao.dart';
import '../modelos/leitura.dart';
import '../modelos/partida.dart';
import '../modelos/usuario.dart';
import 'cliente_api.dart';

/// Resultado do login pelo celular.
typedef Login = ({String token, bool precisaDePerfil});

/// Os endpoints da API Django (/api/) que o app usa.
class ArenaMatchApi {
  ArenaMatchApi(this.cliente);

  final ClienteApi cliente;

  // --- Feed e checkout -----------------------------------------------------------

  /// Partidas abertas que ainda não começaram. [origem]: "arena" ou "pelada".
  Future<List<Partida>> partidas({String? origem, DateTime? dia, int maxPaginas = 3}) async {
    final itens = await _todasAsPaginas('partidas/', {
      'origem': ?origem,
      if (dia != null) 'data': dataIso(dia),
    }, maxPaginas);
    return [for (final item in itens) Partida.fromJson(item)];
  }

  /// Checkout da vaga de linha. No Pix, a inscrição volta com o código copia e cola.
  Future<Inscricao> garantirVaga(String partidaId, {String metodo = 'pix', String posicao = 'linha'}) async {
    final corpo = await cliente.post('partidas/$partidaId/inscricoes/', {
      'posicao': posicao,
      'metodo_pagamento': metodo,
    });
    return Inscricao.fromJson(objeto(corpo));
  }

  Future<List<Inscricao>> minhasInscricoes() async {
    final corpo = await cliente.get('minhas-inscricoes/');
    return [for (final item in resultados(corpo)) Inscricao.fromJson(item)];
  }

  // --- Login pelo celular e perfil -----------------------------------------------

  /// Envia o código por SMS. Em desenvolvimento, devolve o código (nulo em produção).
  Future<String?> solicitarCodigo(String telefone) async {
    final corpo = objeto(await cliente.post('auth/celular/', {'telefone': telefone}));
    return corpo['codigo'] as String?;
  }

  Future<Login> verificarCodigo(String telefone, String codigo, {String nome = ''}) async {
    final corpo = objeto(
      await cliente.post('auth/celular/verificar/', {'telefone': telefone, 'codigo': codigo, 'nome': nome}),
    );
    return (token: texto(corpo['token']), precisaDePerfil: corpo['precisa_de_perfil'] == true);
  }

  Future<Usuario> eu() async => Usuario.fromJson(objeto(await cliente.get('me/')));

  /// Questionário de nível (o servidor calcula o nível de 1 a 5).
  Future<void> salvarQuestionario({
    required String posicao,
    required int autoavaliacao,
    required String frequencia,
    required String experiencia,
  }) => cliente.put('perfil-jogador/', {
    'posicao': posicao,
    'joga_no_gol': posicao == 'goleiro',
    'autoavaliacao': autoavaliacao,
    'frequencia': frequencia,
    'experiencia': experiencia,
  });

  // --- Pelada de grupo (C2C) -----------------------------------------------------

  Future<List<PeladaDoOrganizador>> minhasPeladas() async {
    final itens = await _todasAsPaginas('peladas/', const {}, 3);
    return [for (final item in itens) PeladaDoOrganizador.fromJson(item)];
  }

  Future<PeladaDoOrganizador> criarPelada({
    required int quadra,
    required DateTime dia,
    required String horaInicio,
    required int vagas,
    required double valorPorVaga,
    String titulo = '',
    String nivel = 'aberta',
  }) async {
    final corpo = await cliente.post('peladas/', {
      'quadra': quadra,
      'dia': dataIso(dia),
      'hora_inicio': horaInicio,
      'vagas_linha': vagas,
      'valor_por_vaga': valorPorVaga.toStringAsFixed(2),
      'titulo': titulo,
      'nivel': nivel,
    });
    return PeladaDoOrganizador.fromJson(objeto(corpo));
  }

  /// Cancela as vagas da pelada. Devolve quantos jogadores foram reembolsados.
  Future<int> cancelarPelada(String id) async =>
      inteiro(objeto(await cliente.post('peladas/$id/cancelar/'))['reembolsados']);

  /// Quadras das arenas parceiras (onde o grupo joga).
  Future<List<Quadra>> quadras() async => Quadra.daListaDeArenas(await _todasAsPaginas('arenas/', const {}, 5));

  Future<CarteiraOrganizador> carteira() async =>
      CarteiraOrganizador.fromJson(objeto(await cliente.get('organizador/carteira/')));

  Future<void> salvarChavePix(String tipo, String chave) =>
      cliente.put('organizador/chave-pix/', {'tipo_chave_pix': tipo, 'chave_pix': chave});

  /// Saca todo o saldo disponível via Pix. Devolve o valor sacado.
  Future<double> sacar() async => dinheiro(objeto(await cliente.post('organizador/saques/'))['valor']);

  Future<List<Json>> _todasAsPaginas(String caminho, Map<String, String> parametros, int maxPaginas) async {
    final itens = <Json>[];
    for (var pagina = 1; pagina <= maxPaginas; pagina++) {
      final corpo = await cliente.get(caminho, parametros: {...parametros, if (pagina > 1) 'page': '$pagina'});
      itens.addAll(resultados(corpo));
      if (corpo is! Map<String, dynamic> || corpo['next'] == null) break;
    }
    return itens;
  }
}
