import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/cliente_api.dart';
import '../api/sessao.dart';
import '../formato.dart';
import '../modelos/inscricao.dart';
import '../modelos/partida.dart';
import '../tema.dart';
import 'tela_entrar.dart';
import 'tela_questionario.dart';

/// "Garantir vaga": entra (se preciso), responde o questionário (no primeiro acesso) e paga no Pix.
Future<void> garantirVaga(BuildContext context, Partida partida) async {
  final sessao = EscopoSessao.of(context, ouvir: false);
  if (!sessao.logado && !await entrar(context)) return;
  if (!context.mounted) return;
  if (!(sessao.usuario?.temPerfil ?? false) && !await responderQuestionario(context)) return;
  if (!context.mounted) return;
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    backgroundColor: Cores.cartao,
    builder: (_) => FolhaGarantirVaga(partida: partida, sessao: sessao),
  );
}

class FolhaGarantirVaga extends StatefulWidget {
  const FolhaGarantirVaga({super.key, required this.partida, required this.sessao});

  final Partida partida;
  final Sessao sessao;

  @override
  State<FolhaGarantirVaga> createState() => _FolhaGarantirVagaState();
}

class _FolhaGarantirVagaState extends State<FolhaGarantirVaga> {
  Inscricao? _inscricao;
  String? _erro;
  var _enviando = false;

  Future<void> _pagar() async {
    setState(() {
      _enviando = true;
      _erro = null;
    });
    try {
      final inscricao = await widget.sessao.api.garantirVaga(widget.partida.id);
      setState(() => _inscricao = inscricao);
    } on ApiErro catch (erro) {
      setState(() => _erro = erro.mensagem);
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final temas = Theme.of(context).textTheme;
    final partida = widget.partida;
    final inscricao = _inscricao;

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(Espacos.tela, 0, Espacos.tela, Espacos.tela),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (inscricao == null) ...[
              Text('Garanta sua vaga', style: temas.headlineSmall),
              const SizedBox(height: 4),
              Text(
                '${partida.nome} · ${rotuloDia(partida.data)} ${diaMes(partida.data)}, ${partida.horaInicio}',
                style: temas.bodyLarge?.copyWith(color: Cores.textoSecundario),
              ),
              const SizedBox(height: 24),
              Text(brl(partida.precoPix), style: temas.headlineMedium),
              Text('por pessoa, no Pix', style: temas.bodyMedium?.copyWith(color: Cores.textoSecundario)),
              if (_erro != null) ...[
                const SizedBox(height: 16),
                Text(_erro!, style: temas.bodyMedium?.copyWith(color: Cores.erro)),
              ],
              const SizedBox(height: 24),
              FilledButton(
                onPressed: _enviando ? null : _pagar,
                child: Text(_enviando ? 'Gerando o Pix…' : 'Pagar ${brl(partida.precoPix)} no Pix'),
              ),
            ] else if (inscricao.aguardandoPagamento && inscricao.pixCopiaECola != null) ...[
              Text('Pague no Pix', style: temas.headlineSmall),
              const SizedBox(height: 4),
              Text(
                'Copie o código e cole no app do seu banco. Assim que o Pix cair, a vaga é sua.',
                style: temas.bodyLarge?.copyWith(color: Cores.textoSecundario),
              ),
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Cores.fundo,
                  borderRadius: BorderRadius.circular(Espacos.raioCampo),
                  border: Border.all(color: Cores.borda),
                ),
                child: Text(
                  inscricao.pixCopiaECola!,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
                ),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: () async {
                  await Clipboard.setData(ClipboardData(text: inscricao.pixCopiaECola!));
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Código Pix copiado.')));
                  }
                },
                child: Text('Copiar código Pix · ${brl(inscricao.valorTotal)}'),
              ),
            ] else ...[
              const Icon(Icons.check_circle, color: Cores.bandeira, size: 48),
              const SizedBox(height: 12),
              Text('Vaga garantida!', style: temas.headlineSmall, textAlign: TextAlign.center),
              const SizedBox(height: 4),
              Text(
                'Ela aparece em Perfil, nos próximos jogos.',
                style: temas.bodyLarge?.copyWith(color: Cores.textoSecundario),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              OutlinedButton(onPressed: () => Navigator.pop(context), child: const Text('Fechar')),
            ],
          ],
        ),
      ),
    );
  }
}
