"""Cálculos e ações do Portal do Gestor (ArenaManager).

Concentra indicadores, grade semanal da agenda e financeiro para manter as views
enxutas. Tudo o que o gestor vê é o valor líquido da quadra (parte do aluguel em
cada vaga, congelada na inscrição); a taxa da plataforma, paga pelo jogador, não aparece.
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

from .models import (
    MEIA_NOITE,
    STATUS_HORARIO_LIVRE,
    STATUS_PARTIDA_ATIVA,
    Arena,
    Booking,
    Court,
    OpenMatch,
    StatusHorario,
    StatusPagamento,
    StatusPartida,
    TimeSlot,
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
    liquido: Decimal = Decimal("0")

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

    liquido_mes: Decimal
    pagamentos_mes: int
    liquido_pendente: Decimal
    horarios_vagos: int
    aluguel_por_horario: Decimal
    horarios_mensalistas: int
    quadras_com_mensalistas: int


@dataclass(frozen=True)
class ResumoPartida:
    """Partida aberta com o valor líquido da quadra já pago e ainda pendente."""

    partida: OpenMatch
    liquido_pago: Decimal
    liquido_pendente: Decimal

    @property
    def percentual_do_aluguel(self) -> int:
        """Quanto do aluguel já foi pago (0 a 100), para a barra de progresso."""
        aluguel = self.partida.valor_total_aluguel
        return min(100, round(100 * self.liquido_pago / aluguel)) if aluguel else 0


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


def _liquido_por_partida(partidas: list[OpenMatch]) -> dict:
    """Valor líquido da quadra já pago em cada partida."""
    pagas = (
        Booking.objects.filter(open_match__in=partidas, status_pagamento=StatusPagamento.PAGO)
        .values("open_match_id")
        .annotate(total=Sum("valor_vaga"))
    )
    totais = {linha["open_match_id"]: linha["total"] for linha in pagas}
    com_pendencias = set(
        Booking.objects.filter(
            open_match__in=partidas, status_pagamento=StatusPagamento.PENDENTE
        ).values_list("open_match_id", flat=True)
    )
    for partida in partidas:
        if partida.pk not in com_pendencias:
            totais[partida.pk] = (totais.get(partida.pk) or Decimal("0")) + partida.ajuste_repasse_fechamento
    return totais


def _celula(
    quadra: Court,
    dia: date,
    hora: int,
    horario: TimeSlot | None,
    agora: datetime,
    liquido: dict,
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
        return Celula(quadra, dia, inicio, fim, tipo, horario, partida, liquido.get(partida.pk, Decimal("0")))
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
    liquido = _liquido_por_partida(partidas)
    horas = sorted(set(_horas_de_funcionamento(quadra.arena)) | {h.hora_inicio.hour for h in horarios})
    agora = timezone.localtime()
    return [
        LinhaGrade(
            inicio=time(hora),
            celulas=[
                _celula(quadra, dia, hora, por_posicao.get((dia, hora)), agora, liquido) for dia in dias
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


def _liquido(inscricoes: QuerySet[Booking]) -> Decimal:
    """Soma da parte da quadra nas inscrições (sem a taxa da plataforma)."""
    return inscricoes.aggregate(total=Sum("valor_vaga"))["total"] or Decimal("0")


def _inscricoes(arena: Arena) -> QuerySet[Booking]:
    return Booking.objects.filter(open_match__time_slot__court__arena=arena)


def _do_mes(inscricoes: QuerySet[Booking], dia: date) -> QuerySet[Booking]:
    return inscricoes.filter(
        open_match__time_slot__data__year=dia.year, open_match__time_slot__data__month=dia.month
    )


def _ajustes_fechamento(arena: Arena, *, pendente: bool, dia: date | None = None) -> Decimal:
    """Soma os resíduos de rateio no grupo que ainda deve recebê-los.

    Quando há inscrições pendentes, o ajuste fica em ``a receber``. Depois que
    todas são pagas, ele passa para o valor recebido. ``dia`` limita a soma ao
    mês da partida para os indicadores mensais.
    """
    partidas = OpenMatch.objects.filter(
        time_slot__court__arena=arena, vagas_disponiveis=0
    ).exclude(status=StatusPartida.CANCELADA)
    if dia is not None:
        partidas = partidas.filter(
            time_slot__data__year=dia.year, time_slot__data__month=dia.month
        )
    total = Decimal("0.00")
    for partida in partidas.select_related("time_slot"):
        tem_pendente = partida.inscricoes.filter(
            status_pagamento=StatusPagamento.PENDENTE
        ).exists()
        if tem_pendente == pendente:
            total += partida.ajuste_repasse_fechamento
    return total


def indicadores_dashboard(arena: Arena) -> Indicadores:
    """KPIs: líquido do mês, previsto, horários vagos e mensalistas (próximos 7 dias)."""
    hoje = timezone.localdate()
    dias = [hoje + timedelta(days=i) for i in range(DIAS_DA_SEMANA)]
    quadras = list(arena.quadras.all())
    celulas = [c for q in quadras for linha in grade_da_quadra(q, dias) for c in linha.celulas]
    alugueis = {quadra.pk: aluguel_sugerido(quadra) for quadra in quadras}
    vagas = [c for c in celulas if c.tipo == TipoCelula.VAGO]
    mensalistas = [c for c in celulas if c.tipo == TipoCelula.MENSALISTA]
    inscricoes = _inscricoes(arena)
    pagas_mes = _do_mes(inscricoes, hoje).filter(status_pagamento=StatusPagamento.PAGO)
    pendentes = inscricoes.filter(
        status_pagamento=StatusPagamento.PENDENTE, open_match__status__in=STATUS_PARTIDA_ATIVA
    )
    return Indicadores(
        liquido_mes=_liquido(pagas_mes) + _ajustes_fechamento(arena, pendente=False, dia=hoje),
        pagamentos_mes=pagas_mes.count(),
        liquido_pendente=_liquido(pendentes) + _ajustes_fechamento(arena, pendente=True),
        horarios_vagos=len(vagas),
        # Aluguel que um horário vago rende para a quadra se virar partida e lotar.
        aluguel_por_horario=max((alugueis[c.quadra.pk] for c in vagas), default=Decimal("0")),
        horarios_mensalistas=len(mensalistas),
        quadras_com_mensalistas=len({c.quadra.pk for c in mensalistas}),
    )


def proximas_partidas(arena: Arena, limite: int = 8) -> list[ResumoPartida]:
    """Próximas partidas abertas com o líquido da quadra pago e pendente."""
    partidas = (
        OpenMatch.objects.futuras()
        .filter(time_slot__court__arena=arena, status__in=STATUS_PARTIDA_ATIVA)
        .com_relacionados()
        .annotate(
            liquido_pago=Sum(
                "inscricoes__valor_vaga", filter=Q(inscricoes__status_pagamento=StatusPagamento.PAGO)
            ),
            liquido_pendente=Sum(
                "inscricoes__valor_vaga", filter=Q(inscricoes__status_pagamento=StatusPagamento.PENDENTE)
            ),
        )
        .order_by("time_slot__data", "time_slot__hora_inicio")[:limite]
    )
    zero = Decimal("0")
    resumos = []
    for partida in partidas:
        pago = partida.liquido_pago or zero
        pendente = partida.liquido_pendente or zero
        ajuste = partida.ajuste_repasse_fechamento
        if pendente:
            pendente += ajuste
        else:
            pago += ajuste
        resumos.append(ResumoPartida(partida, pago, pendente))
    return resumos


def resumo_financeiro(arena: Arena) -> dict[str, Decimal | int]:
    """Totais do financeiro em valor líquido da quadra: pago e reembolsado no mês e pendente."""
    hoje = timezone.localdate()
    inscricoes = _inscricoes(arena)
    do_mes = _do_mes(inscricoes, hoje)
    pagas_mes = do_mes.filter(status_pagamento=StatusPagamento.PAGO)
    pendentes = inscricoes.filter(
        status_pagamento=StatusPagamento.PENDENTE, open_match__status__in=STATUS_PARTIDA_ATIVA
    )
    return {
        "liquido_mes": _liquido(pagas_mes) + _ajustes_fechamento(arena, pendente=False, dia=hoje),
        "pagamentos_mes": pagas_mes.count(),
        "liquido_pendente": _liquido(pendentes) + _ajustes_fechamento(arena, pendente=True),
        "reembolsado_mes": _liquido(do_mes.filter(status_pagamento=StatusPagamento.REEMBOLSADO)),
    }


def inscricoes_financeiro(arena: Arena, status: str | None, periodo: str | None) -> QuerySet[Booking]:
    """Inscrições da arena para a tabela do financeiro, com filtros opcionais."""
    hoje = timezone.localdate()
    inscricoes = _inscricoes(arena).select_related("player", "open_match__time_slot__court")
    if status:
        inscricoes = inscricoes.filter(status_pagamento=status)
    if periodo == "proximas":
        inscricoes = inscricoes.filter(open_match__time_slot__data__gte=hoje)
    elif periodo == "mes":
        inscricoes = _do_mes(inscricoes, hoje)
    return inscricoes.order_by(
        "open_match__time_slot__data", "open_match__time_slot__hora_inicio", "player__first_name"
    )


# --- Ações -------------------------------------------------------------------

_TRANSICOES_PAGAMENTO = {
    StatusPagamento.PENDENTE: {StatusPagamento.PAGO},
    StatusPagamento.PAGO: {StatusPagamento.REEMBOLSADO},
}


@transaction.atomic
def abrir_partida(
    quadra: Court,
    dia: date,
    inicio: time,
    fim: time,
    aluguel: Decimal,
    nivel: str,
    vagas: int | None = None,
) -> OpenMatch:
    """Publica uma partida aberta num horário vago da quadra.

    O gestor informa só o aluguel total e as vagas; o preço de cada vaga para o
    jogador é calculado pela partida (parte da quadra + taxa da plataforma).

    Cria o horário na agenda quando ainda não existe e reabre uma partida
    cancelada no mesmo horário.

    Raises:
        ValidationError: horário reservado, já iniciado, com partida ativa ou em
            conflito com a agenda (regras do modelo).
    """
    if timezone.make_aware(datetime.combine(dia, inicio)) <= timezone.localtime():
        raise ValidationError("Este horário já começou.")
    vagas = vagas or quadra.capacidade_padrao
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
            time_slot=horario, vagas_totais=vagas, valor_total_aluguel=aluguel, nivel_competitividade=nivel
        )
    if partida.status != StatusPartida.CANCELADA:
        raise ValidationError("Este horário já tem uma partida aberta.")
    partida.status = StatusPartida.ABERTA
    partida.vagas_totais, partida.valor_total_aluguel, partida.nivel_competitividade = vagas, aluguel, nivel
    partida.save()
    return partida


def registrar_pagamento(inscricao: Booking, status: str) -> None:
    """Marca uma inscrição como paga (se pendente) ou reembolsada (se paga).

    Raises:
        ValidationError: transição não permitida ou regra do modelo violada.
    """
    if status not in StatusPagamento.values:
        raise ValidationError("Status de pagamento inválido.")
    if status not in _TRANSICOES_PAGAMENTO.get(inscricao.status_pagamento, set()):
        raise ValidationError(
            f"Não é possível mudar o pagamento de {inscricao.get_status_pagamento_display().lower()} "
            f"para {StatusPagamento(status).label.lower()}."
        )
    inscricao.status_pagamento = status
    inscricao.save()
