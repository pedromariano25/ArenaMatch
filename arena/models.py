"""Modelos de domínio do ArenaMatch.

As regras de negócio ficam em ``clean()``. ``ValidatedModel.save()`` executa
``full_clean()`` dentro de uma transação, então as regras valem para qualquer
caminho de escrita (Django Admin, actions, API REST, shell), e não apenas para
formulários.
"""

import uuid
from datetime import date, datetime, time, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any, Self

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from .validators import normalizar_documento, validar_cnpj, validar_cpf, validar_telefone

# Usado como ``hora_fim``, 00:00 representa o fim do dia (24:00).
MEIA_NOITE = time(0, 0)

CENTAVO = Decimal("0.01")
# Taxa de serviço da plataforma, cobrada do jogador sobre a parte da quadra em cada vaga.
TAXA_PLATAFORMA_PADRAO = Decimal("15.00")


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


class NivelCompetitividade(models.TextChoices):
    """Nível técnico esperado dos jogadores de uma partida aberta."""

    MISTO = "misto", "Misto"
    INICIANTE = "iniciante", "Iniciante"
    AVANCADO = "avancado", "Avançado"


class StatusPartida(models.TextChoices):
    """Ciclo de vida de uma partida aberta."""

    ABERTA = "aberta", "Aberta"
    LOTADA = "lotada", "Lotada"
    FINALIZADA = "finalizada", "Finalizada"
    CANCELADA = "cancelada", "Cancelada"


class StatusPagamento(models.TextChoices):
    """Situação do pagamento de uma inscrição (registro manual no MVP)."""

    PENDENTE = "pendente", "Pendente"
    PAGO = "pago", "Pago"
    REEMBOLSADO = "reembolsado", "Reembolsado"


