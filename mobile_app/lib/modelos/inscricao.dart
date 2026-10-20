import 'leitura.dart';
import 'partida.dart';

/// Vaga comprada (ou em pagamento) pelo jogador.
class Inscricao {
  const Inscricao({
    required this.id,
    required this.partida,
    required this.status,
    required this.statusDisplay,
    required this.valorTotal,
    required this.pixCopiaECola,
    required this.reservadaAte,
  });

  final String id;
  final Partida partida;

  /// "aguardando_pagamento", "confirmada", "cancelada", "reembolsada" ou "expirada".
  final String status;
  final String statusDisplay;
  final double valorTotal;

  /// Código Pix enquanto o pagamento está pendente.
  final String? pixCopiaECola;
  final DateTime? reservadaAte;

  bool get aguardandoPagamento => status == 'aguardando_pagamento';
  bool get confirmada => status == 'confirmada';

  factory Inscricao.fromJson(Json json) {
    final pagamento = objeto(json['pagamento']);
    final pix = texto(pagamento['pix_copia_e_cola']);
    return Inscricao(
      id: texto(json['id']),
      partida: Partida.fromJson(objeto(json['partida'])),
      status: texto(json['status']),
      statusDisplay: texto(json['status_display']),
      valorTotal: dinheiro(json['valor_total']),
      pixCopiaECola: pix.isEmpty ? null : pix,
      reservadaAte: dataHora(json['reservada_ate']),
    );
  }
}
