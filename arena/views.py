"""Views web: vitrine B2C (jogadores) e Portal do Gestor B2B (ArenaManager)."""

from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import QuerySet, Sum
from django.forms import Form
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from . import gestao
from .forms import (
    AbrirPartidaForm,
    ArenaConfigForm,
    CadastroJogadorForm,
    FiltroVitrineForm,
    QuadraForm,
)
from .models import (
    STATUS_OCUPA_VAGA,
    Arena,
    Booking,
    Court,
    NivelCompetitividade,
    OpenMatch,
    StatusPagamento,
    StatusPartida,
)


def _destino_seguro(request: HttpRequest, destino: str | None, padrao: str) -> str:
    """Devolve ``destino`` se for um endereço interno; caso contrário, ``padrao``."""
    if destino and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return destino
    return padrao


class VitrineView(ListView):
    """Feed de partidas abertas, agrupado por dia e filtrável via query string."""

    template_name = "arena/index.html"
    context_object_name = "partidas"

    def get_queryset(self) -> QuerySet:
        self.filtro = FiltroVitrineForm(self.request.GET or None)
        return OpenMatch.objects.vitrine().filtrar(**self.filtro.filtros())

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        abertas = OpenMatch.objects.vitrine().filter(status=StatusPartida.ABERTA)
        contexto.update(
            filtro=self.filtro,
            total_partidas=abertas.count(),
            total_vagas=abertas.aggregate(total=Sum("vagas_disponiveis"))["total"] or 0,
            total_arenas=Arena.objects.count(),
        )
        return contexto


class PartidaDetalheView(DetailView):
    """Detalhes da partida: local, jogadores confirmados e chamada para reservar."""

    template_name = "arena/partida_detalhe.html"
    context_object_name = "partida"
    queryset = OpenMatch.objects.com_relacionados()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        inscricoes = list(
            self.object.inscricoes.filter(status_pagamento__in=STATUS_OCUPA_VAGA)
            .select_related("player")
            .order_by("data_inscricao")
        )
        usuario = self.request.user
        contexto.update(
            jogadores=[inscricao.player for inscricao in inscricoes],
            minha_inscricao=next(
                (i for i in inscricoes if usuario.is_authenticated and i.player_id == usuario.pk),
                None,
            ),
            vagas_livres=range(min(self.object.vagas_disponiveis, 24)),
        )
        return contexto


class ReservarVagaView(LoginRequiredMixin, View):
    """GET mostra a confirmação da reserva; POST cria a inscrição e abre o comprovante."""

    _MENSAGEM_NAO_JOGADOR = (
        "Sua conta não é de jogador. Crie uma conta de jogador para reservar vagas."
    )

    def get(self, request: HttpRequest, pk: str) -> HttpResponse:
        partida = self._partida(pk)
        bloqueio = self._motivo_bloqueio(partida)
        if bloqueio:
            messages.warning(request, bloqueio)
            return redirect(partida)
        return render(request, "arena/reservar.html", {"partida": partida})

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        partida = self._partida(pk)
        if not request.user.is_player:
            messages.error(request, self._MENSAGEM_NAO_JOGADOR)
            return redirect(partida)
        inscricao = Booking(open_match=partida, player=request.user)
        try:
            inscricao.save()
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
            return redirect(partida)
        messages.success(request, "Vaga garantida! Agora é só combinar o pagamento com a arena.")
        return redirect("arena:inscricao", pk=inscricao.pk)

    def _partida(self, pk: str) -> OpenMatch:
        return get_object_or_404(OpenMatch.objects.com_relacionados(), pk=pk)

    def _motivo_bloqueio(self, partida: OpenMatch) -> str | None:
        """Explica por que o usuário não pode reservar agora (``None`` se pode)."""
        usuario = self.request.user
        if not usuario.is_player:
            return self._MENSAGEM_NAO_JOGADOR
        if partida.inscricoes.filter(player=usuario, status_pagamento__in=STATUS_OCUPA_VAGA).exists():
            return "Você já está inscrito nesta partida."
        if not partida.aceita_inscricoes:
            return "Esta partida não está aceitando novas inscrições."
        return None


class InscricaoView(LoginRequiredMixin, DetailView):
    """Comprovante da inscrição (visível apenas para o próprio jogador)."""

    template_name = "arena/inscricao.html"
    context_object_name = "inscricao"

    def get_queryset(self) -> QuerySet:
        return Booking.objects.filter(player=self.request.user).select_related(
            "open_match__time_slot__court__arena"
        )


class CancelarInscricaoView(LoginRequiredMixin, View):
    """Cancela uma inscrição pendente do jogador e devolve a vaga."""

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        inscricao = get_object_or_404(
            Booking.objects.select_related("open_match__time_slot"), pk=pk, player=request.user
        )
        try:
            inscricao.cancelar()
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
            return redirect("arena:inscricao", pk=pk)
        messages.success(request, "Inscrição cancelada. A vaga voltou para a partida.")
        return redirect("arena:minhas_inscricoes")


