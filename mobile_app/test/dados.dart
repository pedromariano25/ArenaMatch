// Respostas da API Django usadas nos testes (mesmo formato dos serializers do DRF).
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> partidaJson({
  String id = 'p1',
  String origem = 'arena',
  String data = '2026-10-21',
  String hora = '19:00',
  int vagasDisponiveis = 3,
  String status = 'aberta',
}) => {
  'id': id,
  'url': 'http://teste/api/partidas/$id/',
  'origem': origem,
  'titulo': origem == 'pelada' ? 'Pelada da Firma' : '',
  'organizador': origem == 'pelada' ? 'Ana S.' : null,
  'arena': {
    'id': 'a1',
    'nome': 'Arena Gol de Placa',
    'slug': 'arena-gol-de-placa',
    'endereco_completo': 'Vila Madalena, São Paulo - SP',
    'telefone_contato': '',
  },
  'quadra': {
    'id': 7,
    'nome_ou_numero': 'Quadra 1',
    'tipo_piso': 'sintetico',
    'tipo_piso_display': 'Sintético',
    'capacidade_padrao': 12,
  },
  'data': data,
  'hora_inicio': hora,
  'hora_fim': '20:00',
  'nivel_competitividade': 'intermediario',
  'nivel_display': 'Intermediário',
  'vagas_totais': 12,
  'vagas_linha': 10,
  'vagas_goleiro': 2,
  'vagas_disponiveis': vagasDisponiveis,
  'vagas_ocupadas': 12 - vagasDisponiveis,
  'precos': {'linha_pix': '23.95', 'linha_cartao': '25.15', 'goleiro': '0.00', 'goleiro_cartao': '0.00'},
  'minimo_jogadores': 7,
  'jogadores_confirmados': 9,
  'jogo_confirmado': true,
  'status': status,
  'status_display': 'Aberta',
  'aceita_inscricoes': status == 'aberta',
};

Map<String, dynamic> pagina(List<Map<String, dynamic>> itens, {String? proxima}) => {
  'count': itens.length,
  'next': proxima,
  'previous': null,
  'results': itens,
};

/// Cliente HTTP falso: cada caminho (ex.: "/api/partidas/") devolve um JSON fixo.
MockClient clienteFalso(Map<String, Object> respostas, {List<http.Request>? recebidas}) =>
    MockClient((requisicao) async {
      recebidas?.add(requisicao);
      final corpo = respostas[requisicao.url.path];
      if (corpo == null) return http.Response('{"detail": "Não encontrado."}', 404);
      return http.Response.bytes(utf8.encode(jsonEncode(corpo)), 200, headers: {'content-type': 'application/json'});
    });
