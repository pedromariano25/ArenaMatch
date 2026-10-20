import 'package:flutter/material.dart';

import '../api/cliente_api.dart';
import '../api/sessao.dart';
import '../tema.dart';
import '../widgets/comum.dart';

/// Abre o questionário de nível. Devolve `true` se foi salvo.
Future<bool> responderQuestionario(BuildContext context) async {
  final salvo = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const TelaQuestionario()));
  return salvo ?? false;
}

// Mesmas opções do Django (arena/jogadores.py e PosicaoJogador).
const _posicoes = {'goleiro': 'Goleiro', 'defesa': 'Defesa', 'meio': 'Meio-campo', 'ataque': 'Ataque'};
const _frequencias = {
  'raro': 'Raramente',
  'mensal': 'Uma vez por mês',
  'semanal': 'Toda semana',
  'varias': 'Várias vezes por semana',
};
const _experiencias = {
  'nunca': 'Nunca joguei em time',
  'amigos': 'Escolinha ou time de amigos',
  'amador': 'Campeonato amador',
  'federado': 'Federado ou semiprofissional',
};

/// Três perguntas para achar jogos do seu nível (o servidor calcula o nível de 1 a 5).
class TelaQuestionario extends StatefulWidget {
  const TelaQuestionario({super.key});

  @override
  State<TelaQuestionario> createState() => _TelaQuestionarioState();
}

class _TelaQuestionarioState extends State<TelaQuestionario> {
  var _posicao = 'meio';
  var _autoavaliacao = 3;
  var _frequencia = 'semanal';
  var _experiencia = 'amigos';
  var _enviando = false;
  String? _erro;

  Future<void> _salvar() async {
    setState(() {
      _enviando = true;
      _erro = null;
    });
    final sessao = EscopoSessao.of(context, ouvir: false);
    try {
      await sessao.api.salvarQuestionario(
        posicao: _posicao,
        autoavaliacao: _autoavaliacao,
        frequencia: _frequencia,
        experiencia: _experiencia,
      );
      await sessao.atualizarUsuario();
      if (mounted) Navigator.of(context).pop(true);
    } on ApiErro catch (erro) {
      if (mounted) setState(() => _erro = erro.mensagem);
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final temas = Theme.of(context).textTheme;
    Widget pergunta(String texto) => Padding(
      padding: const EdgeInsets.only(top: 24, bottom: 12),
      child: Text(texto, style: temas.titleLarge?.copyWith(fontSize: 18)),
    );

    return Scaffold(
      appBar: AppBar(),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(Espacos.tela),
          children: [
            const TituloTela('Como você joga?', subtitulo: 'Assim a gente mostra jogos do seu nível.'),
            pergunta('Posição'),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final MapEntry(:key, :value) in _posicoes.entries)
                  ChoiceChip(
                    label: Text(value),
                    selected: _posicao == key,
                    onSelected: (_) => setState(() => _posicao = key),
                  ),
              ],
            ),
            pergunta('De 1 a 5, quanto você joga?'),
            SegmentedButton<int>(
              showSelectedIcon: false,
              segments: [for (var nota = 1; nota <= 5; nota++) ButtonSegment(value: nota, label: Text('$nota'))],
              selected: {_autoavaliacao},
              onSelectionChanged: (selecao) => setState(() => _autoavaliacao = selecao.first),
            ),
            pergunta('Com que frequência joga?'),
            for (final MapEntry(:key, :value) in _frequencias.entries)
              Opcao(rotulo: value, selecionada: _frequencia == key, aoTocar: () => setState(() => _frequencia = key)),
            pergunta('Até onde já jogou?'),
            for (final MapEntry(:key, :value) in _experiencias.entries)
              Opcao(rotulo: value, selecionada: _experiencia == key, aoTocar: () => setState(() => _experiencia = key)),
            if (_erro != null) ...[
              const SizedBox(height: 12),
              Text(_erro!, style: temas.bodyMedium?.copyWith(color: Cores.erro)),
            ],
            const SizedBox(height: 24),
            FilledButton(onPressed: _enviando ? null : _salvar, child: const Text('Salvar')),
          ],
        ),
      ),
    );
  }
}
