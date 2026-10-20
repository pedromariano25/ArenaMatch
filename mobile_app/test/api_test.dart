import 'dart:convert';

import 'package:arenamatch/api/arenamatch_api.dart';
import 'package:arenamatch/api/cliente_api.dart';
import 'package:arenamatch/modelos/carteira.dart';
import 'package:arenamatch/modelos/partida.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'dados.dart';

void main() {
  group('modelos', () {
    test('partida da arena e pelada de grupo', () {
      final arena = Partida.fromJson(partidaJson());
      expect(arena.peladaDeGrupo, isFalse);
      expect(arena.nome, 'Arena Gol de Placa');
      expect((arena.precoPix, arena.precoGoleiro, arena.vagasDisponiveis), (23.95, 0.0, 3));
      expect(arena.data, DateTime(2026, 10, 21));

      final pelada = Partida.fromJson(partidaJson(origem: 'pelada'));
      expect((pelada.peladaDeGrupo, pelada.nome, pelada.organizador), (true, 'Pelada da Firma', 'Ana S.'));
      expect(Partida.fromJson(partidaJson(vagasDisponiveis: 0, status: 'lotada')).lotada, isTrue);
    });

    test('carteira com e sem chave Pix', () {
      final semChave = CarteiraOrganizador.fromJson({
        'disponivel': '24.00',
        'a_liberar': '14.00',
        'valor_minimo_saque': '10.00',
        'chave_pix': null,
      });
      expect((semChave.disponivel, semChave.chavePix, semChave.podeSacar), (24.0, null, false));

      final comChave = CarteiraOrganizador.fromJson({
        'disponivel': '24.00',
        'a_liberar': '0.00',
        'valor_minimo_saque': '10.00',
        'chave_pix': {'tipo': 'email', 'chave': 'ana@example.com'},
      });
      expect((comChave.chavePix, comChave.podeSacar), ('ana@example.com', true));
    });

    test('erros do DRF viram mensagem legível', () {
      final porCampo = ApiErro.daResposta(http.Response('{"telefone": ["Informe o celular com DDD."]}', 400));
      expect(porCampo.mensagem, 'Informe o celular com DDD.');
      expect(porCampo.campos['telefone'], ['Informe o celular com DDD.']);
      expect(
        ApiErro.daResposta(http.Response('{"detail": "As credenciais não foram fornecidas."}', 401)).naoAutenticado,
        isTrue,
      );
      expect(ApiErro.daResposta(http.Response('<html>', 502)).mensagem, contains('502'));
    });
  });

  group('ArenaMatchApi', () {
    test('feed manda o filtro de origem e segue a paginação', () async {
      final recebidas = <http.Request>[];
      final cliente = MockClient((requisicao) async {
        recebidas.add(requisicao);
        final segunda = requisicao.url.queryParameters['page'] == '2';
        final corpo = pagina([
          partidaJson(id: segunda ? 'p2' : 'p1'),
        ], proxima: segunda ? null : 'http://teste/api/partidas/?page=2');
        return http.Response.bytes(utf8.encode(jsonEncode(corpo)), 200);
      });
      final api = ArenaMatchApi(ClienteApi(cliente: cliente, baseUrl: 'http://teste/api'));

      final partidas = await api.partidas(origem: 'pelada');
      expect(partidas.map((p) => p.id), ['p1', 'p2']);
      expect(recebidas.first.url.toString(), 'http://teste/api/partidas/?origem=pelada');
      expect(recebidas.last.url.queryParameters, {'origem': 'pelada', 'page': '2'});
    });

    test('login pelo celular e token no cabeçalho', () async {
      final recebidas = <http.Request>[];
      final api = ArenaMatchApi(
        ClienteApi(
          cliente: clienteFalso({
            '/api/auth/celular/': {'telefone': '(11) 91234-5678', 'codigo': '123456'},
            '/api/auth/celular/verificar/': {'token': 'abc', 'usuario': {}, 'precisa_de_perfil': true},
            '/api/me/': {
              'id': 1,
              'first_name': 'Bia',
              'last_name': 'Souza',
              'telefone': '(11) 91234-5678',
              'is_player': true,
              'perfil': null,
            },
          }, recebidas: recebidas),
          baseUrl: 'http://teste/api/',
        ),
      );

      expect(await api.solicitarCodigo('11912345678'), '123456');
      final login = await api.verificarCodigo('11912345678', '123456', nome: 'Bia Souza');
      expect((login.token, login.precisaDePerfil), ('abc', true));
      expect(jsonDecode(recebidas[1].body), {'telefone': '11912345678', 'codigo': '123456', 'nome': 'Bia Souza'});

      api.cliente.token = login.token;
      final eu = await api.eu();
      expect((eu.nome, eu.iniciais, eu.temPerfil), ('Bia Souza', 'BS', false));
      expect(recebidas.last.headers['Authorization'], 'Token abc');
    });

    test('criar pelada envia só o essencial', () async {
      final recebidas = <http.Request>[];
      final api = ArenaMatchApi(
        ClienteApi(
          cliente: clienteFalso({
            '/api/peladas/': {
              ...partidaJson(origem: 'pelada'),
              'recebe_por_vaga': '15.00',
              'arrecadado': '0.00',
              'em_pagamento': 0,
              'pode_cancelar': true,
            },
          }, recebidas: recebidas),
          baseUrl: 'http://teste/api/',
          token: 'abc',
        ),
      );

      final pelada = await api.criarPelada(
        quadra: 7,
        dia: DateTime(2026, 10, 22),
        horaInicio: '20:00',
        vagas: 2,
        valorPorVaga: 15,
      );
      expect((pelada.recebePorVaga, pelada.podeCancelar), (15.0, true));
      expect(jsonDecode(recebidas.single.body), {
        'quadra': 7,
        'dia': '2026-10-22',
        'hora_inicio': '20:00',
        'vagas_linha': 2,
        'valor_por_vaga': '15.00',
        'titulo': '',
        'nivel': 'aberta',
      });
    });

    test('sem internet vira ApiErro com mensagem amigável', () async {
      final api = ArenaMatchApi(
        ClienteApi(
          cliente: MockClient((_) async => throw http.ClientException('offline')),
          baseUrl: 'http://teste/api/',
        ),
      );
      expect(api.partidas(), throwsA(isA<ApiErro>().having((e) => e.mensagem, 'mensagem', contains('Sem conexão'))));
    });
  });
}
