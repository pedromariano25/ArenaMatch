import 'package:flutter/material.dart';

import '../api/cliente_api.dart';
import '../api/sessao.dart';
import '../tema.dart';
import '../widgets/comum.dart';
import 'tela_questionario.dart';

/// Abre o login pelo celular. Devolve `true` se a pessoa entrou.
Future<bool> entrar(BuildContext context) async {
  final entrou = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const TelaEntrar()));
  return entrou ?? false;
}

/// Login sem senha: celular, código por SMS e pronto (a conta é criada no primeiro acesso).
class TelaEntrar extends StatefulWidget {
  const TelaEntrar({super.key});

  @override
  State<TelaEntrar> createState() => _TelaEntrarState();
}

class _TelaEntrarState extends State<TelaEntrar> {
  final _telefone = TextEditingController();
  final _codigo = TextEditingController();
  final _nome = TextEditingController();
  var _codigoEnviado = false;
  var _enviando = false;
  String? _erro;
  String? _codigoDeDemonstracao;

  @override
  void dispose() {
    _telefone.dispose();
    _codigo.dispose();
    _nome.dispose();
    super.dispose();
  }

  Future<void> _executar(Future<void> Function() acao) async {
    setState(() {
      _enviando = true;
      _erro = null;
    });
    try {
      await acao();
    } on ApiErro catch (erro) {
      if (mounted) setState(() => _erro = erro.mensagem);
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  Future<void> _pedirCodigo() => _executar(() async {
    final sessao = EscopoSessao.of(context, ouvir: false);
    final codigo = await sessao.api.solicitarCodigo(_telefone.text);
    setState(() {
      _codigoEnviado = true;
      _codigoDeDemonstracao = codigo;
    });
  });

  Future<void> _confirmar() => _executar(() async {
    final sessao = EscopoSessao.of(context, ouvir: false);
    final login = await sessao.api.verificarCodigo(_telefone.text, _codigo.text, nome: _nome.text);
    await sessao.entrar(login.token);
    if (!mounted) return;
    if (login.precisaDePerfil) await responderQuestionario(context);
    if (mounted) Navigator.of(context).pop(true);
  });

  @override
  Widget build(BuildContext context) {
    final temas = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(Espacos.tela),
          children: [
            TituloTela(
              _codigoEnviado ? 'Digite o código' : 'Entre com o celular',
              subtitulo: _codigoEnviado
                  ? 'Mandamos um SMS com 6 números para ${_telefone.text}.'
                  : 'Sem senha: você recebe um código por SMS.',
            ),
            const SizedBox(height: 24),
            if (!_codigoEnviado)
              TextField(
                controller: _telefone,
                keyboardType: TextInputType.phone,
                autofillHints: const [AutofillHints.telephoneNumber],
                style: const TextStyle(fontSize: 18),
                decoration: const InputDecoration(labelText: 'Celular com DDD', hintText: '(11) 91234-5678'),
                onSubmitted: (_) => _pedirCodigo(),
              )
            else ...[
              TextField(
                controller: _codigo,
                keyboardType: TextInputType.number,
                autofillHints: const [AutofillHints.oneTimeCode],
                maxLength: 6,
                style: const TextStyle(fontSize: 24, letterSpacing: 8, fontWeight: FontWeight.w700),
                decoration: const InputDecoration(labelText: 'Código', counterText: ''),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _nome,
                textCapitalization: TextCapitalization.words,
                decoration: const InputDecoration(labelText: 'Seu nome (só no primeiro acesso)'),
                onSubmitted: (_) => _confirmar(),
              ),
              if (_codigoDeDemonstracao != null) ...[
                const SizedBox(height: 12),
                Text(
                  'Modo de demonstração: o código é $_codigoDeDemonstracao.',
                  style: temas.bodyMedium?.copyWith(color: Cores.textoSecundario),
                ),
              ],
            ],
            if (_erro != null) ...[
              const SizedBox(height: 12),
              Text(_erro!, style: temas.bodyMedium?.copyWith(color: Cores.erro)),
            ],
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _enviando ? null : (_codigoEnviado ? _confirmar : _pedirCodigo),
              child: Text(_codigoEnviado ? 'Entrar' : 'Receber código'),
            ),
            if (_codigoEnviado)
              TextButton(
                onPressed: _enviando ? null : () => setState(() => _codigoEnviado = false),
                child: const Text('Trocar o número'),
              ),
          ],
        ),
      ),
    );
  }
}
