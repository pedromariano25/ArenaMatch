import 'package:arenamatch/formato.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('reais no formato brasileiro', () {
    expect(brl(20), r'R$ 20,00');
    expect(brl(1234.5), r'R$ 1.234,50');
    expect(brl(1234567.891), r'R$ 1.234.567,89');
    expect(brl(0), r'R$ 0,00');
    expect(brl(-15), r'-R$ 15,00');
  });

  test('rótulo do dia', () {
    final hoje = DateTime(2026, 10, 20); // terça-feira
    expect(rotuloDia(DateTime(2026, 10, 20, 22), hoje: hoje), 'Hoje');
    expect(rotuloDia(DateTime(2026, 10, 21), hoje: hoje), 'Amanhã');
    expect(rotuloDia(DateTime(2026, 10, 22), hoje: hoje), 'Quinta');
    expect(diaMes(DateTime(2026, 1, 5)), '05/01');
    expect(dataIso(DateTime(2026, 1, 5)), '2026-01-05');
  });

  test('prévia do preço da pelada: 20% com mínimo de R\$ 5', () {
    expect(precoPelada(15), 20); // 20% de 15 = 3, vale o mínimo de 5
    expect(precoPelada(30), 36); // 20% de 30 = 6
    expect(precoPelada(0), 0);
  });

  test('lê valores com vírgula ou ponto', () {
    expect(lerValor('15,50'), 15.5);
    expect(lerValor('1.234,50'), 1234.5);
    expect(lerValor('15.5'), 15.5);
    expect(lerValor(r'R$ 20'), 20);
    expect(lerValor('abc'), isNull);
  });
}
