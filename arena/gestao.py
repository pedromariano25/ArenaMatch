"""Cálculos e ações do Portal do Gestor (ArenaManager).

Concentra indicadores, grade semanal da agenda e financeiro para manter as views
enxutas. O gestor vê o valor líquido da quadra (parte do aluguel em cada vaga,
congelada na inscrição). O dinheiro vem do razão contábil: vendas "a liberar"
até o dia seguinte à partida, saldo disponível e repasses.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum

from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from . import razao
from .models import (
    MEIA_NOITE,
    STATUS_HORARIO_LIVRE,
    STATUS_PARTIDA_ATIVA,
    ZERO,
    Arena,
    Booking,
    Court,
    LedgerEntry,
    OpenMatch,
    Posicao,
    StatusHorario,
    StatusInscricao,
    StatusPartida,
    TimeSlot,
    TipoConta,
    TipoLancamento,
    TipoPiso,
    TipoReserva,
)

DIAS_DA_SEMANA = 7
# Aluguel sugerido por hora quando a quadra ainda não abriu nenhuma partida.
ALUGUEL_PADRAO_POR_PISO = {
    TipoPiso.SINTETICO: Decimal("250"),
    TipoPiso.SALAO: Decimal("180"),
    TipoPiso.AREIA: Decimal("160"),
    TipoPiso.CAMPO: Decimal("400"),
}
# Lançamentos da arena que compõem as vendas (o repasse só move o saldo).
TIPOS_DE_VENDA = (TipoLancamento.VENDA_VAGA, TipoLancamento.ESTORNO, TipoLancamento.AJUSTE_FECHAMENTO)


class TipoCelula(StrEnum):
    """Situação de uma faixa de horário na grade da agenda."""

    MENSALISTA = "mensalista"
    AVULSO = "avulso"
    BLOQUEADO = "bloqueado"
    PARTIDA = "partida"
    LOTADA = "lotada"
    VAGO = "vago"
    ENCERRADO = "encerrado"


ROTULOS_CELULA = {
    TipoCelula.MENSALISTA: "Mensalista",
    TipoCelula.AVULSO: "Avulso",
    TipoCelula.BLOQUEADO: "Bloqueado",
    TipoCelula.PARTIDA: "Partida aberta",
    TipoCelula.LOTADA: "Partida lotada",
    TipoCelula.VAGO: "Vago",
    TipoCelula.ENCERRADO: "Encerrado",
}

_TIPO_POR_RESERVA = {
    TipoReserva.MENSALISTA: TipoCelula.MENSALISTA,
    TipoReserva.AVULSO: TipoCelula.AVULSO,
    TipoReserva.BLOQUEADO: TipoCelula.BLOQUEADO,
}


@dataclass(frozen=True)
class Celula:
    """Uma faixa de horário de uma quadra em um dia."""

    quadra: Court
    dia: date
    inicio: time
    fim: time
    tipo: TipoCelula
    horario: TimeSlot | None = None
    partida: OpenMatch | None = None
    garantido: Decimal = ZERO

    @property
    def rotulo(self) -> str:
        return ROTULOS_CELULA[self.tipo]

    @property
    def intervalo(self) -> str:
        return f"{self.inicio:%H:%M}–{self.fim:%H:%M}"


@dataclass(frozen=True)
class LinhaGrade:
    """Uma linha da grade semanal: a mesma faixa de horário nos 7 dias."""

    inicio: time
    celulas: list[Celula]


@dataclass(frozen=True)
class Indicadores:
    """KPIs do dashboard."""

    vendido_mes: Decimal
    vagas_vendidas_mes: int
    a_liberar: Decimal
    disponivel: Decimal
    horarios_vagos: int
    aluguel_por_horario: Decimal
    horarios_mensalistas: int
    quadras_com_mensalistas: int


@dataclass(frozen=True)
class ResumoPartida:
    """Partida aberta com o valor da quadra já garantido (pago) e em pagamento."""

    partida: OpenMatch
    garantido: Decimal
    em_pagamento: Decimal

    @property
    def percentual_do_aluguel(self) -> int:
        """Quanto do aluguel já foi pago (0 a 100), para a barra de progresso."""
        aluguel = self.partida.valor_total_aluguel
        return min(100, round(100 * self.garantido / aluguel)) if aluguel else 0


# --- Escopo e preços ---------------------------------------------------------


def arenas_do_usuario(usuario: AbstractBaseUser) -> QuerySet[Arena]:
    """Arenas que o usuário administra (superusuários veem todas)."""
    arenas = Arena.objects.order_by("nome")
    return arenas if usuario.is_superuser else arenas.filter(manager=usuario)


def aluguel_sugerido(quadra: Court) -> Decimal:
    """Último aluguel praticado na quadra ou um padrão pelo tipo de piso."""
    ultimo = (
        OpenMatch.objects.filter(time_slot__court=quadra)
        .order_by("-created_at")
        .values_list("valor_total_aluguel", flat=True)
        .first()
    )
    return ultimo or ALUGUEL_PADRAO_POR_PISO.get(quadra.tipo_piso, Decimal("200"))


def vagas_goleiro_sugeridas(vagas: int) -> int:
    """Dois goleiros a partir de 8 jogadores (futsal, society, campo); nenhum abaixo disso."""
    return 2 if vagas >= 8 else 0


def inicio_da_semana(dia: date) -> date:
    """Segunda-feira da semana de ``dia``."""
    return dia - timedelta(days=dia.weekday())


# --- Agenda ------------------------------------------------------------------


def _horas_de_funcionamento(arena: Arena) -> range:
    """Horas cheias de funcionamento (fechamento às 00:00 = meia-noite)."""
    abertura = arena.hora_abertura.hour
    fechamento = 24 if arena.hora_fechamento == MEIA_NOITE else arena.hora_fechamento.hour
    return range(abertura, fechamento if fechamento > abertura else 24)


def _partida_do_horario(horario: TimeSlot) -> OpenMatch | None:
    try:
        return horario.partida_aberta
    except OpenMatch.DoesNotExist:
        return None


def _garantido_por_partida(partidas: list[OpenMatch]) -> dict:
    """Valor da quadra já pago em cada partida (com o ajuste de fechamento, se lotou)."""
    pagas = (
        Booking.objects.filter(open_match__in=partidas, status=StatusInscricao.CONFIRMADA)
        .values("open_match_id")
        .annotate(total=Sum("valor_vaga"))
    )
    totais = {linha["open_match_id"]: linha["total"] for linha in pagas}
    for partida in partidas:
        if partida.pk in totais:
            totais[partida.pk] += partida.ajuste_repasse_fechamento
    return totais


def _celula(
    quadra: Court,
    dia: date,
    hora: int,
    horario: TimeSlot | None,
    agora: datetime,
    garantido: dict,
) -> Celula:
    inicio, fim = time(hora), time((hora + 1) % 24)
    if horario is not None:
        inicio, fim = horario.hora_inicio, horario.hora_fim
    passou = timezone.make_aware(datetime.combine(dia, inicio)) <= agora
    livre = TipoCelula.ENCERRADO if passou else TipoCelula.VAGO
    if horario is None:
        return Celula(quadra, dia, inicio, fim, livre)

    partida = _partida_do_horario(horario)
    if partida is not None and partida.status != StatusPartida.CANCELADA:
        tipo = TipoCelula.LOTADA if partida.status == StatusPartida.LOTADA else TipoCelula.PARTIDA
        return Celula(quadra, dia, inicio, fim, tipo, horario, partida, garantido.get(partida.pk, ZERO))
    if horario.status == StatusHorario.CONFIRMADO:
        return Celula(quadra, dia, inicio, fim, _TIPO_POR_RESERVA[horario.tipo_reserva], horario)
    return Celula(quadra, dia, inicio, fim, livre, horario)


def grade_da_quadra(quadra: Court, dias: list[date]) -> list[LinhaGrade]:
    """Grade de horários da quadra nos dias informados (uma linha por hora cheia).

    Horas sem reserva dentro do funcionamento aparecem como vagas, prontas para
    virar partida aberta. Horários cadastrados fora do funcionamento também entram.
    """
    horarios = list(
        TimeSlot.objects.filter(court=quadra, data__range=(dias[0], dias[-1])).select_related(
            "partida_aberta"
        )
    )
    por_posicao = {(h.data, h.hora_inicio.hour): h for h in horarios}
    partidas = [p for h in horarios if (p := _partida_do_horario(h)) is not None]
    garantido = _garantido_por_partida(partidas)
    horas = sorted(set(_horas_de_funcionamento(quadra.arena)) | {h.hora_inicio.hour for h in horarios})
    agora = timezone.localtime()
    return [
        LinhaGrade(
            inicio=time(hora),
            celulas=[
                _celula(quadra, dia, hora, por_posicao.get((dia, hora)), agora, garantido)
                for dia in dias
            ],
        )
        for hora in horas
    ]


def contagem_por_tipo(linhas: list[LinhaGrade]) -> Counter:
    """Quantidade de faixas por tipo (para o resumo da semana)."""
    return Counter(celula.tipo for linha in linhas for celula in linha.celulas)


def agenda_de_hoje(arena: Arena) -> list[Celula]:
    """Reservas e partidas de hoje em todas as quadras, em ordem de horário."""
    hoje = timezone.localdate()
    celulas = [
        celula
        for quadra in arena.quadras.all()
        for linha in grade_da_quadra(quadra, [hoje])
        for celula in linha.celulas
        if celula.tipo not in (TipoCelula.VAGO, TipoCelula.ENCERRADO)
    ]
    return sorted(celulas, key=lambda c: (c.inicio, c.quadra.nome_ou_numero))


# --- Indicadores e financeiro -------------------------------------------------


def _vendas_do_mes(arena: Arena, dia: date) -> QuerySet[LedgerEntry]:
    """Lançamentos de venda da arena em partidas do mês de ``dia``."""
    return LedgerEntry.objects.filter(
        conta__tipo=TipoConta.ARENA,
        conta__arena=arena,
        tipo__in=TIPOS_DE_VENDA,
        partida__time_slot__data__year=dia.year,
        partida__time_slot__data__month=dia.month,
    )


def indicadores_dashboard(arena: Arena) -> Indicadores:
    """KPIs: vendas do mês, saldo da carteira, horários vagos e mensalistas (7 dias)."""
    hoje = timezone.localdate()
    dias = [hoje + timedelta(days=i) for i in range(DIAS_DA_SEMANA)]
    quadras = list(arena.quadras.all())
    celulas = [c for q in quadras for linha in grade_da_quadra(q, dias) for c in linha.celulas]
    alugueis = {quadra.pk: aluguel_sugerido(quadra) for quadra in quadras}
    vagas = [c for c in celulas if c.tipo == TipoCelula.VAGO]
    mensalistas = [c for c in celulas if c.tipo == TipoCelula.MENSALISTA]
    saldo = razao.saldo_da_arena(arena)
    vendidas = Booking.objects.filter(
        open_match__time_slot__court__arena=arena,
        open_match__time_slot__data__year=hoje.year,
        open_match__time_slot__data__month=hoje.month,
        status=StatusInscricao.CONFIRMADA,
        posicao=Posicao.LINHA,
    )
    return Indicadores(
        vendido_mes=razao.saldo(_vendas_do_mes(arena, hoje)),
        vagas_vendidas_mes=vendidas.count(),
        a_liberar=saldo.a_liberar,
        disponivel=saldo.disponivel,
        horarios_vagos=len(vagas),
        # Aluguel que um horário vago rende para a quadra se virar partida e lotar.
        aluguel_por_horario=max((alugueis[c.quadra.pk] for c in vagas), default=ZERO),
        horarios_mensalistas=len(mensalistas),
        quadras_com_mensalistas=len({c.quadra.pk for c in mensalistas}),
    )


def proximas_partidas(arena: Arena, limite: int = 8) -> list[ResumoPartida]:
    """Próximas partidas abertas com o valor da quadra já pago e em pagamento."""
    agora = timezone.now()
    partidas = (
        OpenMatch.objects.futuras()
        .filter(time_slot__court__arena=arena, status__in=STATUS_PARTIDA_ATIVA)
        .com_relacionados()
        .com_confirmados()
        .annotate(
            pago=Sum("inscricoes__valor_vaga", filter=Q(inscricoes__status=StatusInscricao.CONFIRMADA)),
            em_pagamento=Sum(
                "inscricoes__valor_vaga",
                filter=Q(
                    inscricoes__status=StatusInscricao.AGUARDANDO_PAGAMENTO,
                    inscricoes__reservada_ate__gt=agora,
                ),
            ),
        )
        .order_by("time_slot__data", "time_slot__hora_inicio")[:limite]
    )
    return [
        ResumoPartida(
            partida,
            (partida.pago or ZERO) + partida.ajuste_repasse_fechamento,
            partida.em_pagamento or ZERO,
        )
        for partida in partidas
    ]


def resumo_financeiro(arena: Arena) -> dict[str, Decimal | int]:
    """Saldo da carteira (disponível, a liberar, repassado no mês) e vendas do mês."""
    hoje = timezone.localdate()
    saldo = razao.saldo_da_arena(arena)
    return {
        "disponivel": saldo.disponivel,
        "a_liberar": saldo.a_liberar,
        "repassado_mes": saldo.repassado_no_mes,
        "vendido_mes": razao.saldo(_vendas_do_mes(arena, hoje)),
    }


def extrato_financeiro(arena: Arena, tipo: str | None, periodo: str | None) -> QuerySet[LedgerEntry]:
    """Lançamentos da carteira da arena para o extrato, com filtros opcionais."""
    lancamentos = razao.extrato_da_arena(arena)
    if tipo:
        lancamentos = lancamentos.filter(tipo=tipo)
    hoje = timezone.localdate()
    if periodo == "mes":
        lancamentos = lancamentos.filter(created_at__year=hoje.year, created_at__month=hoje.month)
    elif periodo == "a_liberar":
        lancamentos = lancamentos.filter(disponivel_em__gt=timezone.now())
    return lancamentos


# --- Ações -------------------------------------------------------------------


@transaction.atomic
def abrir_partida(
    quadra: Court,
    dia: date,
    inicio: time,
    fim: time,
    aluguel: Decimal,
    nivel: str,
    vagas: int | None = None,
    vagas_goleiro: int | None = None,
) -> OpenMatch:
    """Publica uma partida aberta num horário vago da quadra.

    O gestor informa o aluguel total e as vagas; goleiros não pagam, e o preço de
    cada vaga de linha é calculado pela partida (parte da quadra + taxa).

    Cria o horário na agenda quando ainda não existe e reabre uma partida
    cancelada no mesmo horário.

    Raises:
        ValidationError: horário reservado, já iniciado, com partida ativa ou em
            conflito com a agenda (regras do modelo).
    """
    if timezone.make_aware(datetime.combine(dia, inicio)) <= timezone.localtime():
        raise ValidationError("Este horário já começou.")
    vagas = vagas or quadra.capacidade_padrao
    vagas_goleiro = vagas_goleiro_sugeridas(vagas) if vagas_goleiro is None else vagas_goleiro
    horario = TimeSlot.objects.filter(court=quadra, data=dia, hora_inicio=inicio).first()
    if horario is None:
        horario = TimeSlot.objects.create(
            court=quadra,
            data=dia,
            hora_inicio=inicio,
            hora_fim=fim,
            tipo_reserva=TipoReserva.AVULSO,
            status=StatusHorario.OCIOSO,
        )
    elif horario.status not in STATUS_HORARIO_LIVRE:
        raise ValidationError("Este horário já está reservado.")

    partida = OpenMatch.objects.filter(time_slot=horario).first()
    if partida is None:
        return OpenMatch.objects.create(
            time_slot=horario,
            vagas_totais=vagas,
            vagas_goleiro=vagas_goleiro,
            valor_total_aluguel=aluguel,
            nivel_competitividade=nivel,
        )
    if partida.status != StatusPartida.CANCELADA:
        raise ValidationError("Este horário já tem uma partida aberta.")
    partida.status = StatusPartida.ABERTA
    partida.motivo_cancelamento, partida.cancelada_em, partida.quorum_conferido_em = "", None, None
    partida.vagas_totais, partida.vagas_goleiro = vagas, vagas_goleiro
    partida.valor_total_aluguel, partida.nivel_competitividade = aluguel, nivel
    partida.save()
    return partida
