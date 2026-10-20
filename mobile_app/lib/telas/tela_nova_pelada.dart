import 'package:flutter/material.dart';

import '../api/cliente_api.dart';
import '../api/sessao.dart';
import '../formato.dart';
import '../modelos/usuario.dart';
import '../tema.dart';
import '../widgets/comum.dart';

/// "Completar a pelada" em um passo só: onde, quando, quantas vagas e quanto você recebe.
class TelaNovaPelada extends StatefulWidget {
  const TelaNovaPelada({super.key});

  @override
  State<TelaNovaPelada> createState() => _TelaNovaPeladaState();
}

class _TelaNovaPeladaState extends State<TelaNovaPelada> {
  late final Future<List<Quadra>> _quadras;
  Quadra? _quadra;
  DateTime? _dia;
  TimeOfDay? _horario;
  var _vagas = 2;
  final _valor = TextEditingController(text: '15,00');
  final _titulo = TextEditingController();
  var _enviando = false;
  String? _erro;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _quadras = EscopoSessao.of(context, ouvir: false).api.quadras();
  }

  @override
  void dispose() {
    _valor.dispose();
    _titulo.dispose();
    super.dispose();
  }

  double get _valorPorVaga => lerValor(_valor.text) ?? 0;

  bool get _completo => _quadra != null && _dia != null && _horario != null && _valorPorVaga >= 1;

  Future<void> _escolherDia() async {
    final hoje = DateTime.now();
    final dia = await showDatePicker(
      context: context,
      initialDate: _dia ?? hoje,
      firstDate: DateTime(hoje.year, hoje.month, hoje.day),
      lastDate: hoje.add(const Duration(days: 30)),
    );
    if (dia != null) setState(() => _dia = dia);
  }

  Future<void> _escolherHorario() async {
    final horario = await showTimePicker(
      context: context,
      initialTime: _horario ?? const TimeOfDay(hour: 20, minute: 0),
    );
    if (horario != null) setState(() => _horario = horario);
  }

  Future<void> _confirmar() async {
    setState(() {
      _enviando = true;
      _erro = null;
    });
    try {
      final horario = _horario!;
      await EscopoSessao.of(context, ouvir: false).api.criarPelada(
        quadra: _quadra!.id,
        dia: _dia!,
        horaInicio: '${horario.hour.toString().padLeft(2, '0')}:${horario.minute.toString().padLeft(2, '0')}',
        vagas: _vagas,
        valorPorVaga: _valorPorVaga,
        titulo: _titulo.text.trim(),
      );
      if (!mounted) return;
      avisar(context, 'Pronto! Suas vagas estão no feed.');
      Navigator.of(context).pop(true);
    } on ApiErro catch (erro) {
      if (mounted) setState(() => _erro = erro.mensagem);
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final temas = Theme.of(context).textTheme;
    final rotulo = temas.titleLarge?.copyWith(fontSize: 16);
    final preco = precoPelada(_valorPorVaga);

    return Scaffold(
      appBar: AppBar(title: const Text('Completar a pelada')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(Espacos.tela),
          children: [
            Text('Onde vocês jogam', style: rotulo),
            const SizedBox(height: 8),
            FutureBuilder<List<Quadra>>(
              future: _quadras,
              builder: (context, estado) {
                if (estado.hasError) {
                  return Text('Não deu para carregar as quadras.', style: TextStyle(color: Cores.erro));
                }
                final quadras = estado.data ?? const <Quadra>[];
                return DropdownButtonFormField<Quadra>(
                  initialValue: _quadra,
                  isExpanded: true,
                  hint: const Text('Escolha a arena e a quadra'),
                  items: [
                    for (final quadra in quadras)
                      DropdownMenuItem(
                        value: quadra,
                        child: Text(quadra.rotulo, overflow: TextOverflow.ellipsis),
                      ),
                  ],
                  onChanged: (quadra) => setState(() => _quadra = quadra),
                );
              },
            ),
            const SizedBox(height: 20),
            Row(
              children: [
                Expanded(
                  child: _Seletor(
                    rotulo: 'Dia',
                    valor: _dia == null ? 'Escolher' : '${rotuloDia(_dia!)}, ${diaMes(_dia!)}',
                    aoTocar: _escolherDia,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _Seletor(
                    rotulo: 'Horário',
                    valor: _horario == null ? 'Escolher' : _horario!.format(context),
                    aoTocar: _escolherHorario,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 20),
            Text('Quantas vagas faltam?', style: rotulo),
            const SizedBox(height: 8),
            Row(
              children: [
                _BotaoContador(icone: Icons.remove, aoTocar: _vagas > 1 ? () => setState(() => _vagas--) : null),
                Expanded(
                  child: Text(
                    '$_vagas',
                    textAlign: TextAlign.center,
                    style: temas.headlineMedium,
                    semanticsLabel: '$_vagas vagas',
                  ),
                ),
                _BotaoContador(icone: Icons.add, aoTocar: _vagas < 20 ? () => setState(() => _vagas++) : null),
              ],
            ),
            const SizedBox(height: 20),
            Text('Você recebe por vaga (R\$)', style: rotulo),
            const SizedBox(height: 8),
            TextField(
              controller: _valor,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              style: const TextStyle(fontSize: 18),
              onChanged: (_) => setState(() {}),
            ),
            const SizedBox(height: 20),
            Cartao(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Cada jogador paga', style: temas.bodyLarge?.copyWith(color: Cores.textoSecundario)),
                  Text(brl(preco), style: temas.headlineMedium),
                  const SizedBox(height: 4),
                  Text(
                    'Você recebe ${brl(_valorPorVaga)} por vaga · ${brl(_valorPorVaga * _vagas)} vendendo tudo',
                    style: temas.bodyMedium?.copyWith(color: Cores.textoSecundario),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 8),
            Theme(
              data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: Text('Mais opções', style: rotulo),
                children: [
                  TextField(
                    controller: _titulo,
                    textCapitalization: TextCapitalization.sentences,
                    decoration: const InputDecoration(labelText: 'Nome da pelada', hintText: 'Ex.: Pelada da Firma'),
                  ),
                  const SizedBox(height: 8),
                ],
              ),
            ),
            if (_erro != null) ...[
              Text(_erro!, style: temas.bodyMedium?.copyWith(color: Cores.erro)),
              const SizedBox(height: 12),
            ],
            FilledButton(onPressed: _completo && !_enviando ? _confirmar : null, child: const Text('Confirmar')),
            const SizedBox(height: 12),
            Text(
              'Taxa ArenaMatch: 20% (mínimo de R\$ 5,00) por cima do seu valor. '
              'O dinheiro libera no dia seguinte ao jogo, para saque via Pix.',
              textAlign: TextAlign.center,
              style: temas.bodySmall?.copyWith(color: Cores.textoSecundario),
            ),
          ],
        ),
      ),
    );
  }
}

class _Seletor extends StatelessWidget {
  const _Seletor({required this.rotulo, required this.valor, required this.aoTocar});

  final String rotulo;
  final String valor;
  final VoidCallback aoTocar;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(rotulo, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontSize: 16)),
        const SizedBox(height: 8),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton(
            onPressed: aoTocar,
            style: OutlinedButton.styleFrom(
              textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(Espacos.raioCampo)),
            ),
            child: Text(valor),
          ),
        ),
      ],
    );
  }
}

class _BotaoContador extends StatelessWidget {
  const _BotaoContador({required this.icone, required this.aoTocar});

  final IconData icone;
  final VoidCallback? aoTocar;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 56,
      height: 56,
      child: OutlinedButton(
        onPressed: aoTocar,
        style: OutlinedButton.styleFrom(
          padding: EdgeInsets.zero,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(Espacos.raioCampo)),
        ),
        child: Icon(icone),
      ),
    );
  }
}
