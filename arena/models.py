"""Modelos de domínio do ArenaMatch.

As regras de negócio ficam em ``clean()``. ``ValidatedModel.save()`` executa
``full_clean()`` dentro de uma transação, então as regras valem para qualquer
caminho de escrita (Django Admin, actions, API REST, shell), e não apenas para
formulários. Os fluxos que movimentam dinheiro (checkout, estornos, repasses)
ficam nos módulos de serviço: ``checkout``, ``partidas`` e ``razao``.
"""

import math
import uuid
from datetime import date, datetime, time, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any, Self

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Count, F, Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from .validators import normalizar_documento, validar_cnpj, validar_cpf, validar_telefone

# Usado como ``hora_fim``, 00:00 representa o fim do dia (24:00).
MEIA_NOITE = time(0, 0)

CENTAVO = Decimal("0.01")
ZERO = Decimal("0.00")
# Taxa de serviço da plataforma, cobrada do jogador de linha sobre a parte da quadra,
# com um valor mínimo por vaga. São os padrões do contrato de cada arena.
TAXA_PLATAFORMA_PADRAO = Decimal("15.00")
TAXA_MINIMA_PADRAO = Decimal("2.00")
# Acréscimo de quem paga com cartão, para cobrir a tarifa maior do cartão.
ACRESCIMO_CARTAO_PERCENTUAL = Decimal("5.00")
# Por quanto tempo a vaga fica reservada enquanto o jogador conclui o pagamento.
MINUTOS_RESERVA = 10
# Até quantas horas antes do jogo o jogador cancela e recebe crédito integral.
HORAS_CANCELAMENTO_COM_CREDITO = 24
# Mínimo de jogadores pagos (% das vagas) e prazo para atingi-lo: padrões da arena.
QUORUM_PERCENTUAL_PADRAO = 70
HORAS_PRAZO_QUORUM_PADRAO = 3
# A parte da arena fica retida até o dia seguinte à partida, para cobrir cancelamentos.
DIAS_RETENCAO_SALDO = 1
# A trava de nível cai esta quantidade de horas antes do prazo do mínimo de jogadores.
HORAS_LIBERACAO_NIVEL_ANTES_DO_QUORUM = 1
# Goleiro que falta sem avisar perde a vaga grátis por este período.
DIAS_SUSPENSAO_GOLEIRO = 14
# Por quantos dias depois do jogo os jogadores podem avaliá-lo.
DIAS_PARA_AVALIAR = 7
# Sinais de colegas diferentes (na mesma direção) que ajustam o nível de um jogador.
SINAIS_PARA_AJUSTAR_NIVEL = 3


def arredondar(valor: Decimal) -> Decimal:
    """Arredonda para o centavo (meio para cima)."""
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def calcular_acrescimo_cartao(valor: Decimal) -> Decimal:
    """Acréscimo cobrado de quem paga ``valor`` com cartão."""
    return arredondar(valor * ACRESCIMO_CARTAO_PERCENTUAL / 100)


# --- Choices -----------------------------------------------------------------


class TipoPiso(models.TextChoices):
    """Superfície de jogo da quadra."""

    SINTETICO = "sintetico", "Sintético"
    SALAO = "salao", "Salão"
    AREIA = "areia", "Areia"
    CAMPO = "campo", "Campo"


class TipoReserva(models.TextChoices):
    """Natureza da ocupação de um horário."""

    MENSALISTA = "mensalista", "Mensalista"
    AVULSO = "avulso", "Avulso"
    BLOQUEADO = "bloqueado", "Bloqueado"


class StatusHorario(models.TextChoices):
    """Situação de um horário na agenda da quadra."""

    CONFIRMADO = "confirmado", "Confirmado"
    CANCELADO = "cancelado", "Cancelado"
    OCIOSO = "ocioso", "Ocioso"


class NivelJogador(models.IntegerChoices):
    """Nível técnico do jogador, de 1 a 5."""

    INICIANTE = 1, "Iniciante"
    RECREATIVO = 2, "Recreativo"
    INTERMEDIARIO = 3, "Intermediário"
    AVANCADO = 4, "Avançado"
    ELITE = 5, "Elite"


class NivelCompetitividade(models.TextChoices):
    """Nível da partida: define a faixa de níveis de jogador aceita."""

    ABERTA = "aberta", "Aberta a todos"
    INICIANTE = "iniciante", "Iniciante"
    INTERMEDIARIO = "intermediario", "Intermediário"
    AVANCADO = "avancado", "Avançado"


# Faixa de níveis de jogador aceita em cada nível de partida. As faixas se sobrepõem
# de propósito: é a tolerância entre níveis vizinhos.
FAIXAS_DE_NIVEL = {
    NivelCompetitividade.ABERTA: (1, 5),
    NivelCompetitividade.INICIANTE: (1, 2),
    NivelCompetitividade.INTERMEDIARIO: (2, 4),
    NivelCompetitividade.AVANCADO: (4, 5),
}


class PosicaoJogador(models.TextChoices):
    """Posição em que o jogador costuma jogar."""

    GOLEIRO = "goleiro", "Goleiro"
    DEFESA = "defesa", "Defesa"
    MEIO = "meio", "Meio-campo"
    ATAQUE = "ataque", "Ataque"


class OrigemNivel(models.TextChoices):
    """De onde vem o nível atual do jogador."""

    DECLARADO = "declarado", "Declarado pelo jogador"
    AJUSTADO = "ajustado", "Ajustado pela comunidade"


class PercepcaoNivel(models.TextChoices):
    """Como o jogador sentiu o nível da partida em relação ao anunciado."""

    ABAIXO = "abaixo", "Abaixo do anunciado"
    NA_MEDIDA = "na_medida", "Na medida"
    ACIMA = "acima", "Acima do anunciado"


class DirecaoNivel(models.TextChoices):
    """Sinal de que um colega joga fora do nível da partida."""

    ACIMA = "acima", "Joga acima do nível da partida"
    ABAIXO = "abaixo", "Joga abaixo do nível da partida"


class TipoElogio(models.TextChoices):
    """Elogios (sempre positivos) que um jogador dá a um colega depois do jogo."""

    FAIR_PLAY = "fair_play", "Fair play"
    PONTUAL = "pontual", "Pontual"
    BOM_DE_PASSE = "bom_de_passe", "Bom de passe"
    ARTILHEIRO = "artilheiro", "Artilheiro"
    PAREDAO = "paredao", "Paredão"
    RACA = "raca", "Raça"


class StatusPartida(models.TextChoices):
    """Ciclo de vida de uma partida aberta."""

    ABERTA = "aberta", "Aberta"
    LOTADA = "lotada", "Lotada"
    FINALIZADA = "finalizada", "Finalizada"
    CANCELADA = "cancelada", "Cancelada"


class MotivoCancelamento(models.TextChoices):
    """Por que uma partida foi cancelada."""

    ARENA = "arena", "Cancelada pela arena"
    QUORUM = "quorum", "Mínimo de jogadores não atingido"


class Posicao(models.TextChoices):
    """Tipo de vaga na partida."""

    LINHA = "linha", "Linha"
    GOLEIRO = "goleiro", "Goleiro"


class StatusInscricao(models.TextChoices):
    """Ciclo de vida da inscrição: reserva, pagamento e confirmação (ou não)."""

    AGUARDANDO_PAGAMENTO = "aguardando_pagamento", "Aguardando pagamento"
    CONFIRMADA = "confirmada", "Confirmada"
    EXPIRADA = "expirada", "Expirada"
    CANCELADA = "cancelada", "Cancelada"
    REEMBOLSADA = "reembolsada", "Reembolsada"


class MetodoPagamento(models.TextChoices):
    """Forma de pagamento da vaga."""

    PIX = "pix", "Pix"
    CARTAO = "cartao", "Cartão de crédito"
    CREDITO = "credito", "Crédito ArenaMatch"
    GRATUITO = "gratuito", "Gratuito"


