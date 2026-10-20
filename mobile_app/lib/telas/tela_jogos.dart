import 'package:flutter/material.dart';

import '../api/cliente_api.dart';
import '../api/sessao.dart';
import '../formato.dart';
import '../modelos/partida.dart';
import '../tema.dart';
import '../widgets/cartao_partida.dart';
import '../widgets/comum.dart';
import 'garantir_vaga.dart';

/// Aba "Jogos": o feed de partidas com vaga, agrupado por dia.
class TelaJogos extends StatefulWidget {
  const TelaJogos({super.key});

  @override
  State<TelaJogos> createState() => _TelaJogosState();
}

enum _Filtro {
  todos('Todos'),
  hoje('Hoje'),
  amanha('Amanhã'),
  peladas('Peladas de grupo');

  const _Filtro(this.rotulo);
  final String rotulo;
}

class _TelaJogosState extends State<TelaJogos> {
  var _filtro = _Filtro.todos;
  late Future<List<Partida>> _partidas;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _partidas = _buscar();
  }

  Future<List<Partida>> _buscar() {
    final api = EscopoSessao.of(context, ouvir: false).api;
    final hoje = DateTime.now();
    return switch (_filtro) {
      _Filtro.todos => api.partidas(),
      _Filtro.hoje => api.partidas(dia: hoje),
      _Filtro.amanha => api.partidas(dia: hoje.add(const Duration(days: 1))),
      _Filtro.peladas => api.partidas(origem: 'pelada'),
    };
  }

  Future<void> _recarregar() async {
    final partidas = _buscar();
    setState(() => _partidas = partidas);
    await partidas.catchError((_) => <Partida>[]);
  }

  void _filtrar(_Filtro filtro) {
    _filtro = filtro;
    _recarregar();
  }

  @override
  Widget build(BuildContext context) {
    final sessao = EscopoSessao.of(context);
    final nome = sessao.usuario?.nome.split(' ').first;
    return SafeArea(
      child: RefreshIndicator(
        color: Cores.texto,
        onRefresh: _recarregar,
        child: CustomScrollView(
          slivers: [
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(Espacos.tela, 24, Espacos.tela, 16),
              sliver: SliverToBoxAdapter(child: TituloTela(nome == null ? 'Bora jogar?' : 'Bora jogar, $nome?')),
            ),
            SliverToBoxAdapter(
              child: SizedBox(
                height: 44,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: Espacos.tela),
                  children: [
                    for (final filtro in _Filtro.values)
                      Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: ChoiceChip(
                          label: Text(filtro.rotulo),
                          selected: _filtro == filtro,
                          onSelected: (_) => _filtrar(filtro),
                        ),
                      ),
                  ],
                ),
              ),
            ),
            FutureBuilder<List<Partida>>(
              future: _partidas,
              builder: (context, estado) {
                if (estado.connectionState != ConnectionState.done) {
                  return const SliverToBoxAdapter(child: Carregando());
                }
                if (estado.hasError) {
                  final erro = estado.error;
                  return SliverToBoxAdapter(
                    child: EstadoVazio(
                      titulo: 'Não deu para carregar os jogos',
                      texto: erro is ApiErro ? erro.mensagem : null,
                      acao: 'Tentar de novo',
                      aoTocar: _recarregar,
                    ),
                  );
                }
                final partidas = estado.data ?? const [];
                if (partidas.isEmpty) {
                  return const SliverToBoxAdapter(
                    child: EstadoVazio(titulo: 'Nenhum jogo com vaga', texto: 'Tente outro dia ou volte mais tarde.'),
                  );
                }
                return SliverPadding(
                  padding: const EdgeInsets.fromLTRB(Espacos.tela, 8, Espacos.tela, 32),
                  sliver: SliverList.list(children: _porDia(partidas)),
                );
              },
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _porDia(List<Partida> partidas) {
    final itens = <Widget>[];
    DateTime? diaAtual;
    for (final partida in partidas) {
      if (partida.data != diaAtual) {
        diaAtual = partida.data;
        itens.add(
          Padding(
            padding: const EdgeInsets.only(top: 16, bottom: 8),
            child: Text.rich(
              TextSpan(
                text: rotuloDia(partida.data),
                style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
                children: [
                  TextSpan(
                    text: '  ${diaMes(partida.data)}',
                    style: const TextStyle(fontWeight: FontWeight.w400, color: Cores.textoSecundario),
                  ),
                ],
              ),
            ),
          ),
        );
      }
      itens.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: CartaoPartida(
            partida: partida,
            aoGarantir: () async {
              await garantirVaga(context, partida);
              if (mounted) _recarregar();
            },
          ),
        ),
      );
    }
    return itens;
  }
}
