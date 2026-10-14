"""Motor financeiro: preços, checkout, pagamento, expiração, cancelamento, repasse e lista de espera."""

import json
from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from arena import checkout, razao
from arena.models import (
    Booking,
    MetodoPagamento,
    Payment,
    Posicao,
    StatusInscricao,
    StatusPagamento,
    TipoConta,
    TipoLancamento,
    WaitlistEntry,
)

from .fabricas import comprar, criar_arena, criar_horario, criar_jogador, criar_partida, criar_quadra, mover_partida


def lancamentos(tipo_conta: str, **filtros) -> dict[str, Decimal]:
    """Soma dos lançamentos por tipo numa espécie de carteira."""
    totais: dict[str, Decimal] = {}
    for lancamento in razao.LedgerEntry.objects.filter(conta__tipo=tipo_conta, **filtros):
        totais[lancamento.tipo] = totais.get(lancamento.tipo, Decimal("0")) + lancamento.valor
    return totais


class PrecosTest(TestCase):
    def test_goleiro_gratis_e_aluguel_dividido_pela_linha(self):
        partida = criar_partida(vagas=14, vagas_goleiro=2, valor_total_aluguel=Decimal("250.00"))
        self.assertEqual(partida.vagas_linha, 12)
        self.assertEqual(partida.preco_vaga_base, Decimal("20.83"))
        self.assertEqual(partida.valor_taxa_vaga, Decimal("3.12"))
        self.assertEqual(partida.preco_final_jogador, Decimal("23.95"))
        self.assertEqual(partida.preco_cartao, Decimal("25.15"))
        self.assertEqual(partida.valores_da_vaga(Posicao.GOLEIRO, MetodoPagamento.PIX), (Decimal("0"),) * 3)

    def test_taxa_minima(self):
        partida = criar_partida(vagas=12, valor_total_aluguel=Decimal("120.00"))
        self.assertEqual(partida.preco_vaga_base, Decimal("10.00"))
        self.assertEqual(partida.valor_taxa_vaga, Decimal("2.00"))  # 15% seria R$ 1,50
        self.assertEqual(partida.preco_final_jogador, Decimal("12.00"))

    def test_contrato_da_arena_e_copiado_para_a_partida(self):
        arena = criar_arena(taxa_plataforma_percentual=Decimal("10"), taxa_minima=Decimal("1.00"), quorum_percentual=50)
        partida = criar_partida(vagas=10, horario=criar_horario(criar_quadra(arena), status="ocioso"))
        self.assertEqual((partida.taxa_plataforma_percentual, partida.taxa_minima), (Decimal("10"), Decimal("1.00")))
        self.assertEqual(partida.minimo_jogadores, 5)
        self.assertEqual(partida.valor_taxa_vaga, Decimal("2.50"))

    def test_partida_precisa_de_vaga_de_linha(self):
        with self.assertRaises(ValidationError):
            criar_partida(vagas=2, vagas_goleiro=2)