class MinhasInscricoesView(LoginRequiredMixin, TemplateView):
    """Inscrições do jogador, separadas entre próximas partidas e histórico."""

    template_name = "arena/minhas_inscricoes.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        inscricoes = (
            Booking.objects.filter(player=self.request.user)
            .select_related("open_match__time_slot__court__arena")
            .order_by("open_match__time_slot__data", "open_match__time_slot__hora_inicio")
        )
        proximas, anteriores = [], []
        for inscricao in inscricoes:
            (anteriores if inscricao.open_match.time_slot.ja_comecou else proximas).append(inscricao)
        contexto.update(proximas=proximas, anteriores=anteriores[::-1])
        return contexto


class EntrarView(LoginView):
    """Login da vitrine (jogadores); gestores usam o painel em /admin/."""

    template_name = "arena/entrar.html"
    redirect_authenticated_user = True


class CadastroView(FormView):
    """Cadastro de jogador; ao concluir, o usuário já entra logado."""

    template_name = "arena/cadastro.html"
    form_class = CadastroJogadorForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated:
            return redirect("arena:vitrine")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        contexto["next"] = self.request.POST.get("next") or self.request.GET.get("next", "")
        return contexto

    def form_valid(self, form: CadastroJogadorForm) -> HttpResponse:
        usuario = form.save()
        login(self.request, usuario, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(self.request, f"Bem-vindo ao ArenaMatch, {usuario.first_name}!")
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        destino = self.request.POST.get("next") or self.request.GET.get("next")
        return _destino_seguro(self.request, destino, reverse("arena:vitrine"))


# =============================================================================
# Portal do Gestor (ArenaManager) - B2B
# =============================================================================

CHAVE_ARENA_SESSAO = "gestor_arena"


def _mensagens_de_erro(form: Form) -> str:
    return " ".join(erro for erros in form.errors.values() for erro in erros)


class GestorLoginView(LoginView):
    """Login do portal; depois de entrar, o gestor vai para o dashboard."""

    template_name = "arena/manager_login.html"
    redirect_authenticated_user = True

    def get_default_redirect_url(self) -> str:
        return reverse("gestor:dashboard")


class GestorRequiredMixin(LoginRequiredMixin):
    """Restringe o portal a gestores (e superusuários) e define a arena em uso.

    Quem administra mais de uma arena troca de arena com ``?arena=<slug>``; a
    escolha fica guardada na sessão.
    """

    login_url = reverse_lazy("gestor:login")
    secao = ""

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        usuario = request.user
        if not usuario.is_authenticated:
            return self.handle_no_permission()
        if not (usuario.is_manager or usuario.is_superuser):
            return render(request, "arena/manager_sem_acesso.html", status=403)
        self.arenas = list(gestao.arenas_do_usuario(usuario))
        if not self.arenas:
            return render(request, "arena/manager_sem_acesso.html", {"sem_arena": True}, status=403)
        self.arena = self._arena_em_uso()
        return super().dispatch(request, *args, **kwargs)

    def _arena_em_uso(self) -> Arena:
        por_slug = {arena.slug: arena for arena in self.arenas}
        escolhida = self.request.GET.get("arena")
        if escolhida in por_slug:
            self.request.session[CHAVE_ARENA_SESSAO] = escolhida
        return por_slug.get(self.request.session.get(CHAVE_ARENA_SESSAO), self.arenas[0])

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        contexto.update(arena=self.arena, arenas=self.arenas, secao=self.secao)
        return contexto


class GestorDashboardView(GestorRequiredMixin, TemplateView):
    """Visão financeira e operacional da arena."""

    template_name = "arena/manager_dashboard.html"
    secao = "dashboard"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        contexto.update(
            indicadores=gestao.indicadores_dashboard(self.arena),
            proximas=gestao.proximas_partidas(self.arena),
            agenda_hoje=gestao.agenda_de_hoje(self.arena),
            hoje=timezone.localdate(),
        )
        return contexto


class GestorAgendaView(GestorRequiredMixin, TemplateView):
    """Grade semanal de horários por quadra, com conversão rápida de horários vagos."""

    template_name = "arena/manager_agenda.html"
    secao = "agenda"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        hoje = timezone.localdate()
        try:
            referencia = parse_date(self.request.GET.get("semana") or "") or hoje
        except ValueError:
            referencia = hoje
        inicio = gestao.inicio_da_semana(referencia)
        dias = [inicio + timedelta(days=i) for i in range(gestao.DIAS_DA_SEMANA)]
        quadras = list(self.arena.quadras.order_by("nome_ou_numero"))
        escolhida = self.request.GET.get("quadra")
        quadra = next((q for q in quadras if str(q.pk) == escolhida), quadras[0] if quadras else None)
        linhas = gestao.grade_da_quadra(quadra, dias) if quadra else []
        contagem = gestao.contagem_por_tipo(linhas)
        tipo = gestao.TipoCelula
        contexto.update(
            hoje=hoje,
            dias=dias,
            quadras=quadras,
            quadra=quadra,
            linhas=linhas,
            legenda=[
                (tipo.MENSALISTA, "Mensalista", contagem[tipo.MENSALISTA]),
                (tipo.AVULSO, "Avulso", contagem[tipo.AVULSO]),
                (tipo.PARTIDA, "Partida aberta", contagem[tipo.PARTIDA] + contagem[tipo.LOTADA]),
                (tipo.VAGO, "Vago", contagem[tipo.VAGO]),
                (tipo.BLOQUEADO, "Bloqueado", contagem[tipo.BLOQUEADO]),
            ],
            semana_anterior=inicio - timedelta(days=7),
            proxima_semana=inicio + timedelta(days=7),
            semana_atual=gestao.inicio_da_semana(hoje),
            preco_sugerido=gestao.preco_sugerido(quadra) if quadra else None,
            niveis=NivelCompetitividade.choices,
        )
        return contexto


class GestorAbrirPartidaView(GestorRequiredMixin, View):
    """Ação "Transformar em Partida Aberta": publica a partida no app na hora."""

    def post(self, request: HttpRequest) -> HttpResponse:
        destino = _destino_seguro(request, request.POST.get("voltar"), reverse("gestor:agenda"))
        form = AbrirPartidaForm(request.POST, quadras=Court.objects.filter(arena__in=self.arenas))
        if not form.is_valid():
            messages.error(request, _mensagens_de_erro(form))
            return redirect(destino)
        dados = form.cleaned_data
        try:
            partida = gestao.abrir_partida(
                dados["quadra"],
                dados["dia"],
                dados["hora_inicio"],
                dados["hora_fim"],
                dados["preco_por_vaga"],
                dados["nivel_competitividade"],
                dados["vagas_totais"],
            )
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
        else:
            horario = partida.time_slot
            messages.success(
                request,
                f"Partida aberta publicada no app: {date_format(horario.data, 'D, d/m')} · "
                f"{horario.intervalo} · {horario.court.nome_ou_numero}.",
            )
        return redirect(destino)


class GestorFinanceiroView(GestorRequiredMixin, TemplateView):
    """Recebimentos, valores pendentes e reembolsos das inscrições da arena."""

    template_name = "arena/manager_financeiro.html"
    secao = "financeiro"
    por_pagina = 20
    periodos = (("", "Todo o período"), ("proximas", "Próximas partidas"), ("mes", "Este mês"))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        status = self.request.GET.get("status", "")
        status = status if status in StatusPagamento.values else ""
        periodo = self.request.GET.get("periodo", "")
        periodo = periodo if periodo in dict(self.periodos) else ""
        inscricoes = gestao.inscricoes_financeiro(self.arena, status or None, periodo or None)
        contexto.update(
            resumo=gestao.resumo_financeiro(self.arena),
            pagina=Paginator(inscricoes, self.por_pagina).get_page(self.request.GET.get("pagina")),
            status=status,
            periodo=periodo,
            filtros_status=[("", "Todas"), *StatusPagamento.choices],
            periodos=self.periodos,
        )
        return contexto


class GestorPagamentoView(GestorRequiredMixin, View):
    """Marca uma inscrição como paga ou reembolsada."""

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        inscricao = get_object_or_404(
            Booking.objects.select_related("player", "open_match__time_slot"),
            pk=pk,
            open_match__time_slot__court__arena__in=self.arenas,
        )
        status = request.POST.get("status", "")
        try:
            gestao.registrar_pagamento(inscricao, status)
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
        else:
            messages.success(
                request,
                f"Inscrição de {inscricao.player} marcada como {StatusPagamento(status).label.lower()}.",
            )
        return redirect(_destino_seguro(request, request.POST.get("voltar"), reverse("gestor:financeiro")))


class GestorConfiguracoesView(GestorRequiredMixin, TemplateView):
    """Dados da arena e cadastro de quadras."""

    template_name = "arena/manager_configuracoes.html"
    secao = "configuracoes"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        contexto.setdefault("form_arena", ArenaConfigForm(instance=self.arena))
        contexto.setdefault("form_quadra", QuadraForm())
        contexto["quadras"] = self.arena.quadras.order_by("nome_ou_numero")
        return contexto

    def post(self, request: HttpRequest) -> HttpResponse:
        if "salvar_arena" in request.POST:
            form_arena = ArenaConfigForm(request.POST, instance=self.arena)
            if self._salvar(form_arena):
                messages.success(request, "Dados da arena atualizados.")
                return redirect("gestor:configuracoes")
            return self.render_to_response(self.get_context_data(form_arena=form_arena))

        form_quadra = QuadraForm(request.POST, instance=Court(arena=self.arena))
        if self._salvar(form_quadra):
            messages.success(
                request,
                f"{form_quadra.instance.nome_ou_numero} cadastrada. Ela já aparece na agenda.",
            )
            return redirect("gestor:configuracoes")
        return self.render_to_response(self.get_context_data(form_quadra=form_quadra))

    @staticmethod
    def _salvar(form: ArenaConfigForm | QuadraForm) -> bool:
        """Valida e salva; regras do modelo que falharem no ``save()`` viram erros do formulário."""
        if not form.is_valid():
            return False
        try:
            form.save()
        except ValidationError as erro:
            form.add_error(None, erro.messages)
            return False
        return True
