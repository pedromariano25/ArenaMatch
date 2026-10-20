import 'package:flutter/material.dart';

import '../api/cliente_api.dart';
import '../api/sessao.dart';
import '../formato.dart';
import '../modelos/carteira.dart';
import '../modelos/partida.dart';
import '../tema.dart';
import '../widgets/comum.dart';
import 'tela_entrar.dart';
import 'tela_nova_pelada.dart';

/// Aba "Minhas Peladas" (C2C): vender as vagas que faltam no grupo e sacar o que entrou.
class TelaMinhasPeladas extends StatefulWidget {
  const TelaMinhasPeladas({super.key});

  @override
  State<TelaMinhasPeladas> createState() => _TelaMinhasPeladasState();
}

typedef _Painel = ({CarteiraOrganizador carteira, List<PeladaDoOrganizador> peladas});

class _TelaMinhasPeladasState extends State<TelaMinhasPeladas> {
  Future<_Painel>? _painel;
  bool? _logadoAntes;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final logado = EscopoSessao.of(context).logado;
    if (logado != _logadoAntes) {
      _logadoAntes = logado;
      _painel = logado ? _buscar() : null;
    }
  }

  Future<_Painel> _buscar() async {
    final api = EscopoSessao.of(context, ouvir: false).api;
    final (carteira, peladas) = await (api.carteira(), api.minhasPeladas()).wait;
    return (carteira: carteira, peladas: peladas);
  }

  Future<void> _recarregar() async {
    final painel = _buscar();
    setState(() => _painel = painel);
    await painel.then((_) {}, onError: (_) {});
  }

  Future<void> _novaPelada() async {
    final criada = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const TelaNovaPelada()));
    if (criada == true) _recarregar();
  }

  @override
  Widget build(BuildContext context) {
    final sessao = EscopoSessao.of(context);
    if (!sessao.logado) {
      return SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(Espacos.tela),
          children: [
            const SizedBox(height: 8),
            const TituloTela(
              'Minhas Peladas',
              subtitulo: 'Faltou gente na pelada do seu grupo? Venda as vagas que faltam e receba no Pix.',
            ),
            const SizedBox(height: 24),
            FilledButton(onPressed: () => entrar(context), child: const Text('Entrar para começar')),
          ],
        ),
      );
    }

    return SafeArea(
      child: RefreshIndicator(
        color: Cores.texto,
        onRefresh: _recarregar,
        child: FutureBuilder<_Painel>(
          future: _painel,
          builder: (context, estado) {
            final filhos = <Widget>[
              const SizedBox(height: 8),
              const TituloTela('Minhas Peladas', subtitulo: 'Venda as vagas que faltam no seu grupo.'),
              const SizedBox(height: 24),
              FilledButton.icon(
                onPressed: _novaPelada,
                icon: const Icon(Icons.add),
                label: const Text('Completar uma pelada'),
              ),
              const SizedBox(height: 16),
            ];
            if (estado.connectionState != ConnectionState.done) {
              filhos.add(const Carregando());
            } else if (estado.hasError) {
              final erro = estado.error;
              filhos.add(
                EstadoVazio(
                  titulo: 'Não deu para carregar',
                  texto: erro is ApiErro ? erro.mensagem : null,
                  acao: 'Tentar de novo',
                  aoTocar: _recarregar,
                ),
              );
            } else {
              final painel = estado.data!;
              filhos.add(_CartaoSaldo(carteira: painel.carteira, aoMudar: _recarregar));
              final proximas = [
                for (final pelada in painel.peladas)
                  if (pelada.partida.status == 'aberta' || pelada.partida.status == 'lotada') pelada,
              ];
              filhos.add(const SizedBox(height: 24));
              filhos.add(Text('Próximas peladas', style: Theme.of(context).textTheme.titleLarge));
              filhos.add(const SizedBox(height: 8));
              if (proximas.isEmpty) {
                filhos.add(
                  Text(
                    'Nenhuma pelada com vagas à venda.',
                    style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: Cores.textoSecundario),
                  ),
                );
              }
              for (final pelada in proximas) {
                filhos.add(_ItemPelada(pelada: pelada, aoCancelar: _recarregar));
              }
            }
            return ListView(padding: const EdgeInsets.all(Espacos.tela), children: filhos);
          },
        ),
      ),
    );
  }
}

class _CartaoSaldo extends StatelessWidget {
  const _CartaoSaldo({required this.carteira, required this.aoMudar});

  final CarteiraOrganizador carteira;
  final VoidCallback aoMudar;

  Future<void> _sacar(BuildContext context) async {
    final api = EscopoSessao.of(context, ouvir: false).api;
    if (carteira.chavePix == null) {
      final salvou = await showDialog<bool>(
        context: context,
        builder: (_) => _DialogoChavePix(sessao: EscopoSessao.of(context, ouvir: false)),
      );
      if (salvou == true) aoMudar();
      return;
    }
    try {
      final valor = await api.sacar();
      if (context.mounted) avisar(context, 'Saque de ${brl(valor)} enviado para a sua chave Pix.');
      aoMudar();
    } on ApiErro catch (erro) {
      if (context.mounted) avisar(context, erro.mensagem);
    }
  }

