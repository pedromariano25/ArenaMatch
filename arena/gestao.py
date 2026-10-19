"""Cálculos e ações do Portal do Gestor (ArenaManager).

Concentra os números do painel, a agenda (semanal e do dia, com publicação em um
toque) e o financeiro para manter as views enxutas. O gestor vê o valor líquido da quadra (parte do aluguel em cada vaga,
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
from django.db.models import QuerySet, Sum
from django.utils import timezone

from . import razao
from .models import (
    MEIA_NOITE,
    STATUS_HORARIO_LIVRE,
    ZERO,
    Arena,
    Booking,
    Court,
    LedgerEntry,
    NivelCompetitividade,
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
    PELADA = "pelada"
    VAGO = "vago"
    ENCERRADO = "encerrado"


ROTULOS_CELULA = {
    TipoCelula.MENSALISTA: "Mensalista",
    TipoCelula.AVULSO: "Avulso",
    TipoCelula.BLOQUEADO: "Bloqueado",
    TipoCelula.PARTIDA: "Partida aberta",
    TipoCelula.LOTADA: "Partida lotada",
    TipoCelula.PELADA: "Pelada de grupo",
    TipoCelula.VAGO: "Livre",
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
    """Os três números do painel: saldo a receber, vagas vendidas e horários ociosos.

    O saldo liberado é transferido à arena a cada hora (rotina ``gerar_repasses``),
    então o painel mostra o total a receber (liberado + a liberar) e o que já foi
    transferido no mês.
    """

    disponivel: Decimal
    a_liberar: Decimal
    repassado_mes: Decimal
    vagas_vendidas_mes: int
    vendido_mes: Decimal
    horarios_ociosos: int
    # Aluguel somado dos horários ociosos, se todos virassem partidas e lotassem.
    potencial_ocioso: Decimal

    @property
    def a_receber(self) -> Decimal:
        return self.disponivel + self.a_liberar


@dataclass(frozen=True)
class DiaDoPainel:
    """Aba de um dia na agenda do painel, com quantos horários ainda estão ociosos."""

    dia: date
    ociosos: int


@dataclass(frozen=True)
class QuadraDoDia:
    """Faixas de uma quadra num dia e a partida que um toque num horário ocioso publica."""

    quadra: Court
    celulas: list[Celula]
    padrao: OpenMatch


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


def partida_padrao(quadra: Court) -> OpenMatch:
    """Partida (não salva) que a publicação em um toque cria nesta quadra.

    Aluguel sugerido, capacidade da quadra, goleiros sugeridos, nível aberto a
    todos e o contrato da arena: serve para mostrar o preço antes de publicar.
    """
    vagas = quadra.capacidade_padrao
    return OpenMatch(
        valor_total_aluguel=aluguel_sugerido(quadra),
        vagas_totais=vagas,
        vagas_goleiro=vagas_goleiro_sugeridas(vagas),
        nivel_competitividade=NivelCompetitividade.ABERTA,
        taxa_plataforma_percentual=quadra.arena.taxa_plataforma_percentual,
        taxa_minima=quadra.arena.taxa_minima,
    )


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
    if partida is not None and partida.status != StatusPartida.CANCELADA and partida.organizador_id:
        # Mensalista que vende as vagas que faltam no próprio grupo (o dinheiro é do grupo).
        return Celula(quadra, dia, inicio, fim, TipoCelula.PELADA, horario, partida)
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
            "partida_aberta__organizador"
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


def semana_da_arena(arena: Arena) -> tuple[list[date], dict[Court, list[LinhaGrade]]]:
    """Os próximos 7 dias (a partir de hoje) e a grade de cada quadra nesses dias."""
    hoje = timezone.localdate()
    dias = [hoje + timedelta(days=i) for i in range(DIAS_DA_SEMANA)]
    quadras = arena.quadras.select_related("arena").order_by("nome_ou_numero")
    return dias, {quadra: grade_da_quadra(quadra, dias) for quadra in quadras}


def dias_do_painel(dias: list[date], grades: dict[Court, list[LinhaGrade]]) -> list[DiaDoPainel]:
    """Abas da agenda do painel, com os horários ociosos de cada dia."""
    return [
        DiaDoPainel(
            dia,
            sum(linha.celulas[indice].tipo == TipoCelula.VAGO for linhas in grades.values() for linha in linhas),
        )
        for indice, dia in enumerate(dias)
    ]


def agenda_do_dia(grades: dict[Court, list[LinhaGrade]], indice: int) -> list[QuadraDoDia]:
    """Faixas de cada quadra no dia ``indice`` da semana, sem os horários que já passaram."""
    return [
        QuadraDoDia(
            quadra,
            [c for linha in linhas if (c := linha.celulas[indice]).tipo != TipoCelula.ENCERRADO],
            partida_padrao(quadra),
        )
        for quadra, linhas in grades.items()
    ]


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


def indicadores_dashboard(arena: Arena, grades: dict[Court, list[LinhaGrade]]) -> Indicadores:
    """Saldo da carteira, vagas vendidas no mês e horários ociosos nas grades informadas."""
    hoje = timezone.localdate()
    ociosas = [c for linhas in grades.values() for linha in linhas for c in linha.celulas if c.tipo == TipoCelula.VAGO]
    alugueis = {quadra.pk: aluguel_sugerido(quadra) for quadra in grades}
    saldo = razao.saldo_da_arena(arena)
    vendidas = Booking.objects.filter(
        open_match__time_slot__court__arena=arena,
        open_match__time_slot__data__year=hoje.year,
        open_match__time_slot__data__month=hoje.month,
        open_match__organizador__isnull=True,
        status=StatusInscricao.CONFIRMADA,
        posicao=Posicao.LINHA,
    )
    return Indicadores(
        disponivel=saldo.disponivel,
        a_liberar=saldo.a_liberar,
        repassado_mes=saldo.repassado_no_mes,
        vagas_vendidas_mes=vendidas.count(),
        vendido_mes=razao.saldo(_vendas_do_mes(arena, hoje)),
        horarios_ociosos=len(ociosas),
        potencial_ocioso=sum((alugueis[c.quadra.pk] for c in ociosas), ZERO),
    )


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
