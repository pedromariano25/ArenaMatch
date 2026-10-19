"""Razão contábil: carteiras e lançamentos imutáveis.

O saldo de qualquer carteira é a soma dos seus lançamentos. Nada é editado ou
apagado: correções entram como novos lançamentos (estornos). A parte da arena
fica "a liberar" até o dia seguinte à partida e, depois, disponível para repasse.

Na pelada de grupo (C2C), o valor da vaga vai para o saldo do organizador, e
não para a arena (o grupo paga a quadra por fora). Ele também é liberado no dia
seguinte ao jogo e sai por saque via Pix, quando o organizador pedir.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from .formatacao import formatar_brl
from .models import (
    DIAS_RETENCAO_SALDO,
    VALOR_MINIMO_SAQUE,
    ZERO,
    Arena,
    Booking,
    LedgerAccount,
    LedgerEntry,
    MetodoPagamento,
    OpenMatch,
    Payment,
    Payout,
    Saque,
    StatusRepasse,
    TipoConta,
    TipoLancamento,
    Wallet,
)
from .pagamentos import obter_gateway

# --- Carteiras ---------------------------------------------------------------


def carteira_da_arena(arena: Arena) -> LedgerAccount:
    conta, _ = LedgerAccount.objects.get_or_create(tipo=TipoConta.ARENA, arena=arena)
    return conta


def carteira_da_plataforma() -> LedgerAccount:
    conta, _ = LedgerAccount.objects.get_or_create(tipo=TipoConta.PLATAFORMA)
    return conta


def carteira_do_jogador(jogador: AbstractBaseUser) -> LedgerAccount:
    conta, _ = LedgerAccount.objects.get_or_create(tipo=TipoConta.JOGADOR, jogador=jogador)
    return conta


def carteira_do_organizador(usuario: AbstractBaseUser) -> LedgerAccount:
    """Saldo sacável de quem organiza peladas de grupo."""
    conta, _ = LedgerAccount.objects.get_or_create(tipo=TipoConta.ORGANIZADOR, jogador=usuario)
    return conta


def carteira_de_destino(partida: OpenMatch) -> LedgerAccount:
    """Quem recebe a parte da vaga: o organizador (pelada de grupo) ou a arena."""
    if partida.organizador_id is not None:
        return carteira_do_organizador(partida.organizador)
    return carteira_da_arena(partida.time_slot.court.arena)


def bloquear_carteira_do_jogador(jogador: AbstractBaseUser) -> LedgerAccount:
    """Carteira do jogador travada até o fim da transação (gasto de crédito sem corrida)."""
    return LedgerAccount.objects.select_for_update().get(pk=carteira_do_jogador(jogador).pk)


# --- Lançamentos -------------------------------------------------------------


def lancar(
    conta: LedgerAccount,
    tipo: str,
    valor: Decimal,
    descricao: str,
    *,
    disponivel_em: datetime | None = None,
    **referencias: Any,
) -> LedgerEntry | None:
    """Registra um lançamento na carteira. Valores zerados são ignorados."""
    if not valor:
        return None
    return LedgerEntry.objects.create(
        conta=conta,
        tipo=tipo,
        valor=valor,
        descricao=descricao[:255],
        disponivel_em=disponivel_em or timezone.now(),
        **referencias,
    )


def liberacao_da_partida(partida: OpenMatch) -> datetime:
    """Quando a parte da arena numa partida fica disponível para repasse."""
    return partida.time_slot.fim + timedelta(days=DIAS_RETENCAO_SALDO)


def _descricao(inscricao: Booking) -> str:
    horario = inscricao.open_match.time_slot
    return (
        f"{inscricao.player.nome_publico} · {horario.data:%d/%m} {horario.intervalo} · "
        f"{horario.court.nome_ou_numero}"
    )


def registrar_venda(inscricao: Booking, pagamento: Payment | None) -> None:
    """Lança uma vaga paga: parte da arena (a liberar), taxa, acréscimo e tarifa do gateway."""
    partida = inscricao.open_match
    descricao = _descricao(inscricao)
    referencias = {"partida": partida, "inscricao": inscricao, "pagamento": pagamento}
    if inscricao.metodo_pagamento == MetodoPagamento.CREDITO:
        lancar(
            carteira_do_jogador(inscricao.player),
            TipoLancamento.USO_CREDITO,
            -inscricao.valor_total,
            f"Vaga · {descricao}",
            **referencias,
        )
    lancar(
        carteira_de_destino(partida),
        TipoLancamento.VENDA_VAGA,
        inscricao.valor_vaga,
        descricao,
        disponivel_em=liberacao_da_partida(partida),
        **referencias,
    )
    plataforma = carteira_da_plataforma()
    lancar(plataforma, TipoLancamento.TAXA_SERVICO, inscricao.valor_taxa, descricao, **referencias)
    lancar(plataforma, TipoLancamento.ACRESCIMO_CARTAO, inscricao.valor_acrescimo, descricao, **referencias)
    if pagamento is not None:
        registrar_tarifa(pagamento)


def registrar_tarifa(pagamento: Payment) -> None:
    """Lança a tarifa do gateway como custo da plataforma (ela não volta em estornos)."""
    inscricao = pagamento.booking
    lancar(
        carteira_da_plataforma(),
        TipoLancamento.TARIFA_GATEWAY,
        -pagamento.tarifa_gateway,
        f"Tarifa · {_descricao(inscricao)}",
        partida=inscricao.open_match,
        inscricao=inscricao,
        pagamento=pagamento,
    )


def registrar_estorno(inscricao: Booking, *, credito: bool) -> None:
    """Desfaz a venda de uma vaga. Com ``credito``, o jogador recebe o valor como crédito."""
    partida = inscricao.open_match
    descricao = f"Estorno · {_descricao(inscricao)}"
    referencias = {"partida": partida, "inscricao": inscricao}
    lancar(
        carteira_de_destino(partida),
        TipoLancamento.ESTORNO,
        -inscricao.valor_vaga,
        descricao,
        disponivel_em=liberacao_da_partida(partida),
        **referencias,
    )
    lancar(
        carteira_da_plataforma(),
        TipoLancamento.ESTORNO,
        -(inscricao.valor_taxa + inscricao.valor_acrescimo),
        descricao,
        **referencias,
    )
    if credito:
        lancar(
            carteira_do_jogador(inscricao.player),
            TipoLancamento.CREDITO,
            inscricao.valor_total,
            f"Crédito · {_descricao(inscricao)}",
            **referencias,
        )


def registrar_ajuste_fechamento(partida: OpenMatch) -> Decimal:
    """Credita à arena o resíduo do rateio quando todas as vagas de linha foram pagas.

    Idempotente: cada partida recebe no máximo um ajuste.
    """
    if LedgerEntry.objects.filter(partida=partida, tipo=TipoLancamento.AJUSTE_FECHAMENTO).exists():
        return ZERO
    ajuste = partida.ajuste_repasse_fechamento
    if not ajuste:
        return ZERO
    horario = partida.time_slot
    descricao = f"Ajuste de centavos do rateio · {horario.data:%d/%m} {horario.intervalo}"
    lancar(
        carteira_de_destino(partida),
        TipoLancamento.AJUSTE_FECHAMENTO,
        ajuste,
        descricao,
        disponivel_em=liberacao_da_partida(partida),
        partida=partida,
    )
    lancar(carteira_da_plataforma(), TipoLancamento.AJUSTE_FECHAMENTO, -ajuste, descricao, partida=partida)
    return ajuste


# --- Saldos e extratos -------------------------------------------------------


def saldo(lancamentos: QuerySet[LedgerEntry]) -> Decimal:
    return lancamentos.aggregate(total=Sum("valor"))["total"] or ZERO


def saldo_do_jogador(jogador: AbstractBaseUser) -> Decimal:
    """Crédito do jogador disponível para pagar vagas."""
    return saldo(LedgerEntry.objects.filter(conta__tipo=TipoConta.JOGADOR, conta__jogador=jogador))


@dataclass(frozen=True)
class SaldoArena:
    """Saldo da carteira de uma arena."""

    disponivel: Decimal
    a_liberar: Decimal
    repassado_no_mes: Decimal


def saldo_da_arena(arena: Arena, agora: datetime | None = None) -> SaldoArena:
    agora = agora or timezone.now()
    totais = LedgerEntry.objects.filter(conta__tipo=TipoConta.ARENA, conta__arena=arena).aggregate(
        disponivel=Sum("valor", filter=Q(disponivel_em__lte=agora)),
        a_liberar=Sum("valor", filter=Q(disponivel_em__gt=agora)),
    )
    inicio_do_mes = timezone.localtime(agora).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    repassado = Payout.objects.filter(
        arena=arena, status=StatusRepasse.PAGO, created_at__gte=inicio_do_mes
    ).aggregate(total=Sum("valor"))["total"]
    return SaldoArena(totais["disponivel"] or ZERO, totais["a_liberar"] or ZERO, repassado or ZERO)


def extrato_da_arena(arena: Arena) -> QuerySet[LedgerEntry]:
    """Lançamentos da carteira da arena, do mais recente para o mais antigo."""
    return (
        LedgerEntry.objects.filter(conta__tipo=TipoConta.ARENA, conta__arena=arena)
        .select_related("inscricao__player", "partida__time_slot__court", "repasse")
        .order_by("-created_at")
    )


@dataclass(frozen=True)
class SaldoOrganizador:
    """Saldo de quem organiza peladas de grupo."""

    disponivel: Decimal
    a_liberar: Decimal
    sacado: Decimal


def saldo_do_organizador(usuario: AbstractBaseUser, agora: datetime | None = None) -> SaldoOrganizador:
    agora = agora or timezone.now()
    lancamentos = LedgerEntry.objects.filter(conta__tipo=TipoConta.ORGANIZADOR, conta__jogador=usuario)
    totais = lancamentos.aggregate(
        disponivel=Sum("valor", filter=Q(disponivel_em__lte=agora)),
        a_liberar=Sum("valor", filter=Q(disponivel_em__gt=agora)),
        sacado=Sum("valor", filter=Q(tipo=TipoLancamento.SAQUE)),
    )
    return SaldoOrganizador(totais["disponivel"] or ZERO, totais["a_liberar"] or ZERO, -(totais["sacado"] or ZERO))


def extrato_do_organizador(usuario: AbstractBaseUser) -> QuerySet[LedgerEntry]:
    return (
        LedgerEntry.objects.filter(conta__tipo=TipoConta.ORGANIZADOR, conta__jogador=usuario)
        .select_related("inscricao__player", "partida__time_slot__court__arena")
        .order_by("-created_at")
    )


def extrato_do_jogador(jogador: AbstractBaseUser) -> QuerySet[LedgerEntry]:
    return (
        LedgerEntry.objects.filter(conta__tipo=TipoConta.JOGADOR, conta__jogador=jogador)
        .select_related("partida__time_slot__court__arena")
        .order_by("-created_at")
    )


# --- Repasses ----------------------------------------------------------------


def gerar_repasses(agora: datetime | None = None) -> list[Payout]:
    """Transfere a cada arena o saldo já liberado (rotina do agendador)."""
    agora = agora or timezone.now()
    gateway = obter_gateway()
    repasses = []
    for conta_id in LedgerAccount.objects.filter(tipo=TipoConta.ARENA).values_list("pk", flat=True):
        with transaction.atomic():
            conta = LedgerAccount.objects.select_for_update().get(pk=conta_id)
            disponivel = saldo(conta.lancamentos.filter(disponivel_em__lte=agora))
            if disponivel <= 0:
                continue
            referencia = gateway.transferir(conta.arena, disponivel)
            repasse = Payout.objects.create(arena=conta.arena, valor=disponivel, referencia=referencia)
            lancar(
                conta,
                TipoLancamento.REPASSE,
                -disponivel,
                f"Repasse · {referencia}",
                disponivel_em=agora,
                repasse=repasse,
            )
            repasses.append(repasse)
    return repasses


# --- Saques do organizador ----------------------------------------------------


def solicitar_saque(usuario: AbstractBaseUser, agora: datetime | None = None) -> Saque:
    """Transfere via Pix todo o saldo disponível do organizador.

    Raises:
        ValidationError: sem chave Pix cadastrada ou saldo abaixo do mínimo.
    """
    agora = agora or timezone.now()
    wallet = Wallet.objects.filter(usuario=usuario).first()
    if wallet is None or not wallet.pode_sacar:
        raise ValidationError("Cadastre uma chave Pix para sacar.")
    with transaction.atomic():
        conta = LedgerAccount.objects.select_for_update().get(pk=carteira_do_organizador(usuario).pk)
        disponivel = saldo(conta.lancamentos.filter(disponivel_em__lte=agora))
        if disponivel < VALOR_MINIMO_SAQUE:
            raise ValidationError(
                f"O saque mínimo é de {formatar_brl(VALOR_MINIMO_SAQUE)}. "
                f"Você tem {formatar_brl(disponivel)} disponível."
            )
        referencia = obter_gateway().transferir_pix(wallet.chave_pix, disponivel)
        saque = Saque.objects.create(
            wallet=wallet,
            valor=disponivel,
            tipo_chave_pix=wallet.tipo_chave_pix,
            chave_pix=wallet.chave_pix,
            referencia=referencia,
        )
        lancar(conta, TipoLancamento.SAQUE, -disponivel, f"Saque via Pix · {referencia}", disponivel_em=agora)
    return saque