class StatusPagamento(models.TextChoices):
    """Situação de uma cobrança no gateway."""

    PENDENTE = "pendente", "Pendente"
    APROVADO = "aprovado", "Aprovado"
    RECUSADO = "recusado", "Recusado"
    EXPIRADO = "expirado", "Expirado"
    CANCELADO = "cancelado", "Cancelado"
    ESTORNADO = "estornado", "Estornado"


class TipoConta(models.TextChoices):
    """Dono de uma carteira do razão."""

    ARENA = "arena", "Arena"
    PLATAFORMA = "plataforma", "Plataforma"
    JOGADOR = "jogador", "Crédito do jogador"


class TipoLancamento(models.TextChoices):
    """Natureza de um lançamento do razão."""

    VENDA_VAGA = "venda_vaga", "Venda de vaga"
    TAXA_SERVICO = "taxa_servico", "Taxa de serviço"
    ACRESCIMO_CARTAO = "acrescimo_cartao", "Acréscimo do cartão"
    TARIFA_GATEWAY = "tarifa_gateway", "Tarifa do gateway"
    ESTORNO = "estorno", "Estorno"
    CREDITO = "credito", "Crédito ao jogador"
    USO_CREDITO = "uso_credito", "Uso de crédito"
    AJUSTE_FECHAMENTO = "ajuste_fechamento", "Ajuste de fechamento"
    REPASSE = "repasse", "Repasse à arena"


class StatusRepasse(models.TextChoices):
    """Situação de uma transferência para a arena."""

    PAGO = "pago", "Pago"
    FALHOU = "falhou", "Falhou"


# Horários que podem receber uma partida aberta.
STATUS_HORARIO_LIVRE = (StatusHorario.OCIOSO, StatusHorario.CANCELADO)
# Partidas em andamento. Aberta/Lotada são derivados das vagas disponíveis.
STATUS_PARTIDA_ATIVA = (StatusPartida.ABERTA, StatusPartida.LOTADA)
# Inscrições ativas. A reserva (aguardando pagamento) só ocupa vaga dentro do prazo.
STATUS_INSCRICAO_ATIVA = (StatusInscricao.AGUARDANDO_PAGAMENTO, StatusInscricao.CONFIRMADA)


# --- Bases abstratas ---------------------------------------------------------


class BaseModel(models.Model):
    """Base de todos os modelos: chave primária UUID4 e carimbos de data/hora."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        abstract = True


class ValidatedModel(BaseModel):
    """Base das entidades de negócio, que se validam por completo antes de salvar.

    O Django não chama ``clean()`` em ``save()``. Aqui, ``save()`` executa
    ``full_clean()`` (campos, ``clean()``, unicidade e constraints) na mesma
    transação da escrita, para que as validações e a gravação sejam atômicas.
    """

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Valida a instância e a persiste atomicamente.

        Raises:
            ValidationError: se alguma regra de validação for violada.
        """
        with transaction.atomic():
            self.full_clean()
            super().save(*args, **kwargs)


# --- Usuários ----------------------------------------------------------------


