"""Views web: vitrine B2C (jogadores) e Portal do Gestor B2B (ArenaManager)."""

from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import QuerySet, Sum
from django.forms import Form
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.decorators import method_decorator
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DetailView, FormView, ListView, TemplateView

from . import checkout, gestao, partidas, razao
from .forms import (
    AbrirPartidaForm,
    ArenaConfigForm,
    CadastroJogadorForm,
    CheckoutForm,
    FiltroVitrineForm,
    QuadraForm,
)
from .models import (
    STATUS_INSCRICAO_ATIVA,
    Arena,
    Booking,
    Court,
    MotivoCancelamento,
    NivelCompetitividade,
    OpenMatch,
    Payment,
    Posicao,
    StatusInscricao,
    StatusPagamento,
    StatusPartida,
    TipoLancamento,
    WaitlistEntry,
)
from .pagamentos import obter_gateway


def _destino_seguro(request: HttpRequest, destino: str | None, padrao: str) -> str:
    """Devolve ``destino`` se for um endereço interno; caso contrário, ``padrao``."""
    if destino and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return destino
    return padrao


def _mensagens(erro: ValidationError) -> str:
    return " ".join(erro.messages)


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
    """Detalhes da partida: local, jogadores confirmados e chamada para garantir a vaga."""

    template_name = "arena/partida_detalhe.html"
    context_object_name = "partida"
    queryset = OpenMatch.objects.com_relacionados().com_confirmados()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        partida = self.object
        confirmadas = list(
            partida.inscricoes.confirmadas().select_related("player").order_by("confirmada_em")
        )
        usuario = self.request.user
        minha = None
        na_lista = False
        if usuario.is_authenticated:
            minha = partida.inscricoes.filter(player=usuario, status__in=STATUS_INSCRICAO_ATIVA).first()
            na_lista = WaitlistEntry.objects.filter(partida=partida, jogador=usuario).exists()
        livres_linha = partida.vagas_livres(Posicao.LINHA)
        livres_goleiro = partida.vagas_livres(Posicao.GOLEIRO)
        contexto.update(
            linha=[i.player for i in confirmadas if i.posicao == Posicao.LINHA],
            goleiros=[i.player for i in confirmadas if i.posicao == Posicao.GOLEIRO],
            livres_linha=livres_linha,
            livres_goleiro=livres_goleiro,
            vagas_livres_linha=range(min(livres_linha, 24)),
            vagas_livres_goleiro=range(livres_goleiro),
            minha_inscricao=minha,
            na_lista_de_espera=na_lista,
        )
        return contexto


class CheckoutView(LoginRequiredMixin, View):
    """GET mostra a escolha da vaga e do pagamento; POST reserva a vaga e cobra."""

    _MENSAGEM_NAO_JOGADOR = (
        "Sua conta não é de jogador. Crie uma conta de jogador para reservar vagas."
    )

    def get(self, request: HttpRequest, pk: str) -> HttpResponse:
        partida = self._partida(pk)
        resposta = self._bloqueio(partida)
        if resposta:
            return resposta
        return self._exibir(partida, self._formulario(partida))

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        partida = self._partida(pk)
        resposta = self._bloqueio(partida)
        if resposta:
            return resposta
        form = self._formulario(partida, request.POST)
        if not form.is_valid():
            return self._exibir(partida, form)
        try:
            inscricao = checkout.iniciar_checkout(
                partida,
                request.user,
                posicao=form.cleaned_data["posicao"],
                metodo=form.cleaned_data["metodo"],
            )
        except ValidationError as erro:
            messages.error(request, _mensagens(erro))
            return redirect(partida)
        if inscricao.status == StatusInscricao.CONFIRMADA:
            messages.success(request, "Vaga garantida! Te vemos em campo.")
            return redirect("arena:inscricao", pk=inscricao.pk)
        if inscricao.status == StatusInscricao.AGUARDANDO_PAGAMENTO:
            return redirect("arena:pagamento", pk=inscricao.pk)
        messages.error(request, "O pagamento não foi concluído. A vaga voltou para a partida.")
        return redirect(partida)

    def _partida(self, pk: str) -> OpenMatch:
        return get_object_or_404(OpenMatch.objects.com_relacionados(), pk=pk)

    def _formulario(self, partida: OpenMatch, dados: Any = None) -> CheckoutForm:
        return CheckoutForm(dados, partida=partida, saldo=razao.saldo_do_jogador(self.request.user))

    def _exibir(self, partida: OpenMatch, form: CheckoutForm) -> HttpResponse:
        return render(
            self.request,
            "arena/checkout.html",
            {
                "partida": partida,
                "form": form,
                "saldo": razao.saldo_do_jogador(self.request.user),
                "livres_goleiro": partida.vagas_livres(Posicao.GOLEIRO),
            },
        )

    def _bloqueio(self, partida: OpenMatch) -> HttpResponse | None:
        """Redireciona quem não pode comprar esta vaga agora (``None`` se pode)."""
        usuario = self.request.user
        if not usuario.is_player:
            messages.warning(self.request, self._MENSAGEM_NAO_JOGADOR)
            return redirect(partida)
        ativa = partida.inscricoes.filter(player=usuario, status__in=STATUS_INSCRICAO_ATIVA).first()
        if ativa is not None:
            if ativa.status == StatusInscricao.AGUARDANDO_PAGAMENTO and not ativa.reserva_vencida:
                return redirect("arena:pagamento", pk=ativa.pk)
            if ativa.status == StatusInscricao.CONFIRMADA:
                messages.info(self.request, "Você já está nesta partida.")
                return redirect("arena:inscricao", pk=ativa.pk)
        if not partida.aceita_inscricoes:
            messages.warning(self.request, "Esta partida não está aceitando novas inscrições.")
            return redirect(partida)
        return None


