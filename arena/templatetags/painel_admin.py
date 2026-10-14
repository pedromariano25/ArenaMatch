"""Indicadores do painel do gestor (página inicial do Django Admin)."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django import template
from django.contrib.auth.models import AbstractBaseUser
from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from ..models import (
    STATUS_PARTIDA_ATIVA,
    Booking,
    OpenMatch,
    StatusHorario,
    StatusPagamento,
    TimeSlot,
)

register = template.Library()


def _escopo(queryset: QuerySet, usuario: AbstractBaseUser, caminho_gestor: str) -> QuerySet:
    """Superusuários veem tudo; gestores, só as próprias arenas."""
    if usuario.is_superuser:
        return queryset
    return queryset.filter(**{caminho_gestor: usuario})


@register.simple_tag(takes_context=True)
def indicadores_painel(context: dict[str, Any]) -> dict[str, Any]:
    """Resumo dos próximos 7 dias: partidas, ocupação, receita e horários ociosos."""
    usuario = context["request"].user
    hoje = timezone.localdate()
    periodo = (hoje, hoje + timedelta(days=6))

    partidas = _escopo(OpenMatch.objects.all(), usuario, "time_slot__court__arena__manager")
    ativas = partidas.filter(status__in=STATUS_PARTIDA_ATIVA, time_slot__data__range=periodo)
    vagas = ativas.aggregate(totais=Sum("vagas_totais"), livres=Sum("vagas_disponiveis"))

    inscricoes = _escopo(
        Booking.objects.all(), usuario, "open_match__time_slot__court__arena__manager"
    ).filter(
        open_match__status__in=STATUS_PARTIDA_ATIVA,
        open_match__time_slot__data__range=periodo,
    )
    receita = inscricoes.aggregate(
        paga=Sum("valor_vaga", filter=Q(status_pagamento=StatusPagamento.PAGO)),
        pendente=Sum(
            "valor_vaga", filter=Q(status_pagamento=StatusPagamento.PENDENTE)
        ),
    )

    ociosos = _escopo(TimeSlot.objects.all(), usuario, "court__arena__manager").filter(
        status=StatusHorario.OCIOSO, partida_aberta__isnull=True, data__gte=hoje
    )

    return {
        "partidas_hoje": ativas.filter(time_slot__data=hoje).count(),
        "vagas_totais": vagas["totais"] or 0,
        "vagas_ocupadas": (vagas["totais"] or 0) - (vagas["livres"] or 0),
        "receita_paga": receita["paga"] or Decimal("0"),
        "receita_pendente": receita["pendente"] or Decimal("0"),
        "horarios_ociosos": ociosos.count(),
        "proximas": list(
            partidas.futuras()
            .filter(status__in=STATUS_PARTIDA_ATIVA)
            .com_relacionados()
            .order_by("time_slot__data", "time_slot__hora_inicio")[:6]
        ),
    }