class CustomUser(BaseModel, AbstractUser):
    """Usuário da plataforma: gestor de arena (B2B), jogador (B2C) ou ambos.

    Não herda ``ValidatedModel``, porque o fluxo de autenticação salva o usuário
    com frequência (ex.: ``last_login``). A validação completa fica com os
    formulários e serializers, e o CPF é sempre normalizado.
    """

    is_manager = models.BooleanField(
        "gestor de arena",
        default=False,
        help_text="Administra arenas pelo painel de gestão (B2B).",
    )
    is_player = models.BooleanField(
        "jogador",
        default=False,
        help_text="Pode se inscrever em partidas abertas (B2C).",
    )
    telefone = models.CharField(
        "telefone", max_length=20, blank=True, validators=[validar_telefone]
    )
    cpf = models.CharField(
        "CPF",
        max_length=14,
        unique=True,
        null=True,
        blank=True,
        validators=[validar_cpf],
        help_text="Com ou sem máscara. É armazenado só com os dígitos.",
    )

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    @property
    def nome_publico(self) -> str:
        """Nome exibido a outros jogadores: primeiro nome e inicial do sobrenome."""
        if not self.first_name:
            return self.username
        inicial = f" {self.last_name.strip()[0]}." if self.last_name.strip() else ""
        return f"{self.first_name.split()[0]}{inicial}"

    @property
    def iniciais(self) -> str:
        """Até duas iniciais, usadas nos avatares."""
        partes = [*self.first_name.split()[:1], *self.last_name.split()[-1:]]
        return "".join(parte[0] for parte in partes).upper() or self.username[:2].upper()

    def clean(self) -> None:
        """Normaliza o e-mail (via ``AbstractUser``) e o CPF."""
        super().clean()
        self._normalizar_cpf()

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Normaliza o CPF também nas escritas feitas fora de formulários."""
        self._normalizar_cpf()
        super().save(*args, **kwargs)

    def _normalizar_cpf(self) -> None:
        """Remove a máscara. Vazio vira ``None`` para que vários usuários possam ficar sem CPF."""
        self.cpf = normalizar_documento(self.cpf) or None


# --- Arenas e quadras --------------------------------------------------------


class Arena(ValidatedModel):
    """Complexo esportivo (cliente B2B) administrado por um gestor."""

    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="arenas_gerenciadas",
        limit_choices_to={"is_manager": True},
        verbose_name="gestor",
    )
    nome = models.CharField("nome", max_length=120)
    slug = models.SlugField(
        "slug",
        max_length=140,
        unique=True,
        blank=True,
        help_text="Identificador usado em URLs. Se ficar em branco, é gerado a partir do nome.",
    )
    cnpj = models.CharField(
        "CNPJ",
        max_length=18,
        unique=True,
        validators=[validar_cnpj],
        help_text="Com ou sem máscara (aceita o CNPJ alfanumérico). É armazenado sem pontuação.",
    )
    endereco_completo = models.CharField("endereço completo", max_length=255)
    telefone_contato = models.CharField(
        "telefone de contato", max_length=20, validators=[validar_telefone]
    )
    hora_abertura = models.TimeField("hora de abertura")
    hora_fechamento = models.TimeField(
        "hora de fechamento",
        help_text="Se for menor que a hora de abertura, a arena fecha depois da meia-noite.",
    )
    taxa_plataforma_percentual = models.DecimalField(
        "taxa da plataforma (%)",
        max_digits=5,
        decimal_places=2,
        default=TAXA_PLATAFORMA_PADRAO,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Contrato: cobrada do jogador de linha sobre a parte da quadra em cada vaga.",
    )
    taxa_minima = models.DecimalField(
        "taxa mínima por vaga (R$)",
        max_digits=6,
        decimal_places=2,
        default=TAXA_MINIMA_PADRAO,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Contrato: a taxa de serviço nunca fica abaixo deste valor.",
    )
    quorum_percentual = models.PositiveSmallIntegerField(
        "mínimo para confirmar (%)",
        default=QUORUM_PERCENTUAL_PADRAO,
        validators=[MaxValueValidator(100)],
        help_text="Percentual das vagas que precisa estar pago até o prazo. Abaixo disso, a "
        "partida é cancelada e todos são reembolsados. Use 0 para não exigir mínimo.",
    )
    horas_prazo_quorum = models.PositiveSmallIntegerField(
        "prazo do mínimo (horas antes do jogo)",
        default=HORAS_PRAZO_QUORUM_PADRAO,
        validators=[MinValueValidator(1), MaxValueValidator(48)],
    )

    class Meta:
        verbose_name = "arena"
        verbose_name_plural = "arenas"
        ordering = ["nome"]

    def __str__(self) -> str:
        return self.nome

    def clean(self) -> None:
        """Normaliza o CNPJ e gera um slug único quando ele não é informado."""
        super().clean()
        self.cnpj = normalizar_documento(self.cnpj)
        if not self.slug and self.nome:
            self.slug = self._gerar_slug_unico()

    def _gerar_slug_unico(self) -> str:
        """Retorna ``slugify(nome)``, com sufixo numérico em caso de colisão."""
        base = slugify(self.nome)[:120] or "arena"
        slug, sufixo = base, 2
        while Arena.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{sufixo}"
            sufixo += 1
        return slug


class Court(ValidatedModel):
    """Quadra de uma arena."""

    arena = models.ForeignKey(
        Arena, on_delete=models.CASCADE, related_name="quadras", verbose_name="arena"
    )
    nome_ou_numero = models.CharField(
        "nome ou número", max_length=60, help_text="Ex.: Quadra 1."
    )
    tipo_piso = models.CharField(
        "tipo de piso",
        max_length=20,
        choices=TipoPiso.choices,
        default=TipoPiso.SINTETICO,
    )
    capacidade_padrao = models.PositiveSmallIntegerField(
        "capacidade padrão",
        validators=[MinValueValidator(2)],
        help_text="Total de jogadores por partida. Ex.: 14 para society (7 x 7).",
    )

    class Meta:
        verbose_name = "quadra"
        verbose_name_plural = "quadras"
        ordering = ["arena__nome", "nome_ou_numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["arena", "nome_ou_numero"], name="court_nome_unico_por_arena"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.nome_ou_numero} · {self.arena}"


# --- Agenda ------------------------------------------------------------------


class TimeSlot(ValidatedModel):
    """Horário na agenda de uma quadra: reserva, bloqueio ou horário ocioso."""

    court = models.ForeignKey(
        Court, on_delete=models.CASCADE, related_name="horarios", verbose_name="quadra"
    )
    data = models.DateField("data")
    hora_inicio = models.TimeField("hora de início")
    hora_fim = models.TimeField(
        "hora de término",
        help_text="Use 00:00 para horários que terminam à meia-noite.",
    )
    tipo_reserva = models.CharField(
        "tipo de reserva",
        max_length=20,
        choices=TipoReserva.choices,
        default=TipoReserva.AVULSO,
    )
    status = models.CharField(
        "status",
        max_length=20,
        choices=StatusHorario.choices,
        default=StatusHorario.CONFIRMADO,
    )

    class Meta:
        verbose_name = "horário"
        verbose_name_plural = "horários"
        ordering = ["data", "hora_inicio"]
        indexes = [models.Index(fields=["court", "data"], name="timeslot_court_data_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(hora_fim__gt=F("hora_inicio")) | Q(hora_fim=MEIA_NOITE),
                name="timeslot_fim_apos_inicio",
                violation_error_message="A hora de término deve ser posterior à hora de início.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.court} · {self.data:%d/%m/%Y} {self.intervalo}"

    @property
    def intervalo(self) -> str:
        """Faixa de horário no formato ``19:00–20:00``."""
        return f"{self.hora_inicio:%H:%M}–{self.hora_fim:%H:%M}"

    @property
    def inicio(self) -> datetime:
        """Data e hora de início, no fuso horário do projeto."""
        return timezone.make_aware(datetime.combine(self.data, self.hora_inicio))

    @property
    def fim(self) -> datetime:
        """Data e hora de término (00:00 é a meia-noite do dia seguinte)."""
        dia = self.data + timedelta(days=1) if self.hora_fim == MEIA_NOITE else self.data
        return timezone.make_aware(datetime.combine(dia, self.hora_fim))

    @property
    def ja_comecou(self) -> bool:
        """Indica se o horário já começou."""
        return self.inicio <= timezone.now()

    def clean(self) -> None:
        """Valida a janela de horário, conflitos na agenda e a partida vinculada."""
        super().clean()
        if self.hora_inicio is None or self.hora_fim is None:
            return  # Os campos ausentes já foram reportados por clean_fields().
        if self.hora_fim != MEIA_NOITE and self.hora_fim <= self.hora_inicio:
            raise ValidationError(
                {"hora_fim": "A hora de término deve ser posterior à hora de início."}
            )
        if self.court_id is not None and self.data is not None:
            self._validar_sobreposicao()
        self._validar_partida_ativa()

    def _validar_sobreposicao(self) -> None:
        """Impede horários sobrepostos na mesma quadra e no mesmo dia.

        Os intervalos são semiabertos, [início, fim): 19h-20h e 20h-21h não
        conflitam. Horários de qualquer status ocupam a agenda; para reaproveitar
        um horário cancelado, altere-o em vez de criar outro.
        """
        conflitos = (
            TimeSlot.objects.filter(court_id=self.court_id, data=self.data)
            .exclude(pk=self.pk)
            # O outro termina depois que este começa (00:00 = fim do dia)...
            .filter(Q(hora_fim__gt=self.hora_inicio) | Q(hora_fim=MEIA_NOITE))
        )
        if self.hora_fim != MEIA_NOITE:
            # ...e começa antes que este termine.
            conflitos = conflitos.filter(hora_inicio__lt=self.hora_fim)
        conflito = conflitos.order_by("hora_inicio").first()
        if conflito is not None:
            raise ValidationError(
                "Conflito de agenda: esta quadra já tem o horário "
                f"{conflito.hora_inicio:%H:%M}–{conflito.hora_fim:%H:%M} "
                f"({conflito.get_status_display()}) em {self.data:%d/%m/%Y}.",
                code="sobreposicao",
            )

    def _validar_partida_ativa(self) -> None:
        """Um horário com partida aberta ativa precisa continuar Ocioso ou Cancelado."""
        if self._state.adding or self.status in STATUS_HORARIO_LIVRE:
            return
        tem_partida_ativa = OpenMatch.objects.filter(
            time_slot_id=self.pk, status__in=STATUS_PARTIDA_ATIVA
        ).exists()
        if tem_partida_ativa:
            raise ValidationError(
                "Este horário tem uma partida aberta em andamento. Cancele ou finalize "
                f"a partida antes de marcar o horário como {self.get_status_display()}.",
                code="horario_com_partida_ativa",
            )


# --- Partidas abertas (B2C) --------------------------------------------------


class OpenMatchQuerySet(models.QuerySet):
    """Consultas de partidas compartilhadas pela vitrine web, pela API e pelo admin."""

    def com_relacionados(self) -> Self:
        """Carrega horário, quadra e arena na mesma consulta (evita N+1)."""
        return self.select_related("time_slot__court__arena")

    def com_confirmados(self) -> Self:
        """Anota ``num_confirmados``: jogadores com vaga paga que seguem na partida."""
        return self.annotate(
            num_confirmados=Count(
                "inscricoes",
                filter=Q(
                    inscricoes__status=StatusInscricao.CONFIRMADA,
                    inscricoes__repasse_solicitado_em__isnull=True,
                ),
            )
        )

    def futuras(self) -> Self:
        """Partidas cujo horário ainda não começou."""
        agora = timezone.localtime()
        return self.filter(
            Q(time_slot__data__gt=agora.date())
            | Q(time_slot__data=agora.date(), time_slot__hora_inicio__gt=agora.time())
        )

    def vitrine(self) -> Self:
        """Partidas exibidas aos jogadores: Aberta ou Lotada e ainda por começar."""
        return (
            self.futuras()
            .filter(status__in=STATUS_PARTIDA_ATIVA)
            .com_relacionados()
            .com_confirmados()
            .order_by("time_slot__data", "time_slot__hora_inicio")
        )

    def para_o_nivel(self, nivel: int) -> Self:
        """Partidas cuja faixa aceita jogadores do ``nivel``."""
        categorias = [
            categoria for categoria, (minimo, maximo) in FAIXAS_DE_NIVEL.items() if minimo <= nivel <= maximo
        ]
        return self.filter(nivel_competitividade__in=categorias)

    def filtrar(
        self,
        *,
        nivel: str | None = None,
        piso: str | None = None,
        arena: str | None = None,
        de: date | None = None,
        ate: date | None = None,
    ) -> Self:
        """Aplica os filtros opcionais da vitrine (``arena`` é o slug da arena)."""
        filtros: dict[str, Any] = {
            "nivel_competitividade": nivel,
            "time_slot__court__tipo_piso": piso,
            "time_slot__court__arena__slug": arena,
            "time_slot__data__gte": de,
            "time_slot__data__lte": ate,
        }
        return self.filter(**{campo: valor for campo, valor in filtros.items() if valor})


class OpenMatch(ValidatedModel):
    """Partida aberta à comunidade, criada a partir de um horário livre da agenda.

    Motor financeiro: o gestor define o valor total do aluguel e as vagas. Goleiros
    não pagam, então o aluguel é dividido entre as vagas de linha; o sistema soma a
    taxa de serviço da plataforma (percentual com valor mínimo), paga pelo jogador.
    Com todas as vagas de linha pagas, a quadra recebe o aluguel cheio.
    """

    time_slot = models.OneToOneField(
        TimeSlot,
        on_delete=models.CASCADE,
        related_name="partida_aberta",
        verbose_name="horário",
    )
    vagas_totais = models.PositiveSmallIntegerField(
        "vagas totais",
        validators=[MinValueValidator(1)],
        help_text="Total de jogadores, incluindo os goleiros.",
    )
    vagas_goleiro = models.PositiveSmallIntegerField(
        "vagas de goleiro",
        default=0,
        help_text="Goleiros não pagam; o aluguel é dividido entre as vagas de linha.",
    )
    # Derivado das inscrições. PositiveSmallIntegerField também cria CHECK (>= 0) no banco.
    vagas_disponiveis = models.PositiveSmallIntegerField(
        "vagas disponíveis",
        default=0,
        editable=False,
        help_text="Calculado automaticamente: vagas totais menos inscrições pagas ou em pagamento.",
    )
    valor_total_aluguel = models.DecimalField(
        "valor total do aluguel (R$)",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(CENTAVO)],
        help_text="Quanto a quadra recebe com todas as vagas de linha vendidas.",
    )
    taxa_plataforma_percentual = models.DecimalField(
        "taxa da plataforma (%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Em branco, usa o contrato da arena.",
    )
    taxa_minima = models.DecimalField(
        "taxa mínima por vaga (R$)",
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Em branco, usa o contrato da arena.",
    )
    quorum_percentual = models.PositiveSmallIntegerField(
        "mínimo para confirmar (%)",
        null=True,
        blank=True,
        validators=[MaxValueValidator(100)],
        help_text="Em branco, usa o padrão da arena.",
    )
    horas_prazo_quorum = models.PositiveSmallIntegerField(
        "prazo do mínimo (horas antes do jogo)",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(48)],
        help_text="Em branco, usa o padrão da arena.",
    )
    nivel_competitividade = models.CharField(
        "nível da partida",
        max_length=20,
        choices=NivelCompetitividade.choices,
        default=NivelCompetitividade.ABERTA,
        help_text="Define a faixa de níveis de jogador aceita.",
    )
    status = models.CharField(
        "status",
        max_length=20,
        choices=StatusPartida.choices,
        default=StatusPartida.ABERTA,
        help_text="Aberta e Lotada são definidos automaticamente pelas vagas. "
        "Finalizada e Cancelada encerram a partida.",
    )
    quorum_conferido_em = models.DateTimeField(
        "mínimo conferido em", null=True, blank=True, editable=False
    )
    motivo_cancelamento = models.CharField(
        "motivo do cancelamento",
        max_length=20,
        choices=MotivoCancelamento.choices,
        blank=True,
        editable=False,
    )
    cancelada_em = models.DateTimeField("cancelada em", null=True, blank=True, editable=False)

    objects = OpenMatchQuerySet.as_manager()

    class Meta:
        verbose_name = "partida aberta"
        verbose_name_plural = "partidas abertas"
        ordering = ["time_slot__data", "time_slot__hora_inicio"]
        indexes = [models.Index(fields=["status"], name="openmatch_status_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(vagas_disponiveis__lte=F("vagas_totais")),
                name="openmatch_vagas_disponiveis_lte_totais",
                violation_error_message="As vagas disponíveis não podem ultrapassar as vagas totais.",
            ),
            models.CheckConstraint(
                condition=Q(vagas_goleiro__lt=F("vagas_totais")),
                name="openmatch_ao_menos_uma_vaga_de_linha",
                violation_error_message="A partida precisa de pelo menos uma vaga de linha.",
            ),
        ]

    def __str__(self) -> str:
        return f"Partida · {self.time_slot}"

    def get_absolute_url(self) -> str:
        return reverse("arena:partida_detalhe", args=[self.pk])

    # --- Vagas -----------------------------------------------------------------

    @property
    def vagas_linha(self) -> int:
        """Vagas pagas (todas, menos as de goleiro)."""
        return (self.vagas_totais or 0) - (self.vagas_goleiro or 0)

    def capacidade(self, posicao: str) -> int:
        """Quantas vagas a partida tem para a ``posicao``."""
        return self.vagas_goleiro if posicao == Posicao.GOLEIRO else self.vagas_linha

    def vagas_livres(self, posicao: str) -> int:
        """Vagas da ``posicao`` ainda não ocupadas por inscrições pagas ou em pagamento."""
        ocupadas = Booking.objects.filter(open_match_id=self.pk, posicao=posicao).ocupando().count()
        return max(self.capacidade(posicao) - ocupadas, 0)

    @property
    def vagas_ocupadas(self) -> int:
        """Quantidade de vagas já ocupadas por inscrições pagas ou em pagamento."""
        return self.vagas_totais - self.vagas_disponiveis

    @property
    def percentual_ocupado(self) -> int:
        """Ocupação de 0 a 100, usada nas barras de progresso."""
        if not self.vagas_totais:
            return 0
        return round(100 * self.vagas_ocupadas / self.vagas_totais)

    @property
    def aceita_inscricoes(self) -> bool:
        """Indica se a partida está aberta (com vaga) e ainda não começou."""
        return self.status == StatusPartida.ABERTA and not self.time_slot.ja_comecou

    # --- Preços ----------------------------------------------------------------

    @property
    def preco_vaga_base(self) -> Decimal:
        """Parte da quadra em cada vaga de linha, truncada no centavo.

        O resíduo do rateio é conciliado em ``ajuste_repasse_fechamento`` quando
        todas as vagas de linha são pagas. Assim, R$ 200 ÷ 14 aparece como
        R$ 14,28, sem reduzir o repasse total da quadra.
        """
        if self.vagas_linha <= 0 or self.valor_total_aluguel is None:
            return ZERO
        return (self.valor_total_aluguel / self.vagas_linha).quantize(CENTAVO, rounding=ROUND_DOWN)

    @property
    def valor_taxa_vaga(self) -> Decimal:
        """Taxa de serviço por vaga de linha: percentual do contrato, com valor mínimo."""
        base = self.preco_vaga_base
        if not base:
            return ZERO
        percentual = (
            TAXA_PLATAFORMA_PADRAO
            if self.taxa_plataforma_percentual is None
            else self.taxa_plataforma_percentual
        )
        minima = TAXA_MINIMA_PADRAO if self.taxa_minima is None else self.taxa_minima
        return max(arredondar(base * percentual / 100), minima)

    @property
    def preco_final_jogador(self) -> Decimal:
        """Preço da vaga de linha no Pix (ou com crédito): parte da quadra + taxa."""
        return self.preco_vaga_base + self.valor_taxa_vaga

    @property
    def preco_cartao(self) -> Decimal:
        """Preço da vaga de linha no cartão, com o acréscimo que cobre a tarifa."""
        return self.preco_final_jogador + calcular_acrescimo_cartao(self.preco_final_jogador)

    def valores_da_vaga(self, posicao: str, metodo: str) -> tuple[Decimal, Decimal, Decimal]:
        """Parte da quadra, taxa de serviço e acréscimo do cartão de uma vaga."""
        if posicao == Posicao.GOLEIRO:
            return ZERO, ZERO, ZERO
        vaga, taxa = self.preco_vaga_base, self.valor_taxa_vaga
        acrescimo = calcular_acrescimo_cartao(vaga + taxa) if metodo == MetodoPagamento.CARTAO else ZERO
        return vaga, taxa, acrescimo

    @property
    def ajuste_repasse_fechamento(self) -> Decimal:
        """Resíduo do rateio devido à arena quando todas as vagas de linha estão pagas.

        O ajuste sai da receita agregada da plataforma. Ele não altera o preço
        anunciado nem a parcela individual congelada em cada inscrição.
        """
        if (
            self.status == StatusPartida.CANCELADA
            or self.vagas_linha <= 0
            or self.valor_total_aluguel is None
        ):
            return ZERO
        pagas = Booking.objects.filter(
            open_match_id=self.pk, posicao=Posicao.LINHA, status=StatusInscricao.CONFIRMADA
        ).count()
        if pagas < self.vagas_linha:
            return ZERO
        residuo = self.valor_total_aluguel - self.preco_vaga_base * self.vagas_linha
        return max(residuo, ZERO).quantize(CENTAVO)

    # --- Nível ----------------------------------------------------------------

    @property
    def faixa_nivel(self) -> tuple[int, int]:
        """Níveis de jogador aceitos (mínimo, máximo)."""
        return FAIXAS_DE_NIVEL.get(self.nivel_competitividade, (1, 5))

    @property
    def rotulo_faixa(self) -> str:
        minimo, maximo = self.faixa_nivel
        if (minimo, maximo) == (1, 5):
            return "todos os níveis"
        return f"níveis {minimo} a {maximo}"

    @property
    def liberacao_de_nivel(self) -> datetime:
        """A partir de quando a partida aceita qualquer nível (se ainda houver vaga)."""
        return self.prazo_quorum - timedelta(hours=HORAS_LIBERACAO_NIVEL_ANTES_DO_QUORUM)

    @property
    def nivel_liberado(self) -> bool:
        return timezone.now() >= self.liberacao_de_nivel

    def aceita_nivel(self, nivel: int) -> bool:
        """O jogador desse nível pode entrar (na faixa ou com a trava já liberada)."""
        minimo, maximo = self.faixa_nivel
        return minimo <= nivel <= maximo or self.nivel_liberado

    # --- Mínimo de jogadores (quórum) -------------------------------------------

    @property
    def minimo_jogadores(self) -> int:
        """Jogadores pagos necessários até o prazo para a partida acontecer."""
        percentual = (
            QUORUM_PERCENTUAL_PADRAO if self.quorum_percentual is None else self.quorum_percentual
        )
        return math.ceil((self.vagas_totais or 0) * percentual / 100)

    @property
    def prazo_quorum(self) -> datetime:
        """Momento em que o mínimo de jogadores é conferido."""
        horas = self.horas_prazo_quorum or HORAS_PRAZO_QUORUM_PADRAO
        return self.time_slot.inicio - timedelta(hours=horas)

    @property
    def jogadores_confirmados(self) -> int:
        """Jogadores com vaga paga que seguem na partida (usa a anotação da vitrine)."""
        anotado = getattr(self, "num_confirmados", None)
        if anotado is not None:
            return anotado
        return Booking.objects.filter(open_match_id=self.pk).confirmadas().count()

    @property
    def faltam_para_confirmar(self) -> int:
        """Quantos jogadores pagos ainda faltam para atingir o mínimo."""
        return max(self.minimo_jogadores - self.jogadores_confirmados, 0)

    @property
    def jogo_confirmado(self) -> bool:
        """O mínimo de jogadores pagos já foi atingido."""
        return self.faltam_para_confirmar == 0

    # --- Validação -------------------------------------------------------------

    def clean(self) -> None:
        """Aplica o contrato da arena, valida horário e preço e recalcula as vagas."""
        super().clean()
        self._aplicar_contrato_da_arena()
        if self.status in STATUS_PARTIDA_ATIVA:
            self._validar_horario_livre()
        self._validar_preco_travado()
        if self.vagas_totais is not None:
            self._recalcular_vagas()

    def _aplicar_contrato_da_arena(self) -> None:
        """Copia da arena a taxa e as regras de quórum que não foram definidas na partida."""
        try:
            arena = self.time_slot.court.arena
        except ObjectDoesNotExist:
            return  # FK ausente ou inválida: o erro já foi reportado por clean_fields().
        for campo in ("taxa_plataforma_percentual", "taxa_minima", "quorum_percentual", "horas_prazo_quorum"):
            if getattr(self, campo) is None:
                setattr(self, campo, getattr(arena, campo))

    def _validar_preco_travado(self) -> None:
        """Depois da primeira inscrição ativa, aluguel, vagas e taxa não mudam.

        Assim todos os jogadores da partida pagam o mesmo valor e a soma das vagas
        continua cobrindo o aluguel combinado com a quadra.
        """
        if self._state.adding:
            return
        campos = (
            "valor_total_aluguel",
            "vagas_totais",
            "vagas_goleiro",
            "taxa_plataforma_percentual",
            "taxa_minima",
        )
        salvo = OpenMatch.objects.filter(pk=self.pk).values(*campos).first()
        if salvo is None or all(salvo[campo] == getattr(self, campo) for campo in campos):
            return
        ativas = Booking.objects.filter(open_match_id=self.pk, status__in=STATUS_INSCRICAO_ATIVA)
        if ativas.exists():
            raise ValidationError(
                "O aluguel, as vagas e a taxa ficam travados depois da primeira inscrição. "
                "Para mudar, cancele a partida e abra outra.",
                code="preco_travado",
            )

    def atualizar_vagas(self) -> None:
        """Recalcula e persiste as vagas e o status depois de mudanças nas inscrições."""
        self.save(update_fields=["vagas_disponiveis", "status", "updated_at"])

    def _validar_horario_livre(self) -> None:
        """Partidas ativas exigem horário Ocioso ou Cancelado. Partidas novas, horário futuro."""
        try:
            horario = self.time_slot
        except ObjectDoesNotExist:
            return  # FK ausente ou inválida: o erro já foi reportado por clean_fields().
        if horario.status not in STATUS_HORARIO_LIVRE:
            raise ValidationError(
                "Só é possível abrir partidas em horários Ocioso ou Cancelado. "
                f"Este horário está {horario.get_status_display()}.",
                code="horario_indisponivel",
            )
        if self._state.adding and horario.ja_comecou:
            raise ValidationError(
                "Não é possível abrir uma partida em um horário que já começou.",
                code="horario_passado",
            )

    def _recalcular_vagas(self) -> None:
        """Deriva ``vagas_disponiveis`` das inscrições e sincroniza Aberta/Lotada.

        Recalcular a partir das inscrições, em vez de incrementar ou decrementar
        um contador, impede que o valor se desvie com o tempo. Reservas vencidas
        deixam de contar mesmo antes de a rotina de expiração passar.
        """
        ocupadas = (
            0
            if self._state.adding
            else Booking.objects.filter(open_match_id=self.pk).ocupando().count()
        )
        if ocupadas > self.vagas_totais:
            raise ValidationError(
                {
                    "vagas_totais": f"A partida já tem {ocupadas} inscrições ativas, "
                    "então as vagas totais não podem ficar abaixo disso."
                }
            )
        self.vagas_disponiveis = self.vagas_totais - ocupadas
        if self.status in STATUS_PARTIDA_ATIVA:
            self.status = (
                StatusPartida.LOTADA if self.vagas_disponiveis == 0 else StatusPartida.ABERTA
            )


class BookingQuerySet(models.QuerySet):
    """Consultas de inscrições usadas no cálculo de vagas, no quórum e nas rotinas."""

    def ocupando(self, agora: datetime | None = None) -> Self:
        """Inscrições que ocupam vaga: confirmadas (fora de repasse) e reservas no prazo."""
        agora = agora or timezone.now()
        return self.filter(
            Q(status=StatusInscricao.CONFIRMADA, repasse_solicitado_em__isnull=True)
            | Q(status=StatusInscricao.AGUARDANDO_PAGAMENTO, reservada_ate__gt=agora)
        )

    def confirmadas(self) -> Self:
        """Jogadores com vaga paga que seguem na partida (fora de repasse)."""
        return self.filter(status=StatusInscricao.CONFIRMADA, repasse_solicitado_em__isnull=True)

    def reservas_vencidas(self, agora: datetime | None = None) -> Self:
        """Reservas cujo prazo de pagamento terminou."""
        return self.filter(
            status=StatusInscricao.AGUARDANDO_PAGAMENTO,
            reservada_ate__lte=agora or timezone.now(),
        )


# Transições permitidas entre os status da inscrição. Expirada volta a Confirmada
# quando o pagamento é aprovado depois do prazo e ainda há vaga.
_TRANSICOES_INSCRICAO = {
    StatusInscricao.AGUARDANDO_PAGAMENTO: {
        StatusInscricao.CONFIRMADA,
        StatusInscricao.EXPIRADA,
        StatusInscricao.CANCELADA,
    },
    StatusInscricao.EXPIRADA: {StatusInscricao.CONFIRMADA},
    StatusInscricao.CONFIRMADA: {StatusInscricao.CANCELADA, StatusInscricao.REEMBOLSADA},
    StatusInscricao.CANCELADA: set(),
    StatusInscricao.REEMBOLSADA: set(),
}


def _ocupa(status: str, reservada_ate: datetime | None, repasse_em: datetime | None) -> bool:
    """Regra única de ocupação de vaga (espelha ``BookingQuerySet.ocupando``)."""
    if status == StatusInscricao.CONFIRMADA:
        return repasse_em is None
    if status == StatusInscricao.AGUARDANDO_PAGAMENTO:
        return reservada_ate is not None and reservada_ate > timezone.now()
    return False


class Booking(ValidatedModel):
    """Inscrição de um jogador em uma partida aberta.

    Nasce como reserva (aguardando pagamento), que segura a vaga por
    ``MINUTOS_RESERVA``. O pagamento aprovado a confirma; sem pagamento, ela
    expira. Os valores (parte da quadra, taxa e acréscimo do cartão) são
    congelados na criação. Inscrições nunca são apagadas: mudanças de status
    passam por ``save()``, que valida a transição e recalcula as vagas.
    """

    open_match = models.ForeignKey(
        OpenMatch,
        on_delete=models.PROTECT,
        related_name="inscricoes",
        verbose_name="partida",
    )
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="inscricoes",
        limit_choices_to={"is_player": True},
        verbose_name="jogador",
    )
    posicao = models.CharField(
        "posição", max_length=10, choices=Posicao.choices, default=Posicao.LINHA
    )
    status = models.CharField(
        "status",
        max_length=25,
        choices=StatusInscricao.choices,
        default=StatusInscricao.AGUARDANDO_PAGAMENTO,
    )
    metodo_pagamento = models.CharField(
        "forma de pagamento",
        max_length=10,
        choices=MetodoPagamento.choices,
        default=MetodoPagamento.PIX,
    )
    data_inscricao = models.DateTimeField("data de inscrição", default=timezone.now)
    reservada_ate = models.DateTimeField(
        "vaga reservada até",
        null=True,
        blank=True,
        help_text="Prazo para concluir o pagamento; depois dele, a vaga volta para a partida.",
    )
    confirmada_em = models.DateTimeField("confirmada em", null=True, blank=True)
    cancelada_em = models.DateTimeField("cancelada em", null=True, blank=True)
    repasse_solicitado_em = models.DateTimeField(
        "repasse solicitado em",
        null=True,
        blank=True,
        help_text="O jogador liberou a vaga para a lista de espera.",
    )
    valor_vaga = models.DecimalField(
        "valor para a quadra (R$)",
        max_digits=8,
        decimal_places=2,
        default=ZERO,
        editable=False,
        help_text="Parte do aluguel paga nesta vaga (repasse à quadra), congelada na inscrição.",
    )
    valor_taxa = models.DecimalField(
        "taxa de serviço (R$)",
        max_digits=8,
        decimal_places=2,
        default=ZERO,
        editable=False,
        help_text="Receita da plataforma nesta vaga, congelada na inscrição.",
    )
    valor_acrescimo = models.DecimalField(
        "acréscimo do cartão (R$)",
        max_digits=8,
        decimal_places=2,
        default=ZERO,
        editable=False,
    )
    check_in_em = models.DateTimeField("check-in em", null=True, blank=True)
    faltou = models.BooleanField(
        "faltou",
        default=False,
        help_text="Marcado no encerramento quando a arena fez check-in e o jogador não apareceu.",
    )

    objects = BookingQuerySet.as_manager()

    class Meta:
        verbose_name = "inscrição"
        verbose_name_plural = "inscrições"
        ordering = ["-data_inscricao"]
        constraints = [
            # Inscrições encerradas ficam no histórico e não impedem uma nova inscrição.
            models.UniqueConstraint(
                fields=["open_match", "player"],
                condition=Q(status__in=STATUS_INSCRICAO_ATIVA),
                name="booking_inscricao_ativa_unica",
                violation_error_message="Este jogador já tem uma inscrição ativa nesta partida.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.player} · {self.open_match.time_slot}"

    @property
    def valor_total(self) -> Decimal:
        """Valor pago pelo jogador: parte da quadra + taxa + acréscimo do cartão."""
        return self.valor_vaga + self.valor_taxa + self.valor_acrescimo

    @property
    def ocupa_vaga(self) -> bool:
        """Indica se a inscrição ocupa vaga agora."""
        return _ocupa(self.status, self.reservada_ate, self.repasse_solicitado_em)

    @property
    def em_repasse(self) -> bool:
        """O jogador pagou, mas liberou a vaga para a lista de espera."""
        return self.status == StatusInscricao.CONFIRMADA and self.repasse_solicitado_em is not None

    @property
    def reserva_vencida(self) -> bool:
        """Reserva cujo prazo de pagamento terminou (a rotina ainda vai expirá-la)."""
        return (
            self.status == StatusInscricao.AGUARDANDO_PAGAMENTO
            and self.reservada_ate is not None
            and self.reservada_ate <= timezone.now()
        )

    @property
    def gratuita(self) -> bool:
        return self.metodo_pagamento == MetodoPagamento.GRATUITO

    @property
    def prazo_credito(self) -> datetime:
        """Até quando o cancelamento devolve o valor como crédito integral."""
        return self.open_match.time_slot.inicio - timedelta(hours=HORAS_CANCELAMENTO_COM_CREDITO)

    @property
    def pode_cancelar(self) -> bool:
        """Reservas podem ser canceladas; vagas pagas, até 24h antes (com crédito)."""
        if self.open_match.time_slot.ja_comecou:
            return False
        if self.status == StatusInscricao.AGUARDANDO_PAGAMENTO:
            return True
        if self.status != StatusInscricao.CONFIRMADA or self.em_repasse:
            return False
        return self.gratuita or timezone.now() < self.prazo_credito

    @property
    def pode_repassar(self) -> bool:
        """Nas últimas 24h, a vaga paga não é reembolsada, mas pode ir para a lista de espera."""
        return (
            self.status == StatusInscricao.CONFIRMADA
            and not self.gratuita
            and not self.em_repasse
            and self.prazo_credito <= timezone.now() < self.open_match.time_slot.inicio
        )

    def clean(self) -> None:
        """Impede a troca de partida ou jogador, valida a transição e a vaga em novas ocupações."""
        super().clean()
        anterior = self._estado_anterior()
        if anterior is not None:
            if (
                anterior["open_match_id"] != self.open_match_id
                or anterior["player_id"] != self.player_id
            ):
                raise ValidationError(
                    "Não é possível trocar a partida ou o jogador de uma inscrição. "
                    "Cancele esta inscrição e crie outra.",
                    code="inscricao_imutavel",
                )
            de, para = anterior["status"], self.status
            if de != para and para not in _TRANSICOES_INSCRICAO.get(de, set()):
                raise ValidationError(
                    f"Não é possível passar a inscrição de {StatusInscricao(de).label.lower()} "
                    f"para {StatusInscricao(para).label.lower()}.",
                    code="transicao_invalida",
                )
        ocupava = anterior is not None and _ocupa(
            anterior["status"], anterior["reservada_ate"], anterior["repasse_solicitado_em"]
        )
        if self.ocupa_vaga and not ocupava:
            self._validar_nova_ocupacao()

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Valida e salva com a partida bloqueada e depois recalcula as vagas.

        A partida é recarregada com ``select_for_update()`` (bloqueio de linha no
        PostgreSQL) para serializar inscrições concorrentes na última vaga.
        Na criação, os valores da vaga são congelados a partir da partida.
        """
        with transaction.atomic():
            try:
                self.open_match = OpenMatch.objects.select_for_update().get(
                    pk=self.open_match_id
                )
            except OpenMatch.DoesNotExist:
                pass  # full_clean() reportará a partida ausente ou inválida.
            else:
                if self._state.adding:
                    self._congelar_valores()
            super().save(*args, **kwargs)
            self.open_match.atualizar_vagas()

    def _congelar_valores(self) -> None:
        """Copia os valores da vaga e define os prazos iniciais da inscrição."""
        if self.posicao == Posicao.GOLEIRO:
            self.metodo_pagamento = MetodoPagamento.GRATUITO
        self.valor_vaga, self.valor_taxa, self.valor_acrescimo = self.open_match.valores_da_vaga(
            self.posicao, self.metodo_pagamento
        )
        agora = timezone.now()
        if self.status == StatusInscricao.AGUARDANDO_PAGAMENTO and self.reservada_ate is None:
            self.reservada_ate = agora + timedelta(minutes=MINUTOS_RESERVA)
        if self.status == StatusInscricao.CONFIRMADA and self.confirmada_em is None:
            self.confirmada_em = agora

    def _estado_anterior(self) -> dict[str, Any] | None:
        """Lê do banco os valores já salvos (``None`` para inscrições novas)."""
        if self._state.adding:
            return None
        return (
            Booking.objects.filter(pk=self.pk)
            .values("open_match_id", "player_id", "status", "reservada_ate", "repasse_solicitado_em")
            .first()
        )

    def _validar_nova_ocupacao(self) -> None:
        """Valida uma ocupação nova: partida ativa, não iniciada e com vaga na posição."""
        try:
            partida = self.open_match
        except ObjectDoesNotExist:
            return  # FK ausente ou inválida: o erro já foi reportado por clean_fields().
        if partida.status not in STATUS_PARTIDA_ATIVA:
            raise ValidationError(
                f"Esta partida está {partida.get_status_display().lower()} "
                "e não aceita inscrições.",
                code="partida_indisponivel",
            )
        if partida.time_slot.ja_comecou:
            raise ValidationError(
                "Esta partida já começou. Não é possível se inscrever.",
                code="partida_iniciada",
            )
        ocupadas = (
            Booking.objects.filter(open_match_id=partida.pk, posicao=self.posicao)
            .ocupando()
            .exclude(pk=self.pk)
            .count()
        )
        if ocupadas >= partida.capacidade(self.posicao):
            if self.posicao == Posicao.GOLEIRO:
                raise ValidationError(
                    "Não há vaga de goleiro disponível nesta partida.", code="sem_vaga_goleiro"
                )
            raise ValidationError("Esta partida está lotada.", code="partida_lotada")


