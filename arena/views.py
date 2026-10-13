"""Vitrine web B2C: feed de partidas, detalhes, reserva de vaga e inscrições do jogador."""

from typing import Any

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.db.models import QuerySet, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from .forms import CadastroJogadorForm, FiltroVitrineForm
from .models import STATUS_OCUPA_VAGA, Arena, Booking, OpenMatch, StatusPartida


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
        if destino and url_has_allowed_host_and_scheme(
            destino,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return destino
        return reverse("arena:vitrine")
