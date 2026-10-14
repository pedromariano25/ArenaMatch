"""Back-office da plataforma (Django Admin customizado).

O dia a dia dos gestores acontece no Portal do Gestor (``/manager/``); o admin é a
ferramenta interna da equipe do ArenaMatch. Mesmo assim, gestores com acesso ao
admin enxergam apenas os dados das próprias arenas. Inscrições, pagamentos e o
razão contábil são somente leitura: o dinheiro só se move pelos serviços de
checkout e de partidas, que mantêm o razão consistente.
"""

from datetime import timedelta
from typing import Any

from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Q, QuerySet
from django.forms import Field
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import format_html
from django.utils.safestring import SafeString

from . import gestao, razao
from . import partidas as servico_partidas
from .formatacao import formatar_brl, formatar_cnpj, formatar_cpf
from .forms import ConverterPartidaForm
from .models import (
    STATUS_HORARIO_LIVRE,
    Arena,
    AvaliacaoPartida,
    Booking,
    Court,
    CustomUser,
    Elogio,
    LedgerAccount,
    LedgerEntry,
    MotivoCancelamento,
    OpenMatch,
    Payment,
    Payout,
    PlayerProfile,
    SinalNivel,
    StatusHorario,
    StatusInscricao,
    StatusPagamento,
    StatusPartida,
    StatusRepasse,
    TimeSlot,
    WaitlistEntry,
)

admin.site.site_header = "ArenaMatch · Back-office"
admin.site.site_title = "ArenaMatch Back-office"
admin.site.index_title = "Administração da plataforma"
# Página inicial com indicadores (partidas, ocupação, receita e horários ociosos).
admin.site.index_template = "admin/arena_index.html"


# --- Apresentação ------------------------------------------------------------

# (fundo, texto) dos selos de status; legíveis nos temas claro e escuro do admin.
_CORES = {
    "verde": ("#dcfce7", "#166534"),
    "ambar": ("#fef3c7", "#92400e"),
    "azul": ("#dbeafe", "#1e40af"),
    "vermelho": ("#fee2e2", "#991b1b"),
    "cinza": ("#e5e7eb", "#374151"),
}
_COR_POR_STATUS = {
    StatusHorario.CONFIRMADO: "verde",
    StatusHorario.OCIOSO: "ambar",
    StatusHorario.CANCELADO: "cinza",
    StatusPartida.ABERTA: "verde",
    StatusPartida.LOTADA: "azul",
    StatusPartida.FINALIZADA: "cinza",
    StatusPartida.CANCELADA: "vermelho",
    StatusInscricao.CONFIRMADA: "verde",
    StatusInscricao.AGUARDANDO_PAGAMENTO: "ambar",
    StatusInscricao.EXPIRADA: "cinza",
    StatusInscricao.CANCELADA: "cinza",
    StatusInscricao.REEMBOLSADA: "azul",
    StatusPagamento.APROVADO: "verde",
    StatusPagamento.PENDENTE: "ambar",
    StatusPagamento.RECUSADO: "vermelho",
    StatusPagamento.EXPIRADO: "cinza",
    StatusPagamento.CANCELADO: "cinza",
    StatusPagamento.ESTORNADO: "azul",
    StatusRepasse.FALHOU: "vermelho",
}


def _selo(valor: str, rotulo: str) -> SafeString:
    """Renderiza um selo colorido para o status ``valor``."""
    fundo, texto = _CORES[_COR_POR_STATUS.get(valor, "cinza")]
    return format_html(
        '<span style="background:{};color:{};padding:2px 10px;border-radius:999px;'
        'font-size:11px;font-weight:600;white-space:nowrap">{}</span>',
        fundo,
        texto,
        rotulo,
    )