@receiver(post_delete, sender=Booking, dispatch_uid="arena_booking_devolver_vaga")
def devolver_vaga_apos_exclusao(sender: type[Booking], instance: Booking, **kwargs: Any) -> None:
    """Recalcula as vagas quando uma inscrição é excluída, inclusive em massa.

    ``QuerySet.delete()`` não chama ``Model.delete()``, mas dispara este sinal
    para cada objeto excluído.
    """
    try:
        partida = OpenMatch.objects.select_for_update().get(pk=instance.open_match_id)
    except OpenMatch.DoesNotExist:
        return
    partida.atualizar_vagas()


class WaitlistEntry(BaseModel):
    """Jogador na lista de espera de uma partida, avisado quando uma vaga abre."""

    partida = models.ForeignKey(
        OpenMatch,
        on_delete=models.CASCADE,
        related_name="lista_de_espera",
        verbose_name="partida",
    )
    jogador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="listas_de_espera",
        verbose_name="jogador",
    )
    posicao = models.CharField(
        "posição", max_length=10, choices=Posicao.choices, default=Posicao.LINHA
    )
    notificado_em = models.DateTimeField("avisado em", null=True, blank=True)

    class Meta:
        verbose_name = "lugar na lista de espera"
        verbose_name_plural = "lista de espera"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["partida", "jogador"], name="lista_espera_unica"),
        ]

    def __str__(self) -> str:
        return f"{self.jogador} · {self.partida.time_slot}"