# Horários que podem receber uma partida aberta.
STATUS_HORARIO_LIVRE = (StatusHorario.OCIOSO, StatusHorario.CANCELADO)
# Partidas em andamento. Aberta/Lotada são derivados das vagas disponíveis.
STATUS_PARTIDA_ATIVA = (StatusPartida.ABERTA, StatusPartida.LOTADA)
# Inscrições que ocupam vaga. Uma inscrição reembolsada libera a vaga.
STATUS_OCUPA_VAGA = (StatusPagamento.PENDENTE, StatusPagamento.PAGO)


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
            .order_by("time_slot__data", "time_slot__hora_inicio")
        )

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

    Motor financeiro: o gestor define o valor total do aluguel e as vagas; o sistema
    calcula a parte da quadra em cada vaga e soma a taxa de serviço da plataforma,
    paga pelo jogador. Com todas as vagas vendidas, a quadra recebe o aluguel cheio.
    """

    time_slot = models.OneToOneField(
        TimeSlot,
        on_delete=models.CASCADE,
        related_name="partida_aberta",
        verbose_name="horário",
    )
    vagas_totais = models.PositiveSmallIntegerField(
        "vagas totais", validators=[MinValueValidator(1)]
    )
    # Derivado das inscrições. PositiveSmallIntegerField também cria CHECK (>= 0) no banco.
    vagas_disponiveis = models.PositiveSmallIntegerField(
        "vagas disponíveis",
        default=0,
        editable=False,
        help_text="Calculado automaticamente: vagas totais menos inscrições pendentes ou pagas.",
    )
    valor_total_aluguel = models.DecimalField(
        "valor total do aluguel (R$)",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(CENTAVO)],
        help_text="Quanto a quadra recebe com todas as vagas vendidas.",
    )
    taxa_plataforma_percentual = models.DecimalField(
        "taxa da plataforma (%)",
        max_digits=5,
        decimal_places=2,
        default=TAXA_PLATAFORMA_PADRAO,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Taxa de serviço cobrada do jogador sobre a parte da quadra em cada vaga.",
    )
    nivel_competitividade = models.CharField(
        "nível de competitividade",
        max_length=20,
        choices=NivelCompetitividade.choices,
        default=NivelCompetitividade.MISTO,
    )
    status = models.CharField(
        "status",
        max_length=20,
        choices=StatusPartida.choices,
        default=StatusPartida.ABERTA,
        help_text="Aberta e Lotada são definidos automaticamente pelas vagas. "
        "Use Finalizada ou Cancelada para encerrar a partida.",
    )

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
        ]

    def __str__(self) -> str:
        return f"Partida · {self.time_slot}"

    def get_absolute_url(self) -> str:
        return reverse("arena:partida_detalhe", args=[self.pk])

    @property
    def vagas_ocupadas(self) -> int:
        """Quantidade de vagas já ocupadas por inscrições pendentes ou pagas."""
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

    @property
    def preco_vaga_base(self) -> Decimal:
        """Parcela exibida da quadra por vaga, truncada no centavo.

        O resíduo do rateio é conciliado em ``ajuste_repasse_fechamento`` quando
        todas as vagas são ocupadas. Assim, R$ 200 ÷ 14 aparece como R$ 14,28,
        sem reduzir o repasse total da quadra.
        """
        if not self.vagas_totais or self.valor_total_aluguel is None:
            return Decimal("0.00")
        return (self.valor_total_aluguel / self.vagas_totais).quantize(CENTAVO, rounding=ROUND_DOWN)

    @property
    def valor_taxa_vaga(self) -> Decimal:
        """Receita da plataforma por vaga (taxa de conveniência paga pelo jogador)."""
        taxa = self.taxa_plataforma_percentual or Decimal("0")
        return (self.preco_vaga_base * taxa / 100).quantize(CENTAVO, rounding=ROUND_HALF_UP)

    @property
    def preco_final_jogador(self) -> Decimal:
        """Valor cobrado do jogador no app: parte da quadra + taxa de conveniência."""
        return self.preco_vaga_base + self.valor_taxa_vaga

    @property
    def ajuste_repasse_fechamento(self) -> Decimal:
        """Resíduo do aluguel a conciliar no repasse quando todas as vagas forem ocupadas.

        O ajuste sai da receita agregada da plataforma. Ele não altera o preço
        anunciado nem a parcela individual congelada em cada inscrição.
        """
        if (
            self.status == StatusPartida.CANCELADA
            or self.vagas_disponiveis != 0
            or not self.vagas_totais
            or self.valor_total_aluguel is None
        ):
            return Decimal("0.00")
        residuo = self.valor_total_aluguel - self.preco_vaga_base * self.vagas_totais
        return max(residuo, Decimal("0.00")).quantize(CENTAVO)

    def clean(self) -> None:
        """Valida horário e preço e recalcula as vagas disponíveis e o status."""
        super().clean()
        if self.status in STATUS_PARTIDA_ATIVA:
            self._validar_horario_livre()
        self._validar_preco_travado()
        if self.vagas_totais is not None:
            self._recalcular_vagas()

    def _validar_preco_travado(self) -> None:
        """Depois da primeira inscrição ativa, aluguel, vagas e taxa não mudam.

        Assim todos os jogadores da partida pagam o mesmo valor e a soma das vagas
        continua cobrindo o aluguel combinado com a quadra.
        """
        if self._state.adding:
            return
        campos = ("valor_total_aluguel", "vagas_totais", "taxa_plataforma_percentual")
        salvo = OpenMatch.objects.filter(pk=self.pk).values(*campos).first()
        if salvo is None or all(salvo[campo] == getattr(self, campo) for campo in campos):
            return
        if Booking.objects.filter(open_match_id=self.pk, status_pagamento__in=STATUS_OCUPA_VAGA).exists():
            raise ValidationError(
                "O aluguel, as vagas e a taxa ficam travados depois da primeira inscrição. "
                "Para mudar, reembolse as inscrições ou abra outra partida.",
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
        """Deriva ``vagas_disponiveis`` das inscrições ativas e sincroniza Aberta/Lotada.

        Recalcular a partir das inscrições, em vez de incrementar ou decrementar
        um contador, impede que o valor se desvie com o tempo.
        """
        ocupadas = (
            0
            if self._state.adding
            else Booking.objects.filter(
                open_match_id=self.pk, status_pagamento__in=STATUS_OCUPA_VAGA
            ).count()
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


class Booking(ValidatedModel):
    """Inscrição de um jogador em uma partida aberta.

    Os valores da vaga (parte da quadra e taxa da plataforma) são congelados na
    inscrição: relatórios financeiros usam esses valores, e não o preço atual da
    partida. Mudanças de status devem passar por ``save()``, e não por
    ``QuerySet.update()``, para que as vagas da partida sejam recalculadas.
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
    status_pagamento = models.CharField(
        "status do pagamento",
        max_length=20,
        choices=StatusPagamento.choices,
        default=StatusPagamento.PENDENTE,
    )
    data_inscricao = models.DateTimeField("data de inscrição", default=timezone.now)
    valor_vaga = models.DecimalField(
        "valor para a quadra (R$)",
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        help_text="Parte do aluguel paga nesta vaga (repasse à quadra), congelada na inscrição.",
    )
    valor_taxa = models.DecimalField(
        "taxa de conveniência (R$)",
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        help_text="Receita da plataforma nesta vaga, congelada na inscrição.",
    )

    class Meta:
        verbose_name = "inscrição"
        verbose_name_plural = "inscrições"
        ordering = ["-data_inscricao"]
        constraints = [
            # Inscrições reembolsadas ficam no histórico e não impedem uma nova inscrição.
            models.UniqueConstraint(
                fields=["open_match", "player"],
                condition=Q(status_pagamento__in=STATUS_OCUPA_VAGA),
                name="booking_inscricao_ativa_unica",
                violation_error_message="Este jogador já tem uma inscrição ativa nesta partida.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.player} · {self.open_match.time_slot}"

    @property
    def ocupa_vaga(self) -> bool:
        """Indica se a inscrição ocupa vaga (pagamento pendente ou pago)."""
        return self.status_pagamento in STATUS_OCUPA_VAGA

    @property
    def valor_total(self) -> Decimal:
        """Valor pago pelo jogador: parte da quadra + taxa de conveniência."""
        return self.valor_vaga + self.valor_taxa

    @property
    def pode_cancelar(self) -> bool:
        """O jogador pode desistir de inscrições pendentes antes do início da partida."""
        return (
            self.status_pagamento == StatusPagamento.PENDENTE
            and not self.open_match.time_slot.ja_comecou
        )

    def cancelar(self) -> None:
        """Cancela a inscrição pendente: ela é excluída e a vaga volta para a partida.

        Raises:
            ValidationError: se a inscrição já foi paga/reembolsada ou a partida começou.
        """
        if not self.pode_cancelar:
            raise ValidationError(
                "Só é possível cancelar inscrições com pagamento pendente, "
                "antes do início da partida. Fale com a arena para reembolsos.",
                code="cancelamento_negado",
            )
        self.delete()

    def clean(self) -> None:
        """Impede a troca de partida ou jogador e valida a vaga em novas ocupações."""
        super().clean()
        anterior = self._estado_anterior()
        if anterior is not None and (
            anterior["open_match_id"] != self.open_match_id
            or anterior["player_id"] != self.player_id
        ):
            raise ValidationError(
                "Não é possível trocar a partida ou o jogador de uma inscrição. "
                "Reembolse esta inscrição e crie outra.",
                code="inscricao_imutavel",
            )
        ocupava_vaga = (
            anterior is not None and anterior["status_pagamento"] in STATUS_OCUPA_VAGA
        )
        if self.ocupa_vaga and not ocupava_vaga:
            self._validar_nova_ocupacao()

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Valida e salva com a partida bloqueada e depois recalcula as vagas.

        A partida é recarregada com ``select_for_update()`` (bloqueio de linha no
        PostgreSQL) para serializar inscrições concorrentes na última vaga.
        Na criação, os valores da vaga são copiados da partida.
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
                    self.valor_vaga = self.open_match.preco_vaga_base
                    self.valor_taxa = self.open_match.valor_taxa_vaga
            super().save(*args, **kwargs)
            self.open_match.atualizar_vagas()

    def _estado_anterior(self) -> dict[str, Any] | None:
        """Lê do banco os valores já salvos (``None`` para inscrições novas)."""
        if self._state.adding:
            return None
        return (
            Booking.objects.filter(pk=self.pk)
            .values("open_match_id", "player_id", "status_pagamento")
            .first()
        )

    def _validar_nova_ocupacao(self) -> None:
        """Valida uma inscrição nova ou reativada: partida aberta, não iniciada e com vaga."""
        try:
            partida = self.open_match
        except ObjectDoesNotExist:
            return  # FK ausente ou inválida: o erro já foi reportado por clean_fields().
        if partida.status == StatusPartida.LOTADA:
            raise ValidationError("Esta partida está lotada.", code="partida_lotada")
        if partida.status != StatusPartida.ABERTA:
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
            Booking.objects.filter(
                open_match_id=partida.pk, status_pagamento__in=STATUS_OCUPA_VAGA
            )
            .exclude(pk=self.pk)
            .count()
        )
        if ocupadas >= partida.vagas_totais:
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