def _barra_ocupacao(partida: OpenMatch) -> SafeString:
    """Barra de progresso com as vagas preenchidas da partida."""
    cor = "#2563eb" if partida.vagas_disponiveis == 0 else "#10b981"
    return format_html(
        '<div style="min-width:140px"><div style="font-size:11px;margin-bottom:3px">'
        "{} de {} vagas preenchidas</div>"
        '<div style="height:6px;background:#e5e7eb;border-radius:999px;overflow:hidden">'
        '<div style="height:6px;width:{}%;background:{}"></div></div></div>',
        partida.vagas_ocupadas,
        partida.vagas_totais,
        partida.percentual_ocupado,
        cor,
    )


def _motivo_inelegivel(horario: TimeSlot) -> str | None:
    """Explica por que um horário não pode virar partida (``None`` se puder)."""
    if horario.status not in STATUS_HORARIO_LIVRE:
        return f"está {horario.get_status_display()} (precisa estar Ocioso ou Cancelado)"
    if hasattr(horario, "partida_aberta"):
        return "já tem partida aberta"
    if horario.ja_comecou:
        return "o horário já começou"
    return None


# --- Filtros -----------------------------------------------------------------


class PeriodoFilter(admin.SimpleListFilter):
    """Filtro de período voltado à agenda: hoje, amanhã, próximos dias e passados."""

    title = "período"
    parameter_name = "periodo"
    campo_data = "data"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> list[tuple[str, str]]:
        return [
            ("hoje", "Hoje"),
            ("amanha", "Amanhã"),
            ("proximos_7", "Próximos 7 dias"),
            ("futuros", "De hoje em diante"),
            ("passados", "Passados"),
        ]

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        hoje = timezone.localdate()
        campo = self.campo_data
        filtros = {
            "hoje": {campo: hoje},
            "amanha": {campo: hoje + timedelta(days=1)},
            "proximos_7": {f"{campo}__range": (hoje, hoje + timedelta(days=6))},
            "futuros": {f"{campo}__gte": hoje},
            "passados": {f"{campo}__lt": hoje},
        }
        filtro = filtros.get(self.value() or "")
        return queryset.filter(**filtro) if filtro else queryset


class PeriodoPartidaFilter(PeriodoFilter):
    """Filtro de período aplicado à data do horário da partida."""

    campo_data = "time_slot__data"


# --- Escopo multi-tenant -----------------------------------------------------

# Caminho, a partir de cada modelo, até o gestor responsável pela arena.
_CAMINHO_GESTOR: dict[type[models.Model], str] = {
    Arena: "manager",
    Court: "arena__manager",
    TimeSlot: "court__arena__manager",
    OpenMatch: "time_slot__court__arena__manager",
    Booking: "open_match__time_slot__court__arena__manager",
    WaitlistEntry: "partida__time_slot__court__arena__manager",
    Payment: "booking__open_match__time_slot__court__arena__manager",
    LedgerAccount: "arena__manager",
    LedgerEntry: "conta__arena__manager",
    Payout: "arena__manager",
}


def _restringir_ao_gestor(queryset: QuerySet, request: HttpRequest) -> QuerySet:
    """Superusuários veem tudo; os demais, só os dados das próprias arenas."""
    if request.user.is_superuser:
        return queryset
    return queryset.filter(**{_CAMINHO_GESTOR[queryset.model]: request.user})


class EscopoGestorAdmin(admin.ModelAdmin):
    """Aplica o escopo do gestor à listagem e às opções das chaves estrangeiras."""

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return _restringir_ao_gestor(super().get_queryset(request), request)

    def formfield_for_foreignkey(
        self, db_field: models.ForeignKey, request: HttpRequest, **kwargs: Any
    ) -> Field | None:
        modelo = db_field.related_model
        if modelo in _CAMINHO_GESTOR and "queryset" not in kwargs:
            kwargs["queryset"] = _restringir_ao_gestor(modelo._default_manager.all(), request)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class SomenteLeituraAdmin(EscopoGestorAdmin):
    """Registros que só os serviços alteram (dinheiro e inscrições): consulta apenas."""

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


