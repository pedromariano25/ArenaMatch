// Leitura tolerante do JSON da API: o DRF manda dinheiro como texto ("20.00").

typedef Json = Map<String, dynamic>;

double dinheiro(Object? valor) => switch (valor) {
  final num numero => numero.toDouble(),
  final String texto => double.tryParse(texto) ?? 0,
  _ => 0,
};

int inteiro(Object? valor) => switch (valor) {
  final int numero => numero,
  final num numero => numero.toInt(),
  final String texto => int.tryParse(texto) ?? 0,
  _ => 0,
};

String texto(Object? valor) => valor == null ? '' : '$valor';

Json objeto(Object? valor) => valor is Map<String, dynamic> ? valor : const {};

List<Json> lista(Object? valor) => [
  if (valor is List)
    for (final item in valor)
      if (item is Map<String, dynamic>) item,
];

/// Lista paginada do DRF ({"results": [...]}) ou lista simples.
List<Json> resultados(Object? corpo) => corpo is Map<String, dynamic> ? lista(corpo['results']) : lista(corpo);

DateTime? dataHora(Object? valor) => valor is String ? DateTime.tryParse(valor)?.toLocal() : null;
