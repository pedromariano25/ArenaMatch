import 'package:flutter/material.dart';

import '../formato.dart';
import '../modelos/partida.dart';
import '../tema.dart';

/// Cartão do feed, estilo Uber: hora e preço grandes, o essencial embaixo e um botão só.
class CartaoPartida extends StatelessWidget {
  const CartaoPartida({super.key, required this.partida, required this.aoGarantir});

  final Partida partida;
  final VoidCallback aoGarantir;

  @override
  Widget build(BuildContext context) {
    final temas = Theme.of(context).textTheme;
    final cinza = temas.bodyMedium?.copyWith(color: Cores.textoSecundario);
    final detalhes = [
      partida.lotada ? 'Lotada' : '${partida.vagasDisponiveis} vaga${partida.vagasDisponiveis == 1 ? '' : 's'}',
      if (partida.nivel != 'aberta') partida.nivelDisplay,
      if (partida.vagasGoleiro > 0)
        partida.precoGoleiro == 0 ? 'goleiro grátis' : 'goleiro ${brl(partida.precoGoleiro)}',
      if (partida.confirmados > 0) '${partida.confirmados} confirmado${partida.confirmados == 1 ? '' : 's'}',
    ];

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  partida.peladaDeGrupo ? Icons.groups_outlined : Icons.verified_outlined,
                  size: 16,
                  color: Cores.textoSecundario,
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    partida.peladaDeGrupo ? 'Pelada de grupo · por ${partida.organizador ?? ''}' : 'Arena parceira',
                    style: cinza?.copyWith(fontSize: 13),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(child: Text(partida.horaInicio, style: temas.headlineSmall?.copyWith(height: 1))),
                Text(brl(partida.precoPix), style: temas.headlineSmall?.copyWith(height: 1)),
              ],
            ),
            Align(
              alignment: Alignment.centerRight,
              child: Text('por pessoa', style: cinza?.copyWith(fontSize: 13)),
            ),
            const SizedBox(height: 4),
            Text(partida.nome, style: temas.titleLarge?.copyWith(fontSize: 17)),
            const SizedBox(height: 2),
            Text(
              [partida.quadra, if (partida.endereco.isNotEmpty) partida.endereco].join(' · '),
              style: cinza,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            const SizedBox(height: 4),
            Text(detalhes.join(' · '), style: cinza?.copyWith(fontSize: 13)),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: partida.lotada || !partida.aceitaInscricoes
                  ? const OutlinedButton(onPressed: null, child: Text('Lotada'))
                  : FilledButton(onPressed: aoGarantir, child: const Text('Garantir vaga')),
            ),
          ],
        ),
      ),
    );
  }
}