# --- Usuários ----------------------------------------------------------------


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """Usuários da plataforma (gestores não recebem permissão sobre este modelo)."""

    list_display = (
        "username",
        "nome",
        "email",
        "telefone",
        "cpf_formatado",
        "is_manager",
        "is_player",
        "is_staff",
    )
    list_filter = ("is_manager", "is_player", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "first_name", "last_name", "email", "cpf", "telefone")
    ordering = ("username",)
    fieldsets = (
        *UserAdmin.fieldsets,
        ("ArenaMatch", {"fields": ("is_manager", "is_player", "telefone", "cpf")}),
    )
    add_fieldsets = (
        *UserAdmin.add_fieldsets,
        (
            "ArenaMatch",
            {"fields": ("first_name", "last_name", "email", "is_manager", "is_player", "telefone", "cpf")},
        ),
    )

    @admin.display(description="nome", ordering="first_name")
    def nome(self, obj: CustomUser) -> str:
        return obj.get_full_name() or "—"

    @admin.display(description="CPF")
    def cpf_formatado(self, obj: CustomUser) -> str:
        return formatar_cpf(obj.cpf) or "—"


# --- Arenas e quadras --------------------------------------------------------


class CourtInline(admin.TabularInline):
    """Quadras editadas diretamente na página da arena."""

    model = Court
    extra = 0
    fields = ("nome_ou_numero", "tipo_piso", "capacidade_padrao")
    show_change_link = True


@admin.register(Arena)
class ArenaAdmin(EscopoGestorAdmin):
    """Complexos esportivos. O gestor edita a própria arena, mas não troca o responsável."""

    list_display = (
        "nome",
        "manager",
        "cnpj_formatado",
        "telefone_contato",
        "funcionamento",
        "total_quadras",
    )
    search_fields = ("nome", "cnpj", "endereco_completo")
    prepopulated_fields = {"slug": ("nome",)}
    inlines = (CourtInline,)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("nome", "slug", "manager")}),
        ("Contato e endereço", {"fields": ("cnpj", "telefone_contato", "endereco_completo")}),
        ("Funcionamento", {"fields": (("hora_abertura", "hora_fechamento"),)}),
        (
            "Contrato e regras das partidas",
            {
                "fields": (
                    ("taxa_plataforma_percentual", "taxa_minima"),
                    ("quorum_percentual", "horas_prazo_quorum"),
                )
            },
        ),
        ("Registro", {"classes": ("collapse",), "fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return (
            super()
            .get_queryset(request)
            .select_related("manager")
            .annotate(_total_quadras=Count("quadras"))
        )

    def get_list_filter(self, request: HttpRequest) -> tuple[str, ...]:
        return ("manager",) if request.user.is_superuser else ()

    def get_readonly_fields(self, request: HttpRequest, obj: Arena | None = None) -> tuple[str, ...]:
        campos = tuple(super().get_readonly_fields(request, obj))
        if request.user.is_superuser:
            return campos
        # O responsável e o contrato (taxas) só mudam pela equipe da plataforma.
        return (*campos, "manager", "taxa_plataforma_percentual", "taxa_minima")

    def save_model(self, request: HttpRequest, obj: Arena, form: Any, change: bool) -> None:
        if not change and not request.user.is_superuser:
            obj.manager = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="CNPJ", ordering="cnpj")
    def cnpj_formatado(self, obj: Arena) -> str:
        return formatar_cnpj(obj.cnpj)

    @admin.display(description="funcionamento")
    def funcionamento(self, obj: Arena) -> str:
        return f"{obj.hora_abertura:%H:%M}–{obj.hora_fechamento:%H:%M}"

    @admin.display(description="quadras", ordering="_total_quadras")
    def total_quadras(self, obj: Arena) -> int:
        return obj._total_quadras


