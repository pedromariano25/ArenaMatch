import 'leitura.dart';

/// Saldo de quem organiza peladas: o valor de cada vaga libera no dia seguinte ao jogo.
class CarteiraOrganizador {
  const CarteiraOrganizador({
    required this.disponivel,
    required this.aLiberar,
    required this.valorMinimoSaque,
    required this.chavePix,
    required this.tipoChavePix,
  });

  final double disponivel;
  final double aLiberar;
  final double valorMinimoSaque;
  final String? chavePix;
  final String? tipoChavePix;

  bool get podeSacar => chavePix != null && disponivel >= valorMinimoSaque;

  factory CarteiraOrganizador.fromJson(Json json) {
    final chave = json['chave_pix'] is Map<String, dynamic> ? objeto(json['chave_pix']) : null;
    return CarteiraOrganizador(
      disponivel: dinheiro(json['disponivel']),
      aLiberar: dinheiro(json['a_liberar']),
      valorMinimoSaque: dinheiro(json['valor_minimo_saque']),
      chavePix: chave == null ? null : texto(chave['chave']),
      tipoChavePix: chave == null ? null : texto(chave['tipo']),
    );
  }
}
