"""Painel de gestão B2B: Django Admin customizado para os gestores de arenas.

Gestores (``is_manager`` sem superusuário) enxergam e editam apenas os dados das
próprias arenas; superusuários enxergam tudo. Alterações de status passam sempre
por ``save()``, para que as regras de negócio e o recálculo de vagas sejam aplicados.
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

from .formatacao import formatar_brl, formatar_cnpj, formatar_cpf
from .forms import ConverterPartidaForm
from .models import (
    STATUS_HORARIO_LIVRE,
    Arena,
    Booking,
    Court,
    CustomUser,
    OpenMatch,
    StatusHorario,
    StatusPagamento,
    StatusPartida,
    TimeSlot,
)

admin.site.site_header = "ArenaMatch · Painel do Gestor"
admin.site.site_title = "ArenaMatch"
admin.site.index_title = "Gestão de arenas, agenda e partidas"
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
    StatusPagamento.PAGO: "verde",
    StatusPagamento.PENDENTE: "ambar",
    StatusPagamento.REEMBOLSADO: "cinza",
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
        return campos if request.user.is_superuser else (*campos, "manager")

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
            try:
                OpenMatch.objects.create(
                    time_slot=horario,
                    vagas_totais=dados["vagas_totais"] or horario.court.capacidade_padrao,
                    preco_por_vaga=dados["preco_por_vaga"],
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
    """Inscrições exibidas e registradas (ex.: jogador avulso no balcão) na partida."""

    model = Booking
    extra = 0
    fields = ("player", "status_pagamento", "data_inscricao")
    show_change_link = True


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
    readonly_fields = ("vagas_disponiveis", "ocupacao", "created_at", "updated_at")
    inlines = (BookingInline,)
    actions = ("finalizar_partidas", "cancelar_partidas")
    formfield_overrides = {models.DecimalField: {"localize": True}}
    fieldsets = (
        (None, {"fields": ("time_slot", "status")}),
        (
            "Vagas e preço",
            {
                "fields": (
                    ("vagas_totais", "vagas_disponiveis"),
                    "ocupacao",
                    ("preco_por_vaga", "nivel_competitividade"),
                )
            },
        ),
        ("Registro", {"classes": ("collapse",), "fields": ("created_at", "updated_at")}),
    )

    def get_readonly_fields(self, request: HttpRequest, obj: OpenMatch | None = None) -> tuple[str, ...]:
        campos = tuple(super().get_readonly_fields(request, obj))
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

    @admin.display(description="preço/vaga", ordering="preco_por_vaga")
    def preco(self, obj: OpenMatch) -> str:
        return formatar_brl(obj.preco_por_vaga)

    @admin.display(description="status", ordering="status")
    def status_selo(self, obj: OpenMatch) -> SafeString:
        return _selo(obj.status, obj.get_status_display())

    @admin.action(description="Finalizar partidas selecionadas", permissions=["change"])
    def finalizar_partidas(self, request: HttpRequest, queryset: QuerySet) -> None:
        self._mudar_status(request, queryset, StatusPartida.FINALIZADA)

    @admin.action(description="Cancelar partidas selecionadas", permissions=["change"])
    def cancelar_partidas(self, request: HttpRequest, queryset: QuerySet) -> None:
        self._mudar_status(request, queryset, StatusPartida.CANCELADA)
        if Booking.objects.filter(
            open_match__in=queryset, status_pagamento=StatusPagamento.PAGO
        ).exists():
            self.message_user(
                request,
                "Há inscrições pagas nas partidas canceladas: registre os reembolsos em Inscrições.",
                messages.WARNING,
            )

    def _mudar_status(self, request: HttpRequest, queryset: QuerySet, status: str) -> None:
        """Altera o status partida a partida, via ``save()``, informando falhas."""
        alteradas = 0
        for partida in queryset:
            if partida.status == status:
                continue
            partida.status = status
            try:
                partida.save()
                alteradas += 1
            except ValidationError as erro:
                self.message_user(request, f"{partida}: {' '.join(erro.messages)}", messages.ERROR)
        if alteradas:
            self.message_user(
                request,
                f"{alteradas} partida(s) marcada(s) como {StatusPartida(status).label}.",
                messages.SUCCESS,
            )


@admin.register(Booking)
class BookingAdmin(EscopoGestorAdmin):
    """Inscrições de jogadores, com controle manual de pagamento (MVP)."""

    list_display = (
        "player",
        "partida",
        "arena",
        "status_pagamento_selo",
        "valor",
        "data_inscricao",
    )
    list_filter = (
        "status_pagamento",
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
    actions = ("marcar_como_pago", "marcar_como_reembolsado")
    fields = ("open_match", "player", "status_pagamento", "data_inscricao")

    def get_readonly_fields(self, request: HttpRequest, obj: Booking | None = None) -> tuple[str, ...]:
        # Partida e jogador não mudam depois da inscrição (regra do modelo).
        return ("open_match", "player") if obj else ()

    def formfield_for_foreignkey(
        self, db_field: models.ForeignKey, request: HttpRequest, **kwargs: Any
    ) -> Field | None:
        campo = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "open_match" and campo is not None:
            campo.queryset = (
                campo.queryset.filter(status=StatusPartida.ABERTA).futuras().com_relacionados()
            )
        return campo

    @admin.display(description="partida", ordering="open_match__time_slot__data")
    def partida(self, obj: Booking) -> str:
        horario = obj.open_match.time_slot
        return f"{horario.data:%d/%m/%Y} · {horario.intervalo} · {horario.court.nome_ou_numero}"

    @admin.display(description="arena", ordering="open_match__time_slot__court__arena__nome")
    def arena(self, obj: Booking) -> Arena:
        return obj.open_match.time_slot.court.arena

    @admin.display(description="pagamento", ordering="status_pagamento")
    def status_pagamento_selo(self, obj: Booking) -> SafeString:
        return _selo(obj.status_pagamento, obj.get_status_pagamento_display())

    @admin.display(description="valor", ordering="open_match__preco_por_vaga")
    def valor(self, obj: Booking) -> str:
        return formatar_brl(obj.open_match.preco_por_vaga)

    @admin.action(description="Marcar como pago", permissions=["change"])
    def marcar_como_pago(self, request: HttpRequest, queryset: QuerySet) -> None:
        self._mudar_pagamento(request, queryset, StatusPagamento.PAGO)

    @admin.action(description="Marcar como reembolsado (libera a vaga)", permissions=["change"])
    def marcar_como_reembolsado(self, request: HttpRequest, queryset: QuerySet) -> None:
        self._mudar_pagamento(request, queryset, StatusPagamento.REEMBOLSADO)

    def _mudar_pagamento(self, request: HttpRequest, queryset: QuerySet, status: str) -> None:
        """Altera via ``save()`` (e não ``QuerySet.update()``) para recalcular as vagas."""
        alteradas = 0
        for inscricao in queryset.select_related("open_match"):
            if inscricao.status_pagamento == status:
                continue
            inscricao.status_pagamento = status
            try:
                inscricao.save()
                alteradas += 1
            except ValidationError as erro:
                self.message_user(request, f"{inscricao}: {' '.join(erro.messages)}", messages.ERROR)
        if alteradas:
            self.message_user(
                request,
                f"{alteradas} inscrição(ões) marcada(s) como {StatusPagamento(status).label}.",
                messages.SUCCESS,
            )