@admin.register(Court)
class CourtAdmin(EscopoGestorAdmin):
    """Quadras, com a contagem de horários futuros na agenda."""

    list_display = ("nome_ou_numero", "arena", "tipo_piso", "capacidade_padrao", "horarios_futuros")
    list_filter = ("tipo_piso", ("arena", admin.RelatedOnlyFieldListFilter))
    search_fields = ("nome_ou_numero", "arena__nome")
    list_select_related = ("arena",)

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        futuros = Q(horarios__data__gte=timezone.localdate())
        return super().get_queryset(request).annotate(
            _horarios_futuros=Count("horarios", filter=futuros)
        )

    @admin.display(description="horários futuros", ordering="_horarios_futuros")
    def horarios_futuros(self, obj: Court) -> int:
        return obj._horarios_futuros


# --- Agenda ------------------------------------------------------------------


@admin.register(TimeSlot)
class TimeSlotAdmin(EscopoGestorAdmin):
    """Agenda das quadras, com a action que transforma horários ociosos em partidas."""

    list_display = (
        "dia",
        "horario",
        "quadra",
        "arena",
        "tipo_reserva",
        "status_selo",
        "partida",
    )
    list_display_links = ("dia", "horario")
    list_filter = (
        PeriodoFilter,
        "status",
        "tipo_reserva",
        ("court__arena", admin.RelatedOnlyFieldListFilter),
        ("court", admin.RelatedOnlyFieldListFilter),
    )
    date_hierarchy = "data"
    search_fields = ("court__nome_ou_numero", "court__arena__nome")
    list_select_related = ("court__arena", "partida_aberta")
    ordering = ("data", "hora_inicio")
    list_per_page = 50
    actions = ("converter_para_partida_aberta", "marcar_como_ocioso")
    fieldsets = (
        (None, {"fields": ("court", "data", ("hora_inicio", "hora_fim"))}),
        ("Reserva", {"fields": ("tipo_reserva", "status")}),
    )

    @admin.display(description="data", ordering="data")
    def dia(self, obj: TimeSlot) -> str:
        return date_format(obj.data, "D, d/m/Y")

    @admin.display(description="horário", ordering="hora_inicio")
    def horario(self, obj: TimeSlot) -> str:
        return obj.intervalo

    @admin.display(description="quadra", ordering="court__nome_ou_numero")
    def quadra(self, obj: TimeSlot) -> str:
        return obj.court.nome_ou_numero

    @admin.display(description="arena", ordering="court__arena__nome")
    def arena(self, obj: TimeSlot) -> Arena:
        return obj.court.arena

    @admin.display(description="status", ordering="status")
    def status_selo(self, obj: TimeSlot) -> SafeString:
        return _selo(obj.status, obj.get_status_display())

    @admin.display(description="partida aberta")
    def partida(self, obj: TimeSlot) -> SafeString | str:
        try:
            partida = obj.partida_aberta
        except OpenMatch.DoesNotExist:
            return "—"
        return format_html(
            '<a href="{}">{} · {}/{} vagas</a>',
            reverse("admin:arena_openmatch_change", args=[partida.pk]),
            partida.get_status_display(),
            partida.vagas_ocupadas,
            partida.vagas_totais,
        )

    def has_converter_permission(self, request: HttpRequest) -> bool:
        """A conversão cria partidas: exige permissão para adicionar partidas abertas."""
        return request.user.has_perm("arena.add_openmatch")

    @admin.action(description="Converter em partida aberta", permissions=["converter"])
    def converter_para_partida_aberta(
        self, request: HttpRequest, queryset: QuerySet
    ) -> HttpResponse | None:
        """Mostra uma tela intermediária (preço, nível, vagas) e cria as partidas."""
        horarios = queryset.select_related("court__arena", "partida_aberta").order_by(
            "data", "hora_inicio"
        )
        elegiveis: list[TimeSlot] = []
        inelegiveis: list[tuple[TimeSlot, str]] = []
        for horario in horarios:
            motivo = _motivo_inelegivel(horario)
            if motivo:
                inelegiveis.append((horario, motivo))
            else:
                elegiveis.append(horario)

        form = ConverterPartidaForm(request.POST if "aplicar" in request.POST else None)
        if form.is_bound and form.is_valid():
            self._criar_partidas(request, elegiveis, inelegiveis, form.cleaned_data)
            return None

        contexto = {
            **self.admin_site.each_context(request),
            "title": "Converter horários em partidas abertas",
            "opts": self.model._meta,
            "form": form,
            "horarios": horarios,
            "elegiveis": elegiveis,
            "inelegiveis": inelegiveis,
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(
            request, "admin/arena/timeslot/converter_partida_aberta.html", contexto
        )

    def _criar_partidas(
        self,
        request: HttpRequest,
        elegiveis: list[TimeSlot],
        inelegiveis: list[tuple[TimeSlot, str]],
        dados: dict[str, Any],
    ) -> None:
        """Cria uma partida por horário elegível e informa o resultado ao gestor."""
        criadas = 0
        ignorados = list(inelegiveis)
        for horario in elegiveis:
            vagas = dados["vagas_totais"] or horario.court.capacidade_padrao
            goleiros = dados["vagas_goleiro"]
            try:
                OpenMatch.objects.create(
                    time_slot=horario,
                    vagas_totais=vagas,
                    vagas_goleiro=gestao.vagas_goleiro_sugeridas(vagas) if goleiros is None else goleiros,
                    valor_total_aluguel=dados["valor_total_aluguel"],
                    nivel_competitividade=dados["nivel_competitividade"],
                )
                criadas += 1
            except ValidationError as erro:
                ignorados.append((horario, " ".join(erro.messages)))
        if criadas:
            self.message_user(
                request,
                f"{criadas} partida(s) aberta(s) criada(s) e publicada(s) na vitrine.",
                messages.SUCCESS,
            )
        if ignorados:
            detalhes = "; ".join(
                f"{h.data:%d/%m} {h.intervalo} ({h.court.nome_ou_numero}): {motivo}"
                for h, motivo in ignorados
            )
            self.message_user(
                request, f"{len(ignorados)} horário(s) ignorado(s) — {detalhes}", messages.WARNING
            )

    @admin.action(description="Marcar como ocioso (liberar para partidas)", permissions=["change"])
    def marcar_como_ocioso(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Libera os horários selecionados para que possam virar partidas abertas."""
        alterados = 0
        for horario in queryset:
            if horario.status == StatusHorario.OCIOSO:
                continue
            horario.status = StatusHorario.OCIOSO
            try:
                horario.save()
                alterados += 1
            except ValidationError as erro:
                self.message_user(request, f"{horario}: {' '.join(erro.messages)}", messages.ERROR)
        if alterados:
            self.message_user(request, f"{alterados} horário(s) marcado(s) como ocioso.", messages.SUCCESS)


# --- Partidas e inscrições ---------------------------------------------------


class BookingInline(admin.TabularInline):
    """Inscrições da partida (somente leitura: elas mudam pelo checkout)."""

    model = Booking
    extra = 0
    fields = ("player", "posicao", "status", "metodo_pagamento", "valor_pago", "data_inscricao")
    readonly_fields = fields
    show_change_link = True
    can_delete = False

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    @admin.display(description="valor pago")
    def valor_pago(self, obj: Booking) -> str:
        return formatar_brl(obj.valor_total)


@admin.register(OpenMatch)
class OpenMatchAdmin(EscopoGestorAdmin):
    """Partidas abertas, com ocupação em tempo real e as inscrições em linha."""

    list_display = (
        "partida",
        "arena",
        "nivel_competitividade",
        "ocupacao",
        "preco",
        "status_selo",
    )
    list_filter = (
        PeriodoPartidaFilter,
        "status",
        "nivel_competitividade",
        ("time_slot__court__arena", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("time_slot__court__nome_ou_numero", "time_slot__court__arena__nome")
    list_select_related = ("time_slot__court__arena",)
    ordering = ("time_slot__data", "time_slot__hora_inicio")
    readonly_fields = (
        "status",
        "vagas_disponiveis",
        "ocupacao",
        "motivo_cancelamento",
        "cancelada_em",
        "quorum_conferido_em",
        "created_at",
        "updated_at",
    )
    inlines = (BookingInline,)
    actions = ("cancelar_partidas",)
    formfield_overrides = {models.DecimalField: {"localize": True}}
    fieldsets = (
        (None, {"fields": ("time_slot", "status", "nivel_competitividade")}),
        (
            "Vagas e preço",
            {
                "fields": (
                    ("vagas_totais", "vagas_goleiro", "vagas_disponiveis"),
                    "ocupacao",
                    "valor_total_aluguel",
                    ("taxa_plataforma_percentual", "taxa_minima"),
                )
            },
        ),
        (
            "Mínimo de jogadores",
            {"fields": (("quorum_percentual", "horas_prazo_quorum"), "quorum_conferido_em")},
        ),
        (
            "Registro",
            {
                "classes": ("collapse",),
                "fields": ("motivo_cancelamento", "cancelada_em", "created_at", "updated_at"),
            },
        ),
    )

    def get_readonly_fields(self, request: HttpRequest, obj: OpenMatch | None = None) -> tuple[str, ...]:
        campos = tuple(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            campos = (*campos, "taxa_plataforma_percentual", "taxa_minima")
        # Com inscrições vinculadas, a partida não muda de horário.
        return (*campos, "time_slot") if obj else campos

    def formfield_for_foreignkey(
        self, db_field: models.ForeignKey, request: HttpRequest, **kwargs: Any
    ) -> Field | None:
        campo = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "time_slot" and campo is not None:
            # Só horários livres, futuros e ainda sem partida.
            campo.queryset = (
                campo.queryset.filter(
                    status__in=STATUS_HORARIO_LIVRE,
                    partida_aberta__isnull=True,
                    data__gte=timezone.localdate(),
                )
                .select_related("court__arena")
                .order_by("data", "hora_inicio")
            )
        return campo

    @admin.display(description="partida", ordering="time_slot__data")
    def partida(self, obj: OpenMatch) -> str:
        horario = obj.time_slot
        return f"{horario.data:%d/%m/%Y} · {horario.intervalo} · {horario.court.nome_ou_numero}"

    @admin.display(description="arena", ordering="time_slot__court__arena__nome")
    def arena(self, obj: OpenMatch) -> Arena:
        return obj.time_slot.court.arena

    @admin.display(description="ocupação", ordering="vagas_disponiveis")
    def ocupacao(self, obj: OpenMatch) -> SafeString | str:
        if obj is None or obj.vagas_totais is None:
            return "—"
        return _barra_ocupacao(obj)

    @admin.display(description="preço/jogador", ordering="valor_total_aluguel")
    def preco(self, obj: OpenMatch) -> str:
        return formatar_brl(obj.preco_final_jogador)

    @admin.display(description="status", ordering="status")
    def status_selo(self, obj: OpenMatch) -> SafeString:
        return _selo(obj.status, obj.get_status_display())

    @admin.action(description="Cancelar partidas (reembolsa todos os inscritos)", permissions=["change"])
    def cancelar_partidas(self, request: HttpRequest, queryset: QuerySet) -> None:
        canceladas = reembolsados = 0
        for partida in queryset:
            try:
                reembolsados += servico_partidas.cancelar_partida(partida, MotivoCancelamento.ARENA)
                canceladas += 1
            except ValidationError as erro:
                self.message_user(request, f"{partida}: {' '.join(erro.messages)}", messages.ERROR)
        if canceladas:
            self.message_user(
                request,
                f"{canceladas} partida(s) cancelada(s); {reembolsados} jogador(es) reembolsado(s).",
                messages.SUCCESS,
            )


@admin.register(Booking)
class BookingAdmin(SomenteLeituraAdmin):
    """Inscrições de jogadores (somente leitura: mudam pelo checkout e pelos cancelamentos)."""

    list_display = (
        "player",
        "partida",
        "arena",
        "posicao",
        "status_selo",
        "valor",
        "data_inscricao",
    )
    list_filter = (
        "status",
        "posicao",
        "metodo_pagamento",
        ("open_match__time_slot__court__arena", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        "player__username",
        "player__first_name",
        "player__last_name",
        "player__cpf",
        "open_match__time_slot__court__arena__nome",
    )
    list_select_related = ("player", "open_match__time_slot__court__arena")
    date_hierarchy = "data_inscricao"
    fields = (
        "open_match",
        "player",
        "posicao",
        "status",
        "metodo_pagamento",
        ("valor_vaga", "valor_taxa", "valor_acrescimo"),
        "data_inscricao",
        "reservada_ate",
        "confirmada_em",
        "cancelada_em",
        "repasse_solicitado_em",
    )

    @admin.display(description="partida", ordering="open_match__time_slot__data")
    def partida(self, obj: Booking) -> str:
        horario = obj.open_match.time_slot
        return f"{horario.data:%d/%m/%Y} · {horario.intervalo} · {horario.court.nome_ou_numero}"

    @admin.display(description="arena", ordering="open_match__time_slot__court__arena__nome")
    def arena(self, obj: Booking) -> Arena:
        return obj.open_match.time_slot.court.arena

    @admin.display(description="status", ordering="status")
    def status_selo(self, obj: Booking) -> SafeString:
        return _selo(obj.status, obj.get_status_display())

    @admin.display(description="valor", ordering="valor_vaga")
    def valor(self, obj: Booking) -> str:
        return formatar_brl(obj.valor_total)


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(EscopoGestorAdmin):
    """Lista de espera das partidas."""

    list_display = ("jogador", "partida", "posicao", "created_at", "notificado_em")
    list_select_related = ("jogador", "partida__time_slot__court")
    search_fields = ("jogador__username", "jogador__first_name", "jogador__last_name")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


# --- Pagamentos e razão ------------------------------------------------------


def _data_hora(valor: Any) -> str:
    return date_format(timezone.localtime(valor), "d/m/Y H:i") if valor else "—"


@admin.register(Payment)
class PaymentAdmin(SomenteLeituraAdmin):
    """Cobranças das inscrições (gateway ou crédito)."""

    list_display = ("criado", "jogador", "metodo", "valor_formatado", "tarifa", "status_selo", "gateway")
    list_filter = ("status", "metodo", "gateway")
    search_fields = ("gateway_id", "booking__player__username", "booking__player__first_name")
    list_select_related = ("booking__player",)
    date_hierarchy = "created_at"
    fields = (
        "booking",
        "metodo",
        "status",
        "valor",
        "tarifa_gateway",
        "gateway",
        "gateway_id",
        "pix_copia_e_cola",
        "expira_em",
        "aprovado_em",
        "estornado_em",
        "resposta_gateway",
        "created_at",
    )

    @admin.display(description="criado em", ordering="created_at")
    def criado(self, obj: Payment) -> str:
        return _data_hora(obj.created_at)

    @admin.display(description="jogador", ordering="booking__player__first_name")
    def jogador(self, obj: Payment) -> CustomUser:
        return obj.booking.player

    @admin.display(description="valor", ordering="valor")
    def valor_formatado(self, obj: Payment) -> str:
        return formatar_brl(obj.valor)

    @admin.display(description="tarifa", ordering="tarifa_gateway")
    def tarifa(self, obj: Payment) -> str:
        return formatar_brl(obj.tarifa_gateway)

    @admin.display(description="status", ordering="status")
    def status_selo(self, obj: Payment) -> SafeString:
        return _selo(obj.status, obj.get_status_display())


@admin.register(LedgerAccount)
class LedgerAccountAdmin(SomenteLeituraAdmin):
    """Carteiras do razão, com o saldo (soma dos lançamentos)."""

    list_display = ("__str__", "tipo", "saldo")
    list_filter = ("tipo",)
    search_fields = ("arena__nome", "jogador__username", "jogador__first_name")
    list_select_related = ("arena", "jogador")

    @admin.display(description="saldo")
    def saldo(self, obj: LedgerAccount) -> str:
        return formatar_brl(razao.saldo(obj.lancamentos.all()))


@admin.register(LedgerEntry)
class LedgerEntryAdmin(SomenteLeituraAdmin):
    """Lançamentos imutáveis do razão contábil."""

    list_display = ("criado", "conta", "tipo", "valor_formatado", "descricao", "disponivel")
    list_filter = ("tipo", "conta__tipo")
    search_fields = ("descricao", "conta__arena__nome", "conta__jogador__username")
    list_select_related = ("conta__arena", "conta__jogador")
    date_hierarchy = "created_at"

    @admin.display(description="criado em", ordering="created_at")
    def criado(self, obj: LedgerEntry) -> str:
        return _data_hora(obj.created_at)

    @admin.display(description="valor", ordering="valor")
    def valor_formatado(self, obj: LedgerEntry) -> str:
        return formatar_brl(obj.valor)

    @admin.display(description="disponível em", ordering="disponivel_em")
    def disponivel(self, obj: LedgerEntry) -> str:
        return _data_hora(obj.disponivel_em)


@admin.register(Payout)
class PayoutAdmin(SomenteLeituraAdmin):
    """Repasses às arenas."""

    list_display = ("criado", "arena", "valor_formatado", "status", "referencia")
    list_filter = ("status", ("arena", admin.RelatedOnlyFieldListFilter))
    list_select_related = ("arena",)
    date_hierarchy = "created_at"

    @admin.display(description="criado em", ordering="created_at")
    def criado(self, obj: Payout) -> str:
        return _data_hora(obj.created_at)

    @admin.display(description="valor", ordering="valor")
    def valor_formatado(self, obj: Payout) -> str:
        return formatar_brl(obj.valor)


# --- Jogadores ----------------------------------------------------------------


@admin.register(PlayerProfile)
class PlayerProfileAdmin(admin.ModelAdmin):
    """Perfis de jogadores (nível, posição). A equipe pode corrigir o nível manualmente."""

    list_display = ("jogador", "nivel", "nivel_origem", "posicao", "joga_no_gol", "regiao", "goleiro_suspenso_ate")
    list_filter = ("nivel", "nivel_origem", "posicao", "joga_no_gol")
    search_fields = ("jogador__username", "jogador__first_name", "jogador__last_name", "apelido")
    list_select_related = ("jogador",)
    readonly_fields = ("nivel_ajustado_em", "created_at", "updated_at")


class _RegistroDeAvaliacaoAdmin(admin.ModelAdmin):
    """Avaliações vêm dos jogadores: a equipe só consulta (e remove abusos)."""

    list_select_related = ("autor", "partida__time_slot__court")
    date_hierarchy = "created_at"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(AvaliacaoPartida)
class AvaliacaoPartidaAdmin(_RegistroDeAvaliacaoAdmin):
    list_display = ("autor", "partida", "percepcao", "created_at")
    list_filter = ("percepcao",)


@admin.register(Elogio)
class ElogioAdmin(_RegistroDeAvaliacaoAdmin):
    list_display = ("autor", "alvo", "tipo", "partida", "created_at")
    list_filter = ("tipo",)
    list_select_related = ("autor", "alvo", "partida__time_slot__court")


@admin.register(SinalNivel)
class SinalNivelAdmin(_RegistroDeAvaliacaoAdmin):
    list_display = ("autor", "alvo", "direcao", "partida", "created_at")
    list_filter = ("direcao",)
    list_select_related = ("autor", "alvo", "partida__time_slot__court")
