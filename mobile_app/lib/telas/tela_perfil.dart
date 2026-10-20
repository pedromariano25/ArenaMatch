import 'package:flutter/material.dart';

import '../api/sessao.dart';
import '../formato.dart';
import '../modelos/inscricao.dart';
import '../tema.dart';
import '../widgets/comum.dart';
import 'tela_entrar.dart';
import 'tela_questionario.dart';

/// Aba "Perfil": nível, próximos jogos e sair.
class TelaPerfil extends StatefulWidget {
  const TelaPerfil({super.key});

  @override
  State<TelaPerfil> createState() => _TelaPerfilState();
}

class _TelaPerfilState extends State<TelaPerfil> {
  Future<List<Inscricao>>? _inscricoes;
  bool? _logadoAntes;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final sessao = EscopoSessao.of(context);
    if (sessao.logado != _logadoAntes) {
      _logadoAntes = sessao.logado;
      _inscricoes = sessao.logado ? sessao.api.minhasInscricoes() : null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final sessao = EscopoSessao.of(context);
    final usuario = sessao.usuario;
    final temas = Theme.of(context).textTheme;
    final cinza = temas.bodyLarge?.copyWith(color: Cores.textoSecundario);

    if (!sessao.logado || usuario == null) {
      return SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(Espacos.tela),
          children: [
            const SizedBox(height: 8),
            const TituloTela('Perfil', subtitulo: 'Entre com o seu celular para garantir vagas e organizar peladas.'),
            const SizedBox(height: 24),
            FilledButton(onPressed: () => entrar(context), child: const Text('Entrar')),
          ],
        ),
      );
    }

    return SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(Espacos.tela),
        children: [
          const SizedBox(height: 8),
          Row(
            children: [
              CircleAvatar(
                radius: 32,
                backgroundColor: Cores.bandeiraClaro,
                foregroundColor: Cores.bandeiraEscuro,
                child: Text(usuario.iniciais, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(usuario.nome, style: temas.headlineSmall, overflow: TextOverflow.ellipsis),
                    if (usuario.telefone.isNotEmpty) Text(usuario.telefone, style: cinza),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 24),
          Cartao(
            padding: const EdgeInsets.all(20),
            child: usuario.temPerfil
                ? Row(
                    children: [
                      Text('${usuario.nivel}', style: temas.headlineMedium?.copyWith(fontSize: 40)),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('Seu nível', style: cinza),
                            Text(usuario.nivelDisplay, style: temas.titleLarge),
                          ],
                        ),
                      ),
                    ],
                  )
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text('Qual é o seu nível?', style: temas.titleLarge),
                      const SizedBox(height: 4),
                      Text('Três perguntas e você vê os jogos certos para você.', style: cinza),
                      const SizedBox(height: 16),
                      FilledButton(onPressed: () => responderQuestionario(context), child: const Text('Responder')),
                    ],
                  ),
          ),
          const SizedBox(height: 24),
          Text('Próximos jogos', style: temas.titleLarge),
          const SizedBox(height: 8),
          FutureBuilder<List<Inscricao>>(
            future: _inscricoes,
            builder: (context, estado) {
              if (estado.connectionState != ConnectionState.done) return const Carregando();
              final hoje = DateTime.now();
              final proximas = [
                for (final inscricao in estado.data ?? const <Inscricao>[])
                  if ((inscricao.confirmada || inscricao.aguardandoPagamento) &&
                      !inscricao.partida.data.isBefore(DateTime(hoje.year, hoje.month, hoje.day)))
                    inscricao,
              ];
              if (proximas.isEmpty) return Text('Nenhum jogo marcado.', style: cinza);
              return Column(
                children: [
                  for (final inscricao in proximas.reversed)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Cartao(
                        child: Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    inscricao.partida.nome,
                                    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                                  ),
                                  Text(
                                    '${rotuloDia(inscricao.partida.data)}, ${diaMes(inscricao.partida.data)} · ${inscricao.partida.horaInicio}',
                                    style: temas.bodyMedium?.copyWith(color: Cores.textoSecundario),
                                  ),
                                ],
                              ),
                            ),
                            _Selo(inscricao: inscricao),
                          ],
                        ),
                      ),
                    ),
                ],
              );
            },
          ),
          const SizedBox(height: 32),
          OutlinedButton(onPressed: sessao.sair, child: const Text('Sair')),
        ],
      ),
    );
  }
}

class _Selo extends StatelessWidget {
  const _Selo({required this.inscricao});

  final Inscricao inscricao;

  @override
  Widget build(BuildContext context) {
    final confirmada = inscricao.confirmada;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: confirmada ? Cores.bandeiraClaro : const Color(0xFFFFFBEB),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        confirmada ? 'Confirmada' : 'Pagar Pix',
        style: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w600,
          color: confirmada ? Cores.bandeiraEscuro : const Color(0xFF92400E),
        ),
      ),
    );
  }
}
