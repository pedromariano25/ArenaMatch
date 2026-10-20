import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config.dart';

/// Erro devolvido pela API (HTTP 4xx/5xx) ou falta de conexão, com a mensagem pronta para a tela.
class ApiErro implements Exception {
  ApiErro(this.mensagem, {this.status, this.campos = const {}});

  final String mensagem;
  final int? status;

  /// Erros por campo, como o DRF devolve: {"telefone": ["Informe o celular com DDD."]}.
  final Map<String, List<String>> campos;

  bool get naoAutenticado => status == 401;

  /// Lê o corpo de erro do DRF: {"detail": "..."}, {"campo": ["..."]} ou {"non_field_errors": [...]}.
  factory ApiErro.daResposta(http.Response resposta) {
    final campos = <String, List<String>>{};
    String? detalhe;
    try {
      final corpo = jsonDecode(utf8.decode(resposta.bodyBytes));
      if (corpo is Map<String, dynamic>) {
        for (final MapEntry(:key, :value) in corpo.entries) {
          if (key == 'detail') {
            detalhe = '$value';
          } else if (value is List) {
            campos[key] = [for (final item in value) '$item'];
          } else {
            campos[key] = ['$value'];
          }
        }
      } else if (corpo is List && corpo.isNotEmpty) {
        detalhe = '${corpo.first}';
      }
    } on FormatException {
      // Corpo que não é JSON (página de erro do servidor): fica a mensagem genérica.
    }
    final mensagem =
        detalhe ??
        campos['non_field_errors']?.join(' ') ??
        (campos.isNotEmpty
            ? campos.values.first.join(' ')
            : 'Algo deu errado (${resposta.statusCode}). Tente de novo.');
    return ApiErro(mensagem, status: resposta.statusCode, campos: campos);
  }

  @override
  String toString() => mensagem;
}

/// Cliente HTTP da API Django (/api/), com o token de acesso no cabeçalho.
///
/// O [http.Client] é injetável: nos testes entra um MockClient.
class ClienteApi {
  ClienteApi({http.Client? cliente, String baseUrl = apiUrl, this.token})
    : _cliente = cliente ?? http.Client(),
      _base = Uri.parse(baseUrl.endsWith('/') ? baseUrl : '$baseUrl/');

  final http.Client _cliente;
  final Uri _base;
  String? token;

  bool get autenticado => token != null;

  Uri url(String caminho, [Map<String, String>? parametros]) {
    final destino = _base.resolve(caminho);
    if (parametros == null || parametros.isEmpty) return destino;
    return destino.replace(queryParameters: {...destino.queryParameters, ...parametros});
  }

  Map<String, String> get _cabecalhos => {
    'Accept': 'application/json',
    'Content-Type': 'application/json; charset=utf-8',
    if (token != null) 'Authorization': 'Token $token',
  };

  Future<dynamic> get(String caminho, {Map<String, String>? parametros}) =>
      _enviar(() => _cliente.get(url(caminho, parametros), headers: _cabecalhos));

  Future<dynamic> post(String caminho, [Map<String, dynamic>? corpo]) =>
      _enviar(() => _cliente.post(url(caminho), headers: _cabecalhos, body: jsonEncode(corpo ?? {})));

  Future<dynamic> put(String caminho, Map<String, dynamic> corpo) =>
      _enviar(() => _cliente.put(url(caminho), headers: _cabecalhos, body: jsonEncode(corpo)));

  Future<dynamic> delete(String caminho) => _enviar(() => _cliente.delete(url(caminho), headers: _cabecalhos));

  Future<dynamic> _enviar(Future<http.Response> Function() requisicao) async {
    final http.Response resposta;
    try {
      resposta = await requisicao().timeout(const Duration(seconds: 20));
    } on Exception {
      throw ApiErro('Sem conexão com o ArenaMatch. Confira a internet e tente de novo.');
    }
    if (resposta.statusCode >= 400) throw ApiErro.daResposta(resposta);
    if (resposta.bodyBytes.isEmpty) return null;
    return jsonDecode(utf8.decode(resposta.bodyBytes));
  }
}
