"""Jogadores: perfil e nível, elegibilidade, check-in, confiabilidade, avaliações e times.

O nível (1 a 5) nasce de um questionário curto e é corrigido pela comunidade:
quando colegas diferentes sinalizam, em partidas com faixa de nível, que o
jogador joga acima (ou abaixo) do nível da partida, o nível sobe (ou desce) um ponto.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.formats import date_format

from .models import (
    DIAS_PARA_AVALIAR,
    DIAS_SUSPENSAO_GOLEIRO,
    FAIXAS_DE_NIVEL,
    SINAIS_PARA_AJUSTAR_NIVEL,
    AvaliacaoPartida,
    Booking,
    DirecaoNivel,
    Elogio,
    NivelCompetitividade,
    OpenMatch,
    OrigemNivel,
    PlayerProfile,
    Posicao,
    SinalNivel,
    StatusInscricao,
    StatusPartida,
    TipoElogio,
)

# --- Questionário de nível -----------------------------------------------------

FREQUENCIAS = (
    ("raro", "Raramente", 1),
    ("mensal", "Uma vez por mês", 2),
    ("semanal", "Toda semana", 3),
    ("varias", "Várias vezes por semana", 4),
)
EXPERIENCIAS = (
    ("nunca", "Nunca joguei em time", 1),
    ("amigos", "Escolinha ou time de amigos", 2),
    ("amador", "Campeonato amador", 4),
    ("federado", "Federado ou semiprofissional", 5),
)
NIVEL_PADRAO = 3


def calcular_nivel(autoavaliacao: int, frequencia: str, experiencia: str) -> int:
    """Nível inicial de 1 a 5: a autoavaliação pesa o dobro; frequência e experiência a ancoram.

    As respostas concretas evitam que todo mundo se declare avançado (ou que um
    jogador forte se declare iniciante para sobrar no jogo).
    """
    pontos_frequencia = {codigo: pontos for codigo, _, pontos in FREQUENCIAS}[frequencia]
    pontos_experiencia = {codigo: pontos for codigo, _, pontos in EXPERIENCIAS}[experiencia]
    media = (2 * autoavaliacao + pontos_frequencia + pontos_experiencia) / 4
    return max(1, min(5, int(media + 0.5)))


def perfil_do(jogador: AbstractBaseUser) -> PlayerProfile | None:
    if not getattr(jogador, "is_authenticated", False):
        return None
    return PlayerProfile.objects.filter(jogador=jogador).first()


def nivel_do(jogador: AbstractBaseUser) -> int:
    perfil = perfil_do(jogador)
    return perfil.nivel if perfil else NIVEL_PADRAO


def salvar_perfil(
    jogador: AbstractBaseUser,
    *,
    posicao: str,
    joga_no_gol: bool = False,
    apelido: str = "",
    regiao: str = "",
    nivel_declarado: int | None = None,
) -> PlayerProfile:
    """Cria ou atualiza o perfil. O nível declarado não sobrepõe um ajuste da comunidade."""
    perfil = perfil_do(jogador) or PlayerProfile(jogador=jogador)
    perfil.posicao, perfil.joga_no_gol = posicao, joga_no_gol
    perfil.apelido, perfil.regiao = apelido, regiao
    if nivel_declarado is not None and perfil.nivel_origem == OrigemNivel.DECLARADO:
        perfil.nivel = nivel_declarado
    perfil.save()
    return perfil


# --- Elegibilidade ---------------------------------------------------------------


_PERFIL_NAO_INFORMADO = object()


def motivo_inelegivel(
    partida: OpenMatch,
    jogador: AbstractBaseUser,
    posicao: str = Posicao.LINHA,
    perfil: PlayerProfile | None | object = _PERFIL_NAO_INFORMADO,
) -> str | None:
    """Explica por que o jogador não pode entrar na vaga (``None`` se pode).

    ``perfil`` evita reconsultar o banco quando a mesma checagem roda em várias partidas.
    """
    if partida.organizador_id is not None and partida.organizador_id == jogador.pk:
        return "Você organiza esta pelada: as vagas são para quem vai completar o seu grupo."
    if perfil is _PERFIL_NAO_INFORMADO:
        perfil = perfil_do(jogador)
    if perfil is None:
        return "Complete seu perfil de jogador (nível e posição) para entrar em partidas."
    if posicao == Posicao.GOLEIRO:
        if perfil.goleiro_suspenso:
            return (
                "Você faltou como goleiro sem avisar: a vaga grátis de goleiro está suspensa até "
                f"{date_format(perfil.goleiro_suspenso_ate, 'd/m')}."
            )
        if not perfil.pode_ser_goleiro:
            return "A vaga de goleiro é para quem joga no gol. Marque essa opção no seu perfil."
    if not partida.aceita_nivel(perfil.nivel):
        liberacao = timezone.localtime(partida.liberacao_de_nivel)
        return (
            f"Esta partida é para {partida.rotulo_faixa} e o seu nível é {perfil.nivel}. "
            f"Se ainda tiver vaga, ela abre para todos os níveis em {liberacao:%d/%m às %H:%M}."
        )
    return None


def validar_elegibilidade(partida: OpenMatch, jogador: AbstractBaseUser, posicao: str = Posicao.LINHA) -> None:
    """Raises: ValidationError (``perfil_incompleto`` ou ``inelegivel``)."""
    motivo = motivo_inelegivel(partida, jogador, posicao)
    if motivo:
        codigo = "perfil_incompleto" if perfil_do(jogador) is None else "inelegivel"
        raise ValidationError(motivo, code=codigo)


# --- Check-in e faltas -------------------------------------------------------------


def pode_fazer_check_in(inscricao: Booking, agora: datetime | None = None) -> bool:
    """Vaga paga, de uma hora antes do jogo até o fim dele."""
    agora = agora or timezone.now()
    horario = inscricao.open_match.time_slot
    return (
        inscricao.status == StatusInscricao.CONFIRMADA
        and horario.inicio - timedelta(hours=1) <= agora <= horario.fim
    )


def registrar_check_in(inscricao: Booking) -> None:
    """Marca a presença do jogador na recepção (pelo QR do comprovante).

    Raises:
        ValidationError: fora da janela do jogo ou inscrição sem vaga paga.
    """
    if inscricao.check_in_em is not None:
        return
    if not pode_fazer_check_in(inscricao):
        raise ValidationError("O check-in vale de 1h antes do jogo até o fim dele, para vagas confirmadas.")
    inscricao.check_in_em = timezone.now()
    inscricao.save()


def registrar_faltas(partida: OpenMatch) -> int:
    """No encerramento, quem não fez check-in falta (se a arena usou o check-in no jogo).

    Goleiro que falta perde a vaga grátis por ``DIAS_SUSPENSAO_GOLEIRO`` dias.
    """
    confirmadas = partida.inscricoes.filter(status=StatusInscricao.CONFIRMADA)
    if not confirmadas.filter(check_in_em__isnull=False).exists():
        return 0  # A arena não fez check-in neste jogo: ninguém é marcado.
    ausentes = list(confirmadas.filter(check_in_em__isnull=True, faltou=False).select_related("player"))
    for inscricao in ausentes:
        inscricao.faltou = True
        inscricao.save()
        if inscricao.posicao == Posicao.GOLEIRO:
            PlayerProfile.objects.filter(jogador=inscricao.player).update(
                goleiro_suspenso_ate=timezone.localdate() + timedelta(days=DIAS_SUSPENSAO_GOLEIRO)
            )
    return len(ausentes)


# --- Estatísticas -------------------------------------------------------------------


@dataclass(frozen=True)
class Estatisticas:
    """Números do perfil do jogador."""

    partidas_jogadas: int
    faltas: int
    confiabilidade: int | None
    elogios: list[tuple[str, int]] = field(default_factory=list)


def estatisticas(jogador: AbstractBaseUser) -> Estatisticas:
    """Partidas jogadas, faltas, confiabilidade (% de presença com check-in) e elogios."""
    jogadas = Booking.objects.filter(
        player=jogador, status=StatusInscricao.CONFIRMADA, open_match__status=StatusPartida.FINALIZADA
    )
    faltas = jogadas.filter(faltou=True).count()
    com_check_in = (
        jogadas.filter(open_match__inscricoes__check_in_em__isnull=False).values("pk").distinct().count()
    )
    confiabilidade = round(100 * (com_check_in - faltas) / com_check_in) if com_check_in else None
    rotulos = dict(TipoElogio.choices)
    elogios = [
        (rotulos[linha["tipo"]], linha["total"])
        for linha in Elogio.objects.filter(alvo=jogador).values("tipo").annotate(total=Count("pk")).order_by("-total")
    ]
    return Estatisticas(jogadas.count() - faltas, faltas, confiabilidade, elogios)


# --- Avaliação pós-jogo ----------------------------------------------------------------


def _inscricao_de_quem_jogou(partida: OpenMatch, jogador: AbstractBaseUser) -> Booking | None:
    return partida.inscricoes.filter(player=jogador, status=StatusInscricao.CONFIRMADA, faltou=False).first()


def pode_avaliar(partida: OpenMatch, jogador: AbstractBaseUser) -> bool:
    """Quem jogou avalia uma vez, até ``DIAS_PARA_AVALIAR`` dias depois do jogo."""
    return (
        partida.status == StatusPartida.FINALIZADA
        and timezone.now() <= partida.time_slot.fim + timedelta(days=DIAS_PARA_AVALIAR)
        and _inscricao_de_quem_jogou(partida, jogador) is not None
        and not AvaliacaoPartida.objects.filter(partida=partida, autor=jogador).exists()
    )


def colegas_de_partida(partida: OpenMatch, jogador: AbstractBaseUser) -> list[Booking]:
    """Inscrições de quem jogou junto (para elogios e sinais de nível)."""
    return list(
        partida.inscricoes.filter(status=StatusInscricao.CONFIRMADA, faltou=False)
        .exclude(player=jogador)
        .select_related("player__perfil")
        .order_by("posicao", "player__first_name")
    )


@transaction.atomic
def registrar_avaliacao(
    partida: OpenMatch,
    autor: AbstractBaseUser,
    percepcao: str,
    elogios: dict[str, str] | None = None,
    sinais: dict[str, str] | None = None,
) -> list[AbstractBaseUser]:
    """Registra a avaliação, os elogios e os sinais de nível; devolve quem teve o nível ajustado.

    ``elogios`` e ``sinais`` mapeiam o id do colega para o tipo de elogio ou a direção.

    Raises:
        ValidationError: o autor não jogou a partida, já avaliou ou o prazo acabou.
    """
    if not pode_avaliar(partida, autor):
        raise ValidationError("Esta partida não pode mais ser avaliada por você.")
    AvaliacaoPartida.objects.create(autor=autor, partida=partida, percepcao=percepcao)
    colegas = {str(inscricao.player_id): inscricao.player for inscricao in colegas_de_partida(partida, autor)}
    for alvo_id, tipo in (elogios or {}).items():
        if alvo_id in colegas and tipo in TipoElogio.values:
            Elogio.objects.get_or_create(autor=autor, alvo=colegas[alvo_id], partida=partida, tipo=tipo)
    # Sinais só fazem sentido em partidas com faixa de nível (não nas abertas a todos).
    if partida.nivel_competitividade == NivelCompetitividade.ABERTA:
        sinais = {}
    ajustados = []
    for alvo_id, direcao in (sinais or {}).items():
        if alvo_id in colegas and direcao in DirecaoNivel.values:
            SinalNivel.objects.get_or_create(
                autor=autor, alvo=colegas[alvo_id], partida=partida, defaults={"direcao": direcao}
            )
            if ajustar_nivel_se_preciso(colegas[alvo_id]) is not None:
                ajustados.append(colegas[alvo_id])
    return ajustados


def ajustar_nivel_se_preciso(jogador: AbstractBaseUser) -> int | None:
    """Sobe ou desce um nível quando colegas diferentes sinalizam a mesma coisa.

    Contam só os sinais depois do último ajuste e coerentes com a faixa da partida
    (ex.: "acima" quando o jogador estava dentro da faixa). Devolve o novo nível.
    """
    perfil = perfil_do(jogador)
    if perfil is None:
        return None
    sinais = SinalNivel.objects.filter(alvo=jogador).select_related("partida")
    if perfil.nivel_ajustado_em is not None:
        sinais = sinais.filter(created_at__gt=perfil.nivel_ajustado_em)
    autores = {DirecaoNivel.ACIMA: set(), DirecaoNivel.ABAIXO: set()}
    for sinal in sinais:
        minimo, maximo = FAIXAS_DE_NIVEL.get(sinal.partida.nivel_competitividade, (1, 5))
        coerente = perfil.nivel <= maximo if sinal.direcao == DirecaoNivel.ACIMA else perfil.nivel >= minimo
        if coerente:
            autores[sinal.direcao].add(sinal.autor_id)
    for direcao, passo in ((DirecaoNivel.ACIMA, 1), (DirecaoNivel.ABAIXO, -1)):
        novo = max(1, min(5, perfil.nivel + passo))
        if len(autores[direcao]) >= SINAIS_PARA_AJUSTAR_NIVEL and novo != perfil.nivel:
            perfil.nivel = novo
            perfil.nivel_origem = OrigemNivel.AJUSTADO
            perfil.nivel_ajustado_em = timezone.now()
            perfil.save()
            return novo
    return None


# --- Times equilibrados ----------------------------------------------------------------


@dataclass
class Time:
    """Um dos dois times sugeridos para a partida."""

    nome: str
    goleiro: Booking | None = None
    jogadores: list[Booking] = field(default_factory=list)

    @property
    def forca(self) -> int:
        inscricoes = self.jogadores + ([self.goleiro] if self.goleiro else [])
        return sum(_nivel_da_inscricao(inscricao) for inscricao in inscricoes)


def _nivel_da_inscricao(inscricao: Booking) -> int:
    perfil = getattr(inscricao.player, "perfil", None)
    return perfil.nivel if perfil else NIVEL_PADRAO


def montar_times(partida: OpenMatch) -> tuple[Time, Time]:
    """Divide os confirmados em dois times de força parecida (um goleiro em cada).

    Os mais fortes escolhem primeiro: cada jogador vai para o time com menos
    jogadores ou, empatados, com menos força somada.
    """
    confirmadas = list(partida.inscricoes.confirmadas().select_related("player__perfil"))
    times = (Time("Colete laranja"), Time("Colete azul"))
    goleiros = [i for i in confirmadas if i.posicao == Posicao.GOLEIRO]
    linha = sorted(
        (i for i in confirmadas if i.posicao == Posicao.LINHA), key=_nivel_da_inscricao, reverse=True
    )
    for jogador in linha:
        destino = min(times, key=lambda time: (len(time.jogadores), time.forca))
        destino.jogadores.append(jogador)
    for goleiro in sorted(goleiros, key=_nivel_da_inscricao, reverse=True):
        livres = [time for time in times if time.goleiro is None]
        if livres:
            min(livres, key=lambda time: time.forca).goleiro = goleiro
    return times
