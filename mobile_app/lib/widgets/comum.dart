import 'package:flutter/material.dart';

import '../tema.dart';

/// Título grande da tela (peso 800, tracking negativo), como o `.titulo` do site.
class TituloTela extends StatelessWidget {
  const TituloTela(this.texto, {super.key, this.subtitulo});

  final String texto;
  final String? subtitulo;

  @override
  Widget build(BuildContext context) {
    final temas = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(texto, style: temas.headlineMedium),
        if (subtitulo != null) ...[
          const SizedBox(height: 6),
          Text(subtitulo!, style: temas.bodyLarge?.copyWith(color: Cores.textoSecundario)),
        ],
      ],
    );
  }
}

/// Cartão branco com borda fina e cantos de 16.
class Cartao extends StatelessWidget {
  const Cartao({super.key, required this.child, this.padding = const EdgeInsets.all(16)});

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(padding: padding, child: child),
  );
}

class Carregando extends StatelessWidget {
  const Carregando({super.key});

  @override
  Widget build(BuildContext context) => const Center(
    child: Padding(
      padding: EdgeInsets.all(32),
      child: CircularProgressIndicator(color: Cores.texto, strokeWidth: 2.5),
    ),
  );
}

/// Mensagem de vazio ou de erro, com no máximo uma ação.
class EstadoVazio extends StatelessWidget {
  const EstadoVazio({super.key, required this.titulo, this.texto, this.acao, this.aoTocar});

  final String titulo;
  final String? texto;
  final String? acao;
  final VoidCallback? aoTocar;

  @override
  Widget build(BuildContext context) {
    final temas = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 48, horizontal: 8),
      child: Column(
        children: [
          Text(titulo, style: temas.titleLarge, textAlign: TextAlign.center),
          if (texto != null) ...[
            const SizedBox(height: 8),
            Text(
              texto!,
              style: temas.bodyLarge?.copyWith(color: Cores.textoSecundario),
              textAlign: TextAlign.center,
            ),
          ],
          if (acao != null) ...[
            const SizedBox(height: 24),
            SizedBox(
              width: double.infinity,
              child: FilledButton(onPressed: aoTocar, child: Text(acao!)),
            ),
          ],
        ],
      ),
    );
  }
}

/// Avisos curtos na parte de baixo da tela.
void avisar(BuildContext context, String mensagem) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(mensagem)));
}

/// Opção grande de escolha única (a `.opcao` do site): borda escura quando marcada.
class Opcao extends StatelessWidget {
  const Opcao({super.key, required this.rotulo, required this.selecionada, required this.aoTocar, this.detalhe});

  final String rotulo;
  final String? detalhe;
  final bool selecionada;
  final VoidCallback aoTocar;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: Cores.cartao,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(Espacos.raioCartao),
          side: BorderSide(color: selecionada ? Cores.texto : Cores.borda, width: selecionada ? 1.5 : 1),
        ),
        child: InkWell(
          onTap: aoTocar,
          borderRadius: BorderRadius.circular(Espacos.raioCartao),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Icon(
                  selecionada ? Icons.radio_button_checked : Icons.radio_button_unchecked,
                  color: selecionada ? Cores.texto : Cores.textoApagado,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(rotulo, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
                ),
                if (detalhe != null) Text(detalhe!, style: const TextStyle(color: Cores.textoSecundario)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