class CheckoutTest(TestCase):
    def setUp(self):
        self.partida = criar_partida(vagas=3)  # R$ 25,00 de quadra + R$ 3,75 de taxa
        self.jogador = criar_jogador()

    def test_pix_reserva_a_vaga_e_confirma_ao_pagar(self):
        inscricao = checkout.iniciar_checkout(self.partida, self.jogador, metodo=MetodoPagamento.PIX)
        self.assertEqual(inscricao.status, StatusInscricao.AGUARDANDO_PAGAMENTO)
        self.assertAlmostEqual(inscricao.reservada_ate, timezone.now() + timedelta(minutes=10), delta=timedelta(seconds=30))
        pagamento = inscricao.pagamentos.get()
        self.assertEqual((pagamento.status, pagamento.valor), (StatusPagamento.PENDENTE, Decimal("28.75")))
        self.assertIn("ARENAMATCH-TESTE", pagamento.pix_copia_e_cola)
        self.partida.refresh_from_db()
        self.assertEqual(self.partida.vagas_disponiveis, 2)
        self.assertFalse(razao.LedgerEntry.objects.exists())

        with self.captureOnCommitCallbacks(execute=True):
            inscricao = checkout.simular_pagamento(inscricao)
        self.assertEqual(inscricao.status, StatusInscricao.CONFIRMADA)
        self.assertEqual(lancamentos(TipoConta.ARENA), {TipoLancamento.VENDA_VAGA: Decimal("25.00")})
        self.assertEqual(
            lancamentos(TipoConta.PLATAFORMA),
            {TipoLancamento.TAXA_SERVICO: Decimal("3.75"), TipoLancamento.TARIFA_GATEWAY: Decimal("-0.29")},
        )
        saldo = razao.saldo_da_arena(self.partida.time_slot.court.arena)
        self.assertEqual((saldo.a_liberar, saldo.disponivel), (Decimal("25.00"), Decimal("0")))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Vaga garantida", mail.outbox[0].subject)

    def test_cartao_confirma_na_hora_com_acrescimo(self):
        inscricao = checkout.iniciar_checkout(self.partida, self.jogador, metodo=MetodoPagamento.CARTAO)
        self.assertEqual(inscricao.status, StatusInscricao.CONFIRMADA)
        self.assertEqual((inscricao.valor_acrescimo, inscricao.valor_total), (Decimal("1.44"), Decimal("30.19")))
        self.assertEqual(inscricao.pagamentos.get().status, StatusPagamento.APROVADO)
        self.assertEqual(lancamentos(TipoConta.PLATAFORMA)[TipoLancamento.ACRESCIMO_CARTAO], Decimal("1.44"))

    def test_goleiro_entra_de_graca(self):
        partida = criar_partida(vagas=4, vagas_goleiro=1)
        inscricao = checkout.iniciar_checkout(partida, self.jogador, posicao=Posicao.GOLEIRO, metodo=MetodoPagamento.PIX)
        self.assertEqual((inscricao.status, inscricao.metodo_pagamento), (StatusInscricao.CONFIRMADA, MetodoPagamento.GRATUITO))
        self.assertEqual(inscricao.valor_total, Decimal("0"))
        self.assertFalse(inscricao.pagamentos.exists())
        with self.assertRaisesMessage(ValidationError, "vaga de goleiro"):
            checkout.iniciar_checkout(partida, criar_jogador(), posicao=Posicao.GOLEIRO)

    def test_credito_paga_a_vaga_e_precisa_ser_suficiente(self):
        with self.assertRaisesMessage(ValidationError, "não cobre esta vaga"):
            checkout.iniciar_checkout(self.partida, self.jogador, metodo=MetodoPagamento.CREDITO)
        outra = criar_partida(vagas=2)
        mover_partida(outra, timezone.now() + timedelta(days=2))
        checkout.cancelar_inscricao(comprar(outra, self.jogador, metodo=MetodoPagamento.CARTAO))
        self.assertEqual(razao.saldo_do_jogador(self.jogador), Decimal("30.19"))

        inscricao = checkout.iniciar_checkout(self.partida, self.jogador, metodo=MetodoPagamento.CREDITO)
        self.assertEqual(inscricao.status, StatusInscricao.CONFIRMADA)
        self.assertEqual(razao.saldo_do_jogador(self.jogador), Decimal("1.44"))

    def test_lotada_e_inscricao_duplicada(self):
        partida = criar_partida(vagas=1)
        comprar(partida, self.jogador)
        with self.assertRaisesMessage(ValidationError, "Esta partida está lotada."):
            comprar(partida)
        with self.assertRaises(ValidationError):
            comprar(partida, self.jogador)

    def test_notificacao_repetida_nao_duplica_a_venda(self):
        inscricao = checkout.iniciar_checkout(self.partida, self.jogador)
        gateway_id = inscricao.pagamentos.get().gateway_id
        for _ in range(3):
            checkout.processar_notificacao(gateway_id, aprovado=True)
        self.assertEqual(razao.LedgerEntry.objects.filter(tipo=TipoLancamento.VENDA_VAGA).count(), 1)

    def test_pagamento_recusado_libera_a_vaga(self):
        inscricao = checkout.iniciar_checkout(self.partida, self.jogador)
        pagamento = checkout.processar_notificacao(inscricao.pagamentos.get().gateway_id, aprovado=False)
        self.assertEqual(pagamento.status, StatusPagamento.RECUSADO)
        inscricao.refresh_from_db()
        self.assertEqual(inscricao.status, StatusInscricao.CANCELADA)
        self.partida.refresh_from_db()
        self.assertEqual(self.partida.vagas_disponiveis, 3)


