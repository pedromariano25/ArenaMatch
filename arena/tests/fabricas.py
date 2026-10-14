"""Fábricas de objetos para os testes (sem senha utilizável, para serem rápidas)."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import count
from typing import Any

from django.utils import timezone

from arena import checkout
from arena.models import (
    MEIA_NOITE,
    Arena,
    Booking,
    Court,
    CustomUser,
    MetodoPagamento,
    OpenMatch,
    PlayerProfile,
    Posicao,
    PosicaoJogador,
    StatusHorario,
    StatusInscricao,
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
    dados.setdefault("email", f"{dados['username']}@example.com")
    dados.setdefault("first_name", "Usuário")
    dados.setdefault("last_name", f"Teste{numero}")
    return CustomUser.objects.create_user(**dados)


def criar_gestor(**dados: Any) -> CustomUser:
    return criar_usuario(is_manager=True, is_staff=True, **dados)


def criar_jogador(
    nivel: int | None = 3,
    posicao: str = PosicaoJogador.MEIO,
    joga_no_gol: bool = True,
    **dados: Any,
) -> CustomUser:
    """Jogador com perfil (nível 3, meio-campo, topa o gol); ``nivel=None`` cria sem perfil."""
    jogador = criar_usuario(is_player=True, **dados)
    if nivel is not None:
        PlayerProfile.objects.create(jogador=jogador, nivel=nivel, posicao=posicao, joga_no_gol=joga_no_gol)
    return jogador


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
    """Partida só com vagas de linha (R$ 25,00 de quadra por vaga), salvo indicação."""
    valores = {
        "time_slot": horario or criar_horario(status=StatusHorario.OCIOSO),
        "vagas_totais": vagas,
        "valor_total_aluguel": Decimal("25.00") * (vagas - dados.get("vagas_goleiro", 0)),
    }
    return OpenMatch.objects.create(**(valores | dados))


def inscrever(partida: OpenMatch, jogador: CustomUser | None = None, **dados: Any) -> Booking:
    """Inscrição confirmada direto no banco (sem pagamento nem razão), para testar vagas."""
    dados.setdefault("status", StatusInscricao.CONFIRMADA)
    return Booking.objects.create(open_match=partida, player=jogador or criar_jogador(), **dados)


def comprar(
    partida: OpenMatch,
    jogador: CustomUser | None = None,
    metodo: str = MetodoPagamento.PIX,
    posicao: str = Posicao.LINHA,
    pagar: bool = True,
) -> Booking:
    """Checkout completo, como o jogador faria; com ``pagar``, aprova o Pix na hora."""
    inscricao = checkout.iniciar_checkout(partida, jogador or criar_jogador(), posicao=posicao, metodo=metodo)
    if pagar and inscricao.status == StatusInscricao.AGUARDANDO_PAGAMENTO:
        inscricao = checkout.simular_pagamento(inscricao)
    return inscricao


def mover_partida(partida: OpenMatch, inicio: datetime) -> None:
    """Muda o horário da partida sem validação (para simular jogos próximos ou passados)."""
    inicio = timezone.localtime(inicio).replace(second=0, microsecond=0)
    termino = inicio + timedelta(hours=1)
    # Jogos que passariam da meia-noite terminam às 00:00 (fim do dia).
    fim = termino.time() if termino.date() == inicio.date() else MEIA_NOITE
    TimeSlot.objects.filter(pk=partida.time_slot_id).update(
        data=inicio.date(), hora_inicio=inicio.time(), hora_fim=fim
    )
    partida.time_slot.refresh_from_db()