class PagamentoView(LoginRequiredMixin, DetailView):
    """Pix pendente: código copia e cola e prazo da reserva da vaga."""

    template_name = "arena/pagamento.html"
    context_object_name = "inscricao"

    def get_queryset(self) -> QuerySet:
        return Booking.objects.filter(player=self.request.user).select_related(
            "open_match__time_slot__court__arena"
        )

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.object = self.get_object()
        if self.object.status != StatusInscricao.AGUARDANDO_PAGAMENTO or self.object.reserva_vencida:
            return redirect("arena:inscricao", pk=self.object.pk)
        return self.render_to_response(self.get_context_data(object=self.object))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        contexto.update(
            pagamento=self.object.pagamentos.filter(status=StatusPagamento.PENDENTE).first(),
            permite_simulacao=obter_gateway().permite_simulacao,
        )
        return contexto


class SimularPagamentoView(LoginRequiredMixin, View):
    """Aprova o Pix pendente (gateway simulado de desenvolvimento)."""

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        inscricao = get_object_or_404(Booking, pk=pk, player=request.user)
        try:
            inscricao = checkout.simular_pagamento(inscricao)
        except ValidationError as erro:
            messages.error(request, _mensagens(erro))
        else:
            if inscricao.status == StatusInscricao.CONFIRMADA:
                messages.success(request, "Pagamento aprovado. Vaga garantida!")
            else:
                messages.warning(request, "O prazo da reserva acabou e a vaga foi para outro jogador. O valor foi devolvido.")
        return redirect("arena:inscricao", pk=pk)


class InscricaoView(LoginRequiredMixin, DetailView):
    """Comprovante da inscrição (visível apenas para o próprio jogador)."""

    template_name = "arena/inscricao.html"
    context_object_name = "inscricao"

    def get_queryset(self) -> QuerySet:
        return Booking.objects.filter(player=self.request.user).select_related(
            "open_match__time_slot__court__arena"
        )


class CancelarInscricaoView(LoginRequiredMixin, View):
    """Cancela a inscrição do jogador conforme a política (crédito até 24h antes)."""

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        inscricao = get_object_or_404(Booking, pk=pk, player=request.user)
        try:
            mensagem = checkout.cancelar_inscricao(inscricao)
        except ValidationError as erro:
            messages.error(request, _mensagens(erro))
            return redirect("arena:inscricao", pk=pk)
        messages.success(request, mensagem)
        return redirect("arena:minhas_inscricoes")


class RepassarVagaView(LoginRequiredMixin, View):
    """Libera a vaga paga para a lista de espera (ou desfaz o repasse)."""

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        inscricao = get_object_or_404(Booking, pk=pk, player=request.user)
        try:
            if request.POST.get("acao") == "desfazer":
                checkout.desfazer_repasse(inscricao)
                messages.success(request, "Repasse desfeito. A vaga continua sua.")
            else:
                checkout.repassar_vaga(inscricao)
                messages.success(
                    request,
                    "Vaga liberada para a lista de espera. Se alguém assumir, você recebe crédito integral.",
                )
        except ValidationError as erro:
            messages.error(request, _mensagens(erro))
        return redirect("arena:inscricao", pk=pk)


class ListaDeEsperaView(LoginRequiredMixin, View):
    """Entra ou sai da lista de espera de uma partida lotada."""

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        partida = get_object_or_404(OpenMatch.objects.com_relacionados(), pk=pk)
        if request.POST.get("acao") == "sair":
            checkout.sair_da_lista_de_espera(partida, request.user)
            messages.info(request, "Você saiu da lista de espera.")
            return redirect(partida)
        try:
            checkout.entrar_na_lista_de_espera(partida, request.user, request.POST.get("posicao", Posicao.LINHA))
        except ValidationError as erro:
            messages.error(request, _mensagens(erro))
        else:
            messages.success(request, "Você está na lista de espera. Avisamos por e-mail se abrir vaga.")
        return redirect(partida)