class ExpiracaoTest(TestCase):
    def vencer(self, inscricao: Booking) -> None:
        Booking.objects.filter(pk=inscricao.pk).update(reservada_ate=timezone.now() - timedelta(minutes=1))

    def test_reserva_vencida_expira_e_devolve_a_vaga(self):
        partida = criar_partida(vagas=1)
        inscricao = checkout.iniciar_checkout(partida, criar_jogador())
        self.vencer(inscricao)
        self.assertEqual(checkout.expirar_reservas(), 1)
        inscricao.refresh_from_db()
        partida.refresh_from_db()
        self.assertEqual(inscricao.status, StatusInscricao.EXPIRADA)
        self.assertEqual(inscricao.pagamentos.get().status, StatusPagamento.EXPIRADO)
        self.assertEqual((partida.vagas_disponiveis, partida.status), (1, "aberta"))

    def test_vaga_de_reserva_vencida_pode_ser_comprada_antes_da_rotina(self):
        partida = criar_partida(vagas=1)
        atrasada = checkout.iniciar_checkout(partida, criar_jogador())
        self.vencer(atrasada)
        comprar(partida)  # expira a reserva vencida e vende a vaga
        atrasada.refresh_from_db()
        self.assertEqual(atrasada.status, StatusInscricao.EXPIRADA)

    def test_pagamento_atrasado_sem_vaga_e_devolvido(self):
        partida = criar_partida(vagas=1)
        atrasada = checkout.iniciar_checkout(partida, criar_jogador())
        self.vencer(atrasada)
        comprar(partida)
        with self.captureOnCommitCallbacks(execute=True):
            pagamento = checkout.processar_notificacao(atrasada.pagamentos.get().gateway_id, aprovado=True)
        self.assertEqual(pagamento.status, StatusPagamento.ESTORNADO)
        atrasada.refresh_from_db()
        self.assertEqual(atrasada.status, StatusInscricao.EXPIRADA)
        self.assertEqual(razao.LedgerEntry.objects.filter(tipo=TipoLancamento.VENDA_VAGA).count(), 1)
        self.assertTrue(any("devolvido" in m.subject for m in mail.outbox))

    def test_pagamento_atrasado_com_vaga_livre_e_confirmado(self):
        partida = criar_partida(vagas=2)
        atrasada = checkout.iniciar_checkout(partida, criar_jogador())
        self.vencer(atrasada)
        checkout.expirar_reservas()
        checkout.processar_notificacao(atrasada.pagamentos.get().gateway_id, aprovado=True)
        atrasada.refresh_from_db()
        self.assertEqual(atrasada.status, StatusInscricao.CONFIRMADA)

    def test_dinheiro_em_reserva_cancelada_e_devolvido(self):
        inscricao = checkout.iniciar_checkout(criar_partida(vagas=2), criar_jogador())
        checkout.cancelar_inscricao(inscricao)
        pagamento = checkout.processar_notificacao(inscricao.pagamentos.get().gateway_id, aprovado=True)
        self.assertEqual(pagamento.status, StatusPagamento.ESTORNADO)