# --- Jogadores: perfil, avaliações e elogios ----------------------------------


class PlayerProfile(ValidatedModel):
    """Perfil esportivo do jogador: nível, posição e região.

    O nível nasce do questionário do cadastro e pode ser ajustado pela comunidade
    (sinais de colegas diferentes depois dos jogos).
    """

    jogador = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil",
        verbose_name="jogador",
    )
    apelido = models.CharField("apelido", max_length=30, blank=True)
    posicao = models.CharField("posição", max_length=10, choices=PosicaoJogador.choices)
    joga_no_gol = models.BooleanField(
        "também joga no gol", default=False, help_text="Pode pegar a vaga (grátis) de goleiro."
    )
    nivel = models.PositiveSmallIntegerField(
        "nível",
        choices=NivelJogador.choices,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    nivel_origem = models.CharField(
        "origem do nível", max_length=10, choices=OrigemNivel.choices, default=OrigemNivel.DECLARADO
    )
    nivel_ajustado_em = models.DateTimeField("nível ajustado em", null=True, blank=True)
    regiao = models.CharField("bairro ou região", max_length=80, blank=True)
    goleiro_suspenso_ate = models.DateField(
        "vaga de goleiro suspensa até",
        null=True,
        blank=True,
        help_text="Goleiro que falta sem avisar perde a vaga grátis por um período.",
    )

    class Meta:
        verbose_name = "perfil de jogador"
        verbose_name_plural = "perfis de jogadores"

    def __str__(self) -> str:
        return f"{self.jogador} · nível {self.nivel}"

    @property
    def nome_exibicao(self) -> str:
        return self.apelido or self.jogador.nome_publico

    @property
    def goleiro_suspenso(self) -> bool:
        return self.goleiro_suspenso_ate is not None and self.goleiro_suspenso_ate >= timezone.localdate()

    @property
    def pode_ser_goleiro(self) -> bool:
        """Joga no gol (posição ou disposição) e não está suspenso por falta."""
        return (self.posicao == PosicaoJogador.GOLEIRO or self.joga_no_gol) and not self.goleiro_suspenso


class AvaliacaoPartida(BaseModel):
    """Percepção do jogador sobre o nível da partida (um toque depois do jogo)."""

    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="avaliacoes", verbose_name="autor"
    )
    partida = models.ForeignKey(
        OpenMatch, on_delete=models.CASCADE, related_name="avaliacoes", verbose_name="partida"
    )
    percepcao = models.CharField("nível da partida", max_length=10, choices=PercepcaoNivel.choices)

    class Meta:
        verbose_name = "avaliação de partida"
        verbose_name_plural = "avaliações de partidas"
        constraints = [
            models.UniqueConstraint(fields=["autor", "partida"], name="avaliacao_unica_por_partida"),
        ]


