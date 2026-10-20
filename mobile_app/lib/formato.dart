// Formatação em português do Brasil (sem depender do pacote intl).
import 'config.dart';

const _diasDaSemana = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];

/// 1234.5 → "R$ 1.234,50"
String brl(double valor) {
  final centavos = (valor.abs() * 100).round();
  final inteiro = (centavos ~/ 100).toString();
  final milhares = StringBuffer();
  for (var i = 0; i < inteiro.length; i++) {
    if (i > 0 && (inteiro.length - i) % 3 == 0) milhares.write('.');
    milhares.write(inteiro[i]);
  }
  final sinal = valor < 0 && centavos > 0 ? '-' : '';
  return '${sinal}R\$ $milhares,${(centavos % 100).toString().padLeft(2, '0')}';
}

/// "20/10"
String diaMes(DateTime dia) => '${_doisDigitos(dia.day)}/${_doisDigitos(dia.month)}';

/// "Hoje", "Amanhã" ou o dia da semana ("Quinta").
String rotuloDia(DateTime dia, {DateTime? hoje}) {
  final referencia = _soData(hoje ?? DateTime.now());
  final diferenca = _soData(dia).difference(referencia).inDays;
  if (diferenca == 0) return 'Hoje';
  if (diferenca == 1) return 'Amanhã';
  return _diasDaSemana[dia.weekday - 1];
}

/// "AAAA-MM-DD", como a API espera.
String dataIso(DateTime dia) => '${dia.year}-${_doisDigitos(dia.month)}-${_doisDigitos(dia.day)}';

/// Quanto o jogador paga na pelada de grupo: o valor do organizador mais a taxa
/// (percentual com mínimo). Só para a prévia: o preço oficial vem da API.
double precoPelada(double valorPorVaga) {
  if (valorPorVaga <= 0) return 0;
  final percentual = (valorPorVaga * taxaPeladaPercentual).round() / 100;
  return valorPorVaga + (percentual > taxaPeladaMinima ? percentual : taxaPeladaMinima);
}

/// "15,50" ou "15.50" → 15.5 (nulo se não for número).
double? lerValor(String texto) {
  final limpo = texto.trim().replaceAll('R\$', '').replaceAll(' ', '');
  final normalizado = limpo.contains(',') ? limpo.replaceAll('.', '').replaceAll(',', '.') : limpo;
  return double.tryParse(normalizado);
}

String _doisDigitos(int numero) => numero.toString().padLeft(2, '0');

DateTime _soData(DateTime momento) => DateTime(momento.year, momento.month, momento.day);
