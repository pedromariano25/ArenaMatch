"""Fábricas de objetos para os testes (sem senha utilizável, para serem rápidas)."""

from datetime import date, time, timedelta
from decimal import Decimal
from itertools import count
from typing import Any

from django.utils import timezone

from arena.models import (
    MEIA_NOITE,
    Arena,
    Court,
    CustomUser,
    OpenMatch,
    StatusHorario,
    TimeSlot,
    TipoPiso,
)
from arena.validators import digitos_verificadores_cnpj

_sequencia = count(1)


def amanha() -> date:
    return timezone.localdate() + timedelta(days=1)


def criar_usuario(**dados: Any) -> CustomUser:
    numero = next(_sequencia)
    dados.setdefault("username", f"usuario{numero}")
    dados.setdefault("first_name", "Usuário")
    dados.setdefault("last_name", f"Teste{numero}")
    return CustomUser.objects.create_user(**dados)


def criar_gestor(**dados: Any) -> CustomUser:
    return criar_usuario(is_manager=True, is_staff=True, **dados)


def criar_jogador(**dados: Any) -> CustomUser:
    return criar_usuario(is_player=True, **dados)


def criar_arena(gestor: CustomUser | None = None, **dados: Any) -> Arena:
    numero = next(_sequencia)
    base = f"{numero:08d}0001"
    valores = {
        "manager": gestor or criar_gestor(),
        "nome": f"Arena {numero}",
        "cnpj": base + digitos_verificadores_cnpj(base),
        "endereco_completo": "Rua Teste, 100 – Centro, São Paulo – SP",
        "telefone_contato": "(11) 3000-0000",
        "hora_abertura": time(8),
        "hora_fechamento": MEIA_NOITE,
    }
    return Arena.objects.create(**(valores | dados))


def criar_quadra(arena: Arena | None = None, **dados: Any) -> Court:
    valores = {
        "arena": arena or criar_arena(),
        "nome_ou_numero": f"Quadra {next(_sequencia)}",
        "tipo_piso": TipoPiso.SINTETICO,
        "capacidade_padrao": 14,
    }
    return Court.objects.create(**(valores | dados))


def criar_horario(
    quadra: Court | None = None,
    inicio: time = time(19),
    fim: time = time(20),
    data: date | None = None,
    **dados: Any,
) -> TimeSlot:
    return TimeSlot.objects.create(
        court=quadra or criar_quadra(),
        data=data or amanha(),
        hora_inicio=inicio,
        hora_fim=fim,
        **dados,
    )


def criar_partida(vagas: int = 2, horario: TimeSlot | None = None, **dados: Any) -> OpenMatch:
    valores = {
        "time_slot": horario or criar_horario(status=StatusHorario.OCIOSO),
        "vagas_totais": vagas,
        "preco_por_vaga": Decimal("25.00"),
    }
    return OpenMatch.objects.create(**(valores | dados))