class CancelamentoERepasseTest(TestCase):
    def setUp(self):
        self.partida = criar_partida(vagas=2)
        self.jogador = criar_jogador()

    def test_cancelar_reserva_nao_cobra_nada(self):
        inscricao = checkout.iniciar_checkout(self.partida, self.jogador)
        self.assertIn("Nenhum valor", checkout.cancelar_inscricao(inscricao))
        self.assertEqual(inscricao.pagamentos.get().status, StatusPagamento.CANCELADO)
        self.assertFalse(razao.LedgerEntry.objects.exists())

    def test_cancelar_com_24h_de_antecedencia_vira_credito(self):
        mover_partida(self.partida, timezone.now() + timedelta(days=2))
        inscricao = comprar(self.partida, self.jogador)
        self.assertIn("crédito", checkout.cancelar_inscricao(inscricao))
        inscricao.refresh_from_db()
        self.assertEqual(inscricao.status, StatusInscricao.CANCELADA)
        self.assertEqual(razao.saldo_do_jogador(self.jogador), Decimal("28.75"))
        self.assertEqual(razao.saldo(razao.LedgerEntry.objects.filter(conta__tipo=TipoConta.ARENA)), Decimal("0"))
        self.partida.refresh_from_db()
        self.assertEqual(self.partida.vagas_disponiveis, 2)

    def test_menos_de_24h_nao_cancela_mas_repassa(self):
        mover_partida(self.partida, timezone.now() + timedelta(hours=5))
        inscricao = comprar(self.partida, self.jogador)
        self.assertFalse(inscricao.pode_cancelar)
        with self.assertRaisesMessage(ValidationError, "menos de 24h"):
            checkout.cancelar_inscricao(inscricao)
        self.assertTrue(inscricao.pode_repassar)
        checkout.repassar_vaga(inscricao)
        self.partida.refresh_from_db()
        self.assertEqual(self.partida.vagas_disponiveis, 2)

        comprar(self.partida)  # vaga livre de verdade: o repasse continua pendente
        inscricao.refresh_from_db()
        self.assertTrue(inscricao.em_repasse)
        comprar(self.partida)  # agora a vaga repassada foi vendida
        inscricao.refresh_from_db()
        self.assertEqual(inscricao.status, StatusInscricao.CANCELADA)
        self.assertEqual(razao.saldo_do_jogador(self.jogador), Decimal("28.75"))

    def test_desfazer_repasse(self):
        mover_partida(self.partida, timezone.now() + timedelta(hours=5))
        inscricao = comprar(self.partida, self.jogador)
        checkout.repassar_vaga(inscricao)
        checkout.desfazer_repasse(inscricao)
        inscricao.refresh_from_db()
        self.assertFalse(inscricao.em_repasse)

    def test_goleiro_libera_a_vaga_sem_credito(self):
        partida = criar_partida(vagas=4, vagas_goleiro=1)
        inscricao = comprar(partida, self.jogador, posicao=Posicao.GOLEIRO)
        self.assertEqual(checkout.cancelar_inscricao(inscricao), "Vaga de goleiro liberada.")
        self.assertEqual(razao.saldo_do_jogador(self.jogador), Decimal("0"))


class ListaDeEsperaTest(TestCase):
    def test_avisa_quando_abre_vaga_e_sai_da_lista_ao_comprar(self):
        partida = criar_partida(vagas=1)
        mover_partida(partida, timezone.now() + timedelta(days=2))
        dono = comprar(partida)
        esperando = criar_jogador(email="espera@example.com")
        checkout.entrar_na_lista_de_espera(partida, esperando)
        with self.assertRaisesMessage(ValidationError, "já está nesta partida"):
            checkout.entrar_na_lista_de_espera(partida, dono.player)

        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            checkout.cancelar_inscricao(dono)
        self.assertEqual([m.to for m in mail.outbox if "Abriu vaga" in m.subject], [["espera@example.com"]])
        self.assertIsNotNone(WaitlistEntry.objects.get(jogador=esperando).notificado_em)

        comprar(partida, esperando)
        self.assertFalse(WaitlistEntry.objects.exists())


class WebhookTest(TestCase):
    def test_notificacao_do_gateway(self):
        inscricao = checkout.iniciar_checkout(criar_partida(vagas=2), criar_jogador())
        gateway_id = inscricao.pagamentos.get().gateway_id
        url = reverse("webhook_pagamentos")
        enviar = lambda dados: self.client.post(url, json.dumps(dados), content_type="application/json")  # noqa: E731

        self.assertEqual(enviar({"gateway_id": gateway_id, "status": "talvez"}).status_code, 400)
        self.assertEqual(enviar({"gateway_id": "inexistente", "status": "aprovado"}).status_code, 404)
        resposta = enviar({"gateway_id": gateway_id, "status": "aprovado"})
        self.assertEqual(resposta.json(), {"status": "aprovado"})
        self.assertEqual(Payment.objects.get().status, StatusPagamento.APROVADO)