class MinhasInscricoesView(LoginRequiredMixin, TemplateView):
    """Inscrições do jogador (próximas e histórico) e o crédito disponível."""

    template_name = "arena/minhas_inscricoes.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        inscricoes = (
            Booking.objects.filter(player=self.request.user)
            .exclude(status__in=(StatusInscricao.EXPIRADA, StatusInscricao.CANCELADA), confirmada_em__isnull=True)
            .select_related("open_match__time_slot__court__arena")
            .order_by("open_match__time_slot__data", "open_match__time_slot__hora_inicio")
        )
        proximas, anteriores = [], []
        for inscricao in inscricoes:
            (anteriores if inscricao.open_match.time_slot.ja_comecou else proximas).append(inscricao)
        contexto.update(
            proximas=proximas,
            anteriores=anteriores[::-1],
            saldo=razao.saldo_do_jogador(self.request.user),
            extrato=razao.extrato_do_jogador(self.request.user)[:10],
        )
        return contexto


@method_decorator(csrf_exempt, name="dispatch")
class PagamentoWebhookView(View):
    """Recebe as notificações do gateway de pagamento (webhook)."""

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            notificacao = obter_gateway().interpretar_notificacao(request)
        except PermissionDenied:
            return HttpResponseForbidden()
        except ValueError:
            return HttpResponseBadRequest()
        try:
            pagamento = checkout.processar_notificacao(
                notificacao.gateway_id, aprovado=notificacao.aprovado, resposta=notificacao.resposta
            )
        except Payment.DoesNotExist:
            return HttpResponseNotFound()
        return JsonResponse({"status": pagamento.status})


class EntrarView(LoginView):
    """Login da vitrine (jogadores); gestores usam o portal em /manager/."""

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
            aluguel_sugerido=gestao.aluguel_sugerido(quadra) if quadra else None,
            goleiros_sugeridos=gestao.vagas_goleiro_sugeridas(quadra.capacidade_padrao) if quadra else 0,
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
                dados["valor_total_aluguel"],
                dados["nivel_competitividade"],
                dados["vagas_totais"],
                dados["vagas_goleiro"],
            )
        except ValidationError as erro:
            messages.error(request, _mensagens(erro))
        else:
            horario = partida.time_slot
            messages.success(
                request,
                f"Partida aberta publicada no app: {date_format(horario.data, 'D, d/m')} · "
                f"{horario.intervalo} · {horario.court.nome_ou_numero}.",
            )
        return redirect(destino)


class GestorCancelarPartidaView(GestorRequiredMixin, View):
    """Cancela uma partida da arena; todos os inscritos são reembolsados na hora."""

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        partida = get_object_or_404(OpenMatch, pk=pk, time_slot__court__arena__in=self.arenas)
        try:
            reembolsados = partidas.cancelar_partida(partida, MotivoCancelamento.ARENA)
        except ValidationError as erro:
            messages.error(request, _mensagens(erro))
        else:
            messages.success(
                request,
                f"Partida cancelada. {reembolsados} jogador(es) reembolsado(s) automaticamente.",
            )
        return redirect(_destino_seguro(request, request.POST.get("voltar"), reverse("gestor:dashboard")))


class GestorFinanceiroView(GestorRequiredMixin, TemplateView):
    """Carteira da arena: saldo disponível, a liberar, extrato e repasses."""

    template_name = "arena/manager_financeiro.html"
    secao = "financeiro"
    por_pagina = 20
    periodos = (("", "Todo o período"), ("mes", "Este mês"), ("a_liberar", "A liberar"))
    tipos = (
        ("", "Tudo"),
        (TipoLancamento.VENDA_VAGA, "Vendas"),
        (TipoLancamento.ESTORNO, "Estornos"),
        (TipoLancamento.REPASSE, "Repasses"),
        (TipoLancamento.AJUSTE_FECHAMENTO, "Ajustes"),
    )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        tipo = self.request.GET.get("tipo", "")
        tipo = tipo if tipo in dict(self.tipos) else ""
        periodo = self.request.GET.get("periodo", "")
        periodo = periodo if periodo in dict(self.periodos) else ""
        lancamentos = gestao.extrato_financeiro(self.arena, tipo or None, periodo or None)
        contexto.update(
            resumo=gestao.resumo_financeiro(self.arena),
            pagina=Paginator(lancamentos, self.por_pagina).get_page(self.request.GET.get("pagina")),
            repasses=self.arena.repasses.all()[:10],
            tipo=tipo,
            periodo=periodo,
            filtros_tipo=self.tipos,
            periodos=self.periodos,
            agora=timezone.now(),
        )
        return contexto


class GestorConfiguracoesView(GestorRequiredMixin, TemplateView):
    """Dados da arena, regras de mínimo de jogadores e cadastro de quadras."""

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
