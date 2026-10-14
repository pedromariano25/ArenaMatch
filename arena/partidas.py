"""Ciclo de vida da partida: cancelamento com reembolso, mínimo de jogadores e encerramento."""

from datetime import datetime, timedelta
from functools import partial

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import checkout, notificacoes, razao
from .models import (
    STATUS_INSCRICAO_ATIVA,
    STATUS_PARTIDA_ATIVA,
    Booking,
    MetodoPagamento,
    MotivoCancelamento,
    OpenMatch,
    StatusInscricao,
    StatusPagamento,
    StatusPartida,
)
from .pagamentos import obter_gateway

# O prazo do mínimo de jogadores é de até 48h antes do jogo (validador da arena).
JANELA_DO_QUORUM = timedelta(hours=48)


def cancelar_partida(partida: OpenMatch, motivo: str = MotivoCancelamento.ARENA) -> int:
    """Cancela a partida e devolve o dinheiro de todos os inscritos.

    Quem pagou com Pix ou cartão recebe o estorno pela mesma forma; quem pagou
    com crédito recebe o crédito de volta. Reservas em pagamento são canceladas.
    Devolve quantos jogadores foram reembolsados.

    Raises:
        ValidationError: partida já encerrada ou já iniciada.
    """
    gateway = obter_gateway()
    with transaction.atomic():
        partida = OpenMatch.objects.select_for_update().select_related("time_slot").get(pk=partida.pk)
        if partida.status not in STATUS_PARTIDA_ATIVA:
            raise ValidationError("Só é possível cancelar partidas abertas ou lotadas.")
        if partida.time_slot.ja_comecou:
            raise ValidationError("A partida já começou e não pode mais ser cancelada.")

        agora = timezone.now()
        afetadas: list[Booking] = []
        inscricoes = Booking.objects.select_for_update(of=("self",)).filter(
            open_match=partida, status__in=STATUS_INSCRICAO_ATIVA
        )
        for inscricao in inscricoes.select_related("player"):
            if inscricao.status == StatusInscricao.AGUARDANDO_PAGAMENTO:
                inscricao.status = StatusInscricao.CANCELADA
                for pagamento in inscricao.pagamentos.filter(status=StatusPagamento.PENDENTE):
                    pagamento.status = StatusPagamento.CANCELADO
                    pagamento.save()
                    transaction.on_commit(partial(gateway.cancelar, pagamento))
            elif inscricao.gratuita:
                inscricao.status = StatusInscricao.CANCELADA
            else:
                credito = inscricao.metodo_pagamento == MetodoPagamento.CREDITO
                razao.registrar_estorno(inscricao, credito=credito)
                if not credito:
                    for pagamento in inscricao.pagamentos.filter(status=StatusPagamento.APROVADO):
                        pagamento.status = StatusPagamento.ESTORNADO
                        pagamento.estornado_em = agora
                        pagamento.save()
                        transaction.on_commit(partial(gateway.estornar, pagamento))
                inscricao.status = StatusInscricao.REEMBOLSADA
            inscricao.cancelada_em = agora
            inscricao.save()
            afetadas.append(inscricao)

        partida.refresh_from_db()
        partida.status = StatusPartida.CANCELADA
        partida.motivo_cancelamento = motivo
        partida.cancelada_em = agora
        partida.save()
        partida.lista_de_espera.all().delete()
        notificacoes.avisar_partida_cancelada(partida, afetadas)
    return sum(1 for inscricao in afetadas if inscricao.status == StatusInscricao.REEMBOLSADA)


def conferir_quorum(agora: datetime | None = None) -> int:
    """No prazo, confirma as partidas com o mínimo de pagos e cancela as demais (rotina).

    Devolve quantas partidas foram canceladas.
    """
    agora = agora or timezone.now()
    candidatas = OpenMatch.objects.filter(
        status__in=STATUS_PARTIDA_ATIVA,
        quorum_conferido_em__isnull=True,
        time_slot__data__lte=timezone.localdate(agora + JANELA_DO_QUORUM),
    ).select_related("time_slot")
    canceladas = 0
    for partida in candidatas:
        if partida.time_slot.inicio <= agora or partida.prazo_quorum > agora:
            continue
        if partida.jogo_confirmado:
            OpenMatch.objects.filter(pk=partida.pk).update(quorum_conferido_em=agora)
        else:
            cancelar_partida(partida, MotivoCancelamento.QUORUM)
            canceladas += 1
    return canceladas


def finalizar_partidas(agora: datetime | None = None) -> int:
    """Encerra as partidas que já terminaram e credita o ajuste de fechamento (rotina)."""
    agora = agora or timezone.now()
    candidatas = OpenMatch.objects.filter(
        status__in=STATUS_PARTIDA_ATIVA, time_slot__data__lte=timezone.localdate(agora)
    ).select_related("time_slot")
    finalizadas = 0
    for candidata in candidatas:
        if candidata.time_slot.fim > agora:
            continue
        with transaction.atomic():
            partida = OpenMatch.objects.select_for_update().get(pk=candidata.pk)
            if partida.status not in STATUS_PARTIDA_ATIVA:
                continue
            checkout.expirar_reservas_da_partida(partida, agora)
            partida.refresh_from_db()
            partida.status = StatusPartida.FINALIZADA
            partida.save()
            razao.registrar_ajuste_fechamento(partida)
            finalizadas += 1
    return finalizadas