class Elogio(BaseModel):
    """Elogio de um jogador a um colega da mesma partida."""

    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="elogios_dados", verbose_name="autor"
    )
    alvo = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="elogios_recebidos",
        verbose_name="elogiado",
    )
    partida = models.ForeignKey(OpenMatch, on_delete=models.CASCADE, related_name="elogios", verbose_name="partida")
    tipo = models.CharField("elogio", max_length=15, choices=TipoElogio.choices)

    class Meta:
        verbose_name = "elogio"
        verbose_name_plural = "elogios"
        constraints = [
            models.UniqueConstraint(fields=["autor", "alvo", "partida", "tipo"], name="elogio_unico"),
            models.CheckConstraint(condition=~Q(autor=F("alvo")), name="elogio_nao_e_para_si"),
        ]


class SinalNivel(BaseModel):
    """Sinal de um colega de que o jogador joga acima ou abaixo do nível da partida."""

    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sinais_dados", verbose_name="autor"
    )
    alvo = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sinais_recebidos",
        verbose_name="jogador sinalizado",
    )
    partida = models.ForeignKey(
        OpenMatch, on_delete=models.CASCADE, related_name="sinais_de_nivel", verbose_name="partida"
    )
    direcao = models.CharField("direção", max_length=10, choices=DirecaoNivel.choices)

    class Meta:
        verbose_name = "sinal de nível"
        verbose_name_plural = "sinais de nível"
        constraints = [
            models.UniqueConstraint(fields=["autor", "alvo", "partida"], name="sinal_unico_por_partida"),
            models.CheckConstraint(condition=~Q(autor=F("alvo")), name="sinal_nao_e_para_si"),
        ]