  @override
  Widget build(BuildContext context) {
    final temas = Theme.of(context).textTheme;
    return Cartao(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Disponível para saque', style: temas.bodyLarge?.copyWith(color: Cores.textoSecundario)),
          const SizedBox(height: 4),
          Text(brl(carteira.disponivel), style: temas.headlineMedium?.copyWith(fontSize: 36)),
          if (carteira.aLiberar > 0)
            Text(
              'Mais ${brl(carteira.aLiberar)} liberam no dia seguinte aos próximos jogos.',
              style: temas.bodyMedium?.copyWith(color: Cores.textoSecundario),
            ),
          const SizedBox(height: 16),
          OutlinedButton(
            onPressed: carteira.chavePix == null || carteira.podeSacar ? () => _sacar(context) : null,
            child: Text(carteira.chavePix == null ? 'Cadastrar chave Pix' : 'Sacar via Pix'),
          ),
          if (carteira.chavePix != null) ...[
            const SizedBox(height: 8),
            Text(
              carteira.podeSacar
                  ? 'Vai para ${carteira.chavePix}.'
                  : 'Saque a partir de ${brl(carteira.valorMinimoSaque)}. Vai para ${carteira.chavePix}.',
              style: temas.bodyMedium?.copyWith(color: Cores.textoSecundario),
            ),
          ],
        ],
      ),
    );
  }
}

class _DialogoChavePix extends StatefulWidget {
  const _DialogoChavePix({required this.sessao});

  final Sessao sessao;

  @override
  State<_DialogoChavePix> createState() => _DialogoChavePixState();
}

class _DialogoChavePixState extends State<_DialogoChavePix> {
  static const _tipos = {'celular': 'Celular', 'cpf': 'CPF', 'email': 'E-mail', 'aleatoria': 'Aleatória'};
  var _tipo = 'celular';
  final _chave = TextEditingController();
  String? _erro;

  @override
  void dispose() {
    _chave.dispose();
    super.dispose();
  }

  Future<void> _salvar() async {
    try {
      await widget.sessao.api.salvarChavePix(_tipo, _chave.text);
      if (mounted) Navigator.of(context).pop(true);
    } on ApiErro catch (erro) {
      setState(() => _erro = erro.campos['chave_pix']?.join(' ') ?? erro.mensagem);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: Cores.cartao,
      title: const Text('Sua chave Pix'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final MapEntry(:key, :value) in _tipos.entries)
                ChoiceChip(label: Text(value), selected: _tipo == key, onSelected: (_) => setState(() => _tipo = key)),
            ],
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _chave,
            decoration: InputDecoration(labelText: 'Chave', errorText: _erro, errorMaxLines: 3),
          ),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Voltar')),
        FilledButton(onPressed: _salvar, child: const Text('Salvar')),
      ],
    );
  }
}

class _ItemPelada extends StatelessWidget {
  const _ItemPelada({required this.pelada, required this.aoCancelar});

  final PeladaDoOrganizador pelada;
  final VoidCallback aoCancelar;

  Future<void> _cancelar(BuildContext context) async {
    final confirmou = await showDialog<bool>(
      context: context,
      builder: (contexto) => AlertDialog(
        backgroundColor: Cores.cartao,
        title: const Text('Cancelar as vagas?'),
        content: const Text('Quem comprou recebe o dinheiro de volta na hora.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(contexto, false), child: const Text('Voltar')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Cores.erro),
            onPressed: () => Navigator.pop(contexto, true),
            child: const Text('Cancelar vagas'),
          ),
        ],
      ),
    );
    if (confirmou != true || !context.mounted) return;
    try {
      final reembolsados = await EscopoSessao.of(context, ouvir: false).api.cancelarPelada(pelada.partida.id);
      if (context.mounted) {
        avisar(context, reembolsados > 0 ? 'Vagas canceladas. $reembolsados reembolsado(s).' : 'Vagas canceladas.');
      }
      aoCancelar();
    } on ApiErro catch (erro) {
      if (context.mounted) avisar(context, erro.mensagem);
    }
  }

  @override
  Widget build(BuildContext context) {
    final partida = pelada.partida;
    final cinza = Theme.of(context).textTheme.bodyMedium?.copyWith(color: Cores.textoSecundario);
    final vendidas = partida.lotada
        ? 'Completa · ${partida.vagasTotais} vendidas'
        : '${partida.confirmados} de ${partida.vagasTotais} vendidas';
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Cartao(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(partida.nome, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
                      Text(
                        '${rotuloDia(partida.data)}, ${diaMes(partida.data)} · ${partida.horaInicio} · ${partida.arena}',
                        style: cinza,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(brl(pelada.arrecadado), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                    Text('você recebe', style: cinza?.copyWith(fontSize: 12)),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: Text(
                    pelada.emPagamento > 0 ? '$vendidas · ${pelada.emPagamento} pagando agora' : vendidas,
                    style: cinza,
                  ),
                ),
                if (pelada.podeCancelar)
                  TextButton(onPressed: () => _cancelar(context), child: const Text('Cancelar vagas')),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
