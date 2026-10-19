"""Pelada de grupo (C2C): o organizador vende as vagas que faltam no seu grupo.

O grupo já tem o horário com a arena (mensalista) e paga a quadra por fora. O
organizador abre só as vagas que faltam, com o valor que quer receber por vaga.
O jogador avulso paga esse valor mais a taxa da plataforma (``TAXA_C2C_*``), e a
parte do organizador entra no saldo dele, liberada no dia seguinte ao jogo para
saque via Pix.

Diferenças em relação à partida da arena:

- acontece no horário de mensalista do grupo, que aparece na agenda da arena;
- não é cancelada por falta de quórum: o grupo joga mesmo sem vender as vagas;
- a vaga de goleiro pode ter preço próprio (ou ser grátis, como na arena).
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, QuerySet, Sum
from django.utils import timezone

from . import partidas, razao
from .models import (
    TAXA_C2C_MINIMA,
    TAXA_C2C_PERCENTUAL,
    Court,
    MotivoCancelamento,
    NivelCompetitividade,
    OpenMatch,
    StatusHorario,
    StatusInscricao,
    StatusPartida,
    TimeSlot,
    TipoReserva,
    Wallet,
)

# Até quantos dias à frente o organizador pode abrir vagas.
DIAS_DE_ANTECEDENCIA = 30
# Prazo do mínimo (só usado na liberação da trava de nível: pelada de grupo não tem quórum).
HORAS_PRAZO_PELADA = 3


def _horario_do_grupo(quadra: Court, dia: date, inicio: time, fim: time) -> TimeSlot:
    """Horário de mensalista do grupo na quadra: o já cadastrado pela arena ou um novo."""
    horario = TimeSlot.objects.filter(court=quadra, data=dia, hora_inicio=inicio).first()
    if horario is None:
        return TimeSlot.objects.create(
            court=quadra,
            data=dia,
            hora_inicio=inicio,
            hora_fim=fim,
            tipo_reserva=TipoReserva.MENSALISTA,
            status=StatusHorario.CONFIRMADO,
        )
    if (
        horario.tipo_reserva != TipoReserva.MENSALISTA
        or horario.status != StatusHorario.CONFIRMADO
        or horario.hora_fim != fim
    ):
        raise ValidationError(
            "Este horário não está reservado para um grupo nesta quadra. Confira o dia e o horário "
            "combinados com a arena."
        )
    return horario


@transaction.atomic
def criar_pelada(
    organizador: AbstractBaseUser,
    quadra: Court,
    dia: date,
    inicio: time,
    fim: time,
    *,
    titulo: str,
    vagas_linha: int,
    valor_por_vaga: Decimal,
    vagas_goleiro: int = 0,
    valor_goleiro: Decimal = Decimal("0"),
    nivel: str = NivelCompetitividade.ABERTA,
) -> OpenMatch:
    """Publica as vagas que faltam na pelada do grupo.

    Raises:
        ValidationError: horário passado ou longe demais, horário ocupado na quadra
            ou já com outra partida.
    """
    comeca = timezone.make_aware(datetime.combine(dia, inicio))
    agora = timezone.now()
    if comeca <= agora:
        raise ValidationError("Este horário já começou.")
    if comeca > agora + timedelta(days=DIAS_DE_ANTECEDENCIA):
        raise ValidationError(f"Abra as vagas com até {DIAS_DE_ANTECEDENCIA} dias de antecedência.")
    if vagas_linha < 1:
        raise ValidationError("Abra pelo menos uma vaga de linha.")

    horario = _horario_do_grupo(quadra, dia, inicio, fim)
    valores = {
        "organizador": organizador,
        "titulo": titulo.strip(),
        "vagas_totais": vagas_linha + vagas_goleiro,
        "vagas_goleiro": vagas_goleiro,
        "valor_total_aluguel": valor_por_vaga * vagas_linha,
        "valor_vaga_goleiro": valor_goleiro,
        "nivel_competitividade": nivel,
        "taxa_plataforma_percentual": TAXA_C2C_PERCENTUAL,
        "taxa_minima": TAXA_C2C_MINIMA,
        # Sem quórum: o grupo joga mesmo que nenhuma vaga seja vendida.
        "quorum_percentual": 0,
        "horas_prazo_quorum": HORAS_PRAZO_PELADA,
    }
    partida = OpenMatch.objects.filter(time_slot=horario).first()
    if partida is None:
        return OpenMatch.objects.create(time_slot=horario, **valores)
    # Reabrir uma pelada cancelada do mesmo organizador no mesmo horário.
    if partida.status != StatusPartida.CANCELADA or partida.organizador_id != organizador.pk:
        raise ValidationError("Este horário já tem uma partida no ArenaMatch.")
    for campo, valor in valores.items():
        setattr(partida, campo, valor)
    partida.status = StatusPartida.ABERTA
    partida.motivo_cancelamento, partida.cancelada_em, partida.quorum_conferido_em = "", None, None
    partida.save()
    return partida


def cancelar_pelada(pelada: OpenMatch, organizador: AbstractBaseUser) -> int:
    """O organizador desiste das vagas: todos os inscritos recebem o dinheiro de volta.

    Raises:
        ValidationError: a pelada não é deste organizador, já começou ou já acabou.
    """
    if pelada.organizador_id != organizador.pk:
        raise ValidationError("Só o organizador pode cancelar esta pelada.")
    return partidas.cancelar_partida(pelada, MotivoCancelamento.ORGANIZADOR)


def peladas_do(organizador: AbstractBaseUser) -> QuerySet[OpenMatch]:
    """Peladas do organizador com vagas vendidas e o valor que ele recebe."""
    pagas = Q(inscricoes__status=StatusInscricao.CONFIRMADA)
    return (
        OpenMatch.objects.filter(organizador=organizador)
        .com_relacionados()
        .com_confirmados()
        .annotate(
            arrecadado=Sum("inscricoes__valor_vaga", filter=pagas),
            em_pagamento=Count(
                "inscricoes", filter=Q(inscricoes__status=StatusInscricao.AGUARDANDO_PAGAMENTO)
            ),
        )
        .order_by("-time_slot__data", "-time_slot__hora_inicio")
    )


def wallet_do(usuario: AbstractBaseUser) -> Wallet:
    wallet, _ = Wallet.objects.get_or_create(usuario=usuario)
    return wallet


def resumo_do_organizador(usuario: AbstractBaseUser) -> dict:
    """Carteira, saldos, saques e peladas (próximas e anteriores) do organizador."""
    agora = timezone.now()
    proximas, anteriores = [], []
    for pelada in peladas_do(usuario):
        (anteriores if pelada.time_slot.inicio <= agora else proximas).append(pelada)
    wallet = wallet_do(usuario)
    return {
        "wallet": wallet,
        "saldo": razao.saldo_do_organizador(usuario, agora),
        "saques": list(wallet.saques.all()[:5]),
        "proximas": proximas[::-1],
        "anteriores": anteriores,
    }