# --- Pagamentos e razão contábil ---------------------------------------------


class Payment(ValidatedModel):
    """Cobrança de uma inscrição: no gateway (Pix ou cartão) ou com crédito do jogador."""

    booking = models.ForeignKey(
        Booking, on_delete=models.PROTECT, related_name="pagamentos", verbose_name="inscrição"
    )
    metodo = models.CharField("forma de pagamento", max_length=10, choices=MetodoPagamento.choices)
    status = models.CharField(
        "status", max_length=10, choices=StatusPagamento.choices, default=StatusPagamento.PENDENTE
    )
    valor = models.DecimalField("valor cobrado (R$)", max_digits=10, decimal_places=2)
    tarifa_gateway = models.DecimalField(
        "tarifa do gateway (R$)", max_digits=10, decimal_places=2, default=ZERO
    )
    gateway = models.CharField("gateway", max_length=40)
    gateway_id = models.CharField(
        "identificador no gateway", max_length=100, unique=True, null=True, blank=True
    )
    pix_copia_e_cola = models.TextField("Pix copia e cola", blank=True)
    expira_em = models.DateTimeField("expira em", null=True, blank=True)
    aprovado_em = models.DateTimeField("aprovado em", null=True, blank=True)
    estornado_em = models.DateTimeField("estornado em", null=True, blank=True)
    resposta_gateway = models.JSONField("última resposta do gateway", default=dict, blank=True)

    class Meta:
        verbose_name = "pagamento"
        verbose_name_plural = "pagamentos"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_metodo_display()} · {self.valor} · {self.get_status_display()}"


