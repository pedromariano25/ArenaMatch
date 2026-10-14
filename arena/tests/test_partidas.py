"""Ciclo de vida da partida: cancelamento com reembolso, mínimo de jogadores, encerramento e repasses."""

from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from arena import checkout, partidas, razao
from arena.models import (
    LedgerEntry,
    MetodoPagamento,
    MotivoCancelamento,
    Posicao,
    StatusInscricao,
    StatusPagamento,
    StatusPartida,
    TipoConta,
    TipoLancamento,
)

from .fabricas import comprar, criar_jogador, criar_partida, mover_partida


def saldo_arena(partida) -> Decimal:
    return razao.saldo(LedgerEntry.objects.filter(conta__tipo=TipoConta.ARENA, partida=partida))


class CancelarPartidaTest(TestCase):
    def test_reembolsa_todos_pela_mesma_forma_de_pagamento(self):
        partida = criar_partida(vagas=5, vagas_goleiro=1)
        com_credito = criar_jogador()
        outra = criar_partida(vagas=2)
        mover_partida(outra, timezone.now() + timedelta(days=2))
        checkout.cancelar_inscricao(comprar(outra, com_credito))  # R$ 28,75 de crédito

        pix = comprar(partida, metodo=MetodoPagamento.PIX)
        cartao = comprar(partida, metodo=MetodoPagamento.CARTAO)
        credito = comprar(partida, com_credito, metodo=MetodoPagamento.CREDITO)
        goleiro = comprar(partida, posicao=Posicao.GOLEIRO)
        reserva = comprar(partida, pagar=False)
        self.assertEqual(razao.saldo_do_jogador(com_credito), Decimal("0"))

        with self.captureOnCommitCallbacks(execute=True):
            reembolsados = partidas.cancelar_partida(partida, MotivoCancelamento.ARENA)
        self.assertEqual(reembolsados, 3)

        partida.refresh_from_db()
        self.assertEqual((partida.status, partida.motivo_cancelamento), (StatusPartida.CANCELADA, "arena"))
        for inscricao, status in (
            (pix, StatusInscricao.REEMBOLSADA),
            (cartao, StatusInscricao.REEMBOLSADA),
            (credito, StatusInscricao.REEMBOLSADA),
            (goleiro, StatusInscricao.CANCELADA),
            (reserva, StatusInscricao.CANCELADA),
        ):
            inscricao.refresh_from_db()
            self.assertEqual(inscricao.status, status)
        self.assertEqual(pix.pagamentos.get().status, StatusPagamento.ESTORNADO)
        self.assertEqual(cartao.pagamentos.get().status, StatusPagamento.ESTORNADO)
        self.assertEqual(reserva.pagamentos.get().status, StatusPagamento.CANCELADO)
        self.assertEqual(razao.saldo_do_jogador(com_credito), Decimal("28.75"))
        self.assertEqual(saldo_arena(partida), Decimal("0"))
        # Todos os afetados são avisados, inclusive o goleiro e quem estava pagando.
        self.assertEqual(sum("cancelada" in m.subject for m in mail.outbox), 5)

    def test_nao_cancela_partida_encerrada_ou_iniciada(self):
        partida = criar_partida()
        partidas.cancelar_partida(partida)
        with self.assertRaisesMessage(ValidationError, "abertas ou lotadas"):
            partidas.cancelar_partida(partida)
        iniciada = criar_partida()
        mover_partida(iniciada, timezone.now() - timedelta(minutes=10))
        with self.assertRaisesMessage(ValidationError, "já começou"):
            partidas.cancelar_partida(iniciada)


class QuorumTest(TestCase):
    def setUp(self):
        self.partida = criar_partida(vagas=10)  # mínimo de 7 (70%), conferido 3h antes
        mover_partida(self.partida, timezone.now() + timedelta(days=1))

    def test_sem_o_minimo_a_partida_e_cancelada_no_prazo(self):
        pagantes = [comprar(self.partida) for _ in range(2)]
        self.assertEqual(self.partida.faltam_para_confirmar, 5)
        antes_do_prazo = self.partida.prazo_quorum - timedelta(minutes=1)
        self.assertEqual(partidas.conferir_quorum(antes_do_prazo), 0)

        self.assertEqual(partidas.conferir_quorum(self.partida.prazo_quorum + timedelta(minutes=1)), 1)
        self.partida.refresh_from_db()
        self.assertEqual((self.partida.status, self.partida.motivo_cancelamento), (StatusPartida.CANCELADA, "quorum"))
        for inscricao in pagantes:
            inscricao.refresh_from_db()
            self.assertEqual(inscricao.status, StatusInscricao.REEMBOLSADA)

    def test_com_o_minimo_o_jogo_e_confirmado(self):
        for _ in range(7):
            comprar(self.partida)
        self.assertTrue(self.partida.jogo_confirmado)
        self.assertEqual(partidas.conferir_quorum(self.partida.prazo_quorum + timedelta(minutes=1)), 0)
        self.partida.refresh_from_db()
        self.assertEqual(self.partida.status, StatusPartida.ABERTA)
        self.assertIsNotNone(self.partida.quorum_conferido_em)


class EncerramentoERepasseTest(TestCase):
    def test_partida_lotada_rende_o_aluguel_cheio_e_e_repassada(self):
        partida = criar_partida(vagas=3, valor_total_aluguel=Decimal("100.00"))  # R$ 33,33 por vaga
        for _ in range(3):
            comprar(partida)
        fim = partida.time_slot.fim
        self.assertEqual(partidas.finalizar_partidas(fim - timedelta(minutes=1)), 0)
        self.assertEqual(partidas.finalizar_partidas(fim + timedelta(minutes=1)), 1)
        partida.refresh_from_db()
        self.assertEqual(partida.status, StatusPartida.FINALIZADA)
        self.assertEqual(saldo_arena(partida), Decimal("100.00"))  # 3 x 33,33 + 0,01 de ajuste
        self.assertEqual(partidas.finalizar_partidas(fim + timedelta(minutes=2)), 0)  # idempotente

        arena = partida.time_slot.court.arena
        self.assertEqual(razao.gerar_repasses(fim + timedelta(hours=1)), [])  # ainda retido
        repasses = razao.gerar_repasses(fim + timedelta(days=1, minutes=1))
        self.assertEqual([r.valor for r in repasses], [Decimal("100.00")])
        saldo = razao.saldo_da_arena(arena, fim + timedelta(days=2))
        self.assertEqual((saldo.disponivel, saldo.a_liberar), (Decimal("0"), Decimal("0")))
        self.assertEqual(razao.gerar_repasses(fim + timedelta(days=2)), [])

    def test_reserva_pendente_expira_no_encerramento(self):
        partida = criar_partida(vagas=3)
        reserva = comprar(partida, pagar=False)
        partidas.finalizar_partidas(partida.time_slot.fim + timedelta(minutes=1))
        reserva.refresh_from_db()
        self.assertEqual(reserva.status, StatusInscricao.EXPIRADA)
        self.assertFalse(LedgerEntry.objects.filter(tipo=TipoLancamento.AJUSTE_FECHAMENTO).exists())