class LedgerAccount(BaseModel):
    """Carteira do razão: de uma arena, da plataforma ou de crédito de um jogador.

    O saldo é sempre a soma dos lançamentos; a carteira não guarda saldo próprio.
    """

    tipo = models.CharField("tipo", max_length=12, choices=TipoConta.choices)
    arena = models.ForeignKey(
        Arena,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contas",
        verbose_name="arena",
    )
    jogador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contas",
        verbose_name="jogador",
    )

    class Meta:
        verbose_name = "carteira"
        verbose_name_plural = "carteiras"
        constraints = [
            models.UniqueConstraint(
                fields=["arena"], condition=Q(tipo=TipoConta.ARENA), name="carteira_unica_por_arena"
            ),
            models.UniqueConstraint(
                fields=["jogador"],
                condition=Q(tipo=TipoConta.JOGADOR),
                name="carteira_unica_por_jogador",
            ),
            models.UniqueConstraint(
                fields=["tipo"],
                condition=Q(tipo=TipoConta.PLATAFORMA),
                name="carteira_unica_da_plataforma",
            ),
            models.CheckConstraint(
                condition=(
                    Q(tipo=TipoConta.ARENA, arena__isnull=False, jogador__isnull=True)
                    | Q(tipo=TipoConta.JOGADOR, jogador__isnull=False, arena__isnull=True)
                    | Q(tipo=TipoConta.PLATAFORMA, arena__isnull=True, jogador__isnull=True)
                ),
                name="carteira_dono_coerente",
            ),
        ]

    def __str__(self) -> str:
        if self.tipo == TipoConta.ARENA:
            return f"Carteira · {self.arena}"
        if self.tipo == TipoConta.JOGADOR:
            return f"Crédito · {self.jogador}"
        return "Carteira · ArenaMatch"


class Payout(ValidatedModel):
    """Repasse (transferência) do saldo disponível de uma arena."""

    arena = models.ForeignKey(
        Arena, on_delete=models.PROTECT, related_name="repasses", verbose_name="arena"
    )
    valor = models.DecimalField("valor (R$)", max_digits=12, decimal_places=2)
    status = models.CharField(
        "status", max_length=10, choices=StatusRepasse.choices, default=StatusRepasse.PAGO
    )
    referencia = models.CharField("referência no gateway", max_length=100, blank=True)

    class Meta:
        verbose_name = "repasse"
        verbose_name_plural = "repasses"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Repasse · {self.arena} · {self.valor}"


class LedgerEntry(ValidatedModel):
    """Lançamento imutável do razão. Correções entram como novos lançamentos (estornos).

    O valor é positivo quando entra na carteira e negativo quando sai. Para as
    arenas, ``disponivel_em`` separa o saldo "a liberar" do saldo disponível.
    """

    conta = models.ForeignKey(
        LedgerAccount, on_delete=models.PROTECT, related_name="lancamentos", verbose_name="carteira"
    )
    tipo = models.CharField("tipo", max_length=20, choices=TipoLancamento.choices)
    valor = models.DecimalField("valor (R$)", max_digits=12, decimal_places=2)
    descricao = models.CharField("descrição", max_length=255)
    disponivel_em = models.DateTimeField(
        "disponível em",
        default=timezone.now,
        help_text="A partir de quando o valor pode ser repassado.",
    )
    partida = models.ForeignKey(
        OpenMatch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lancamentos",
        verbose_name="partida",
    )
    inscricao = models.ForeignKey(
        Booking,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lancamentos",
        verbose_name="inscrição",
    )
    pagamento = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lancamentos",
        verbose_name="pagamento",
    )
    repasse = models.ForeignKey(
        Payout,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lancamentos",
        verbose_name="repasse",
    )

    class Meta:
        verbose_name = "lançamento"
        verbose_name_plural = "lançamentos"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["conta", "disponivel_em"], name="lancamento_conta_disp_idx")]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} · {self.valor}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Lançamentos do razão são imutáveis; registre um estorno.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValidationError("Lançamentos do razão não podem ser apagados.")
