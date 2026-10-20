"""Views web: vitrine B2C (jogadores) e Portal do Gestor B2B (ArenaManager)."""

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch, QuerySet, Sum
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

from . import acesso, checkout, gestao, jogadores, partidas, peladas, razao
from .forms import (
    AbrirPartidaForm,
    ArenaConfigForm,
    AvaliacaoPartidaForm,
    CadastroJogadorForm,
    ChavePixForm,
    CheckoutForm,
    CodigoAcessoForm,
    FiltroVitrineForm,
    NovaPeladaForm,
    TelefoneForm,
    PerfilJogadorForm,
    QuadraForm,
)
from .models import (
    STATUS_INSCRICAO_ATIVA,
    VALOR_MINIMO_SAQUE,
    Arena,
    Booking,
    Court,
    MotivoCancelamento,
    DirecaoNivel,
    NivelCompetitividade,
    OpenMatch,
    OrigemNivel,
    Payment,
    Posicao,
    StatusInscricao,
    StatusPagamento,
    StatusPartida,
    TipoElogio,
    TipoLancamento,
    WaitlistEntry,
)
from .formatacao import formatar_brl as brl
from .localizacao import distancia_km, ler_coordenadas
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


def _confirmados_com_perfil() -> Prefetch:
    """Jogadores confirmados de cada partida (para os rostos nos cards)."""
    return Prefetch(
        "inscricoes",
        queryset=Booking.objects.confirmadas().select_related("player__perfil").order_by("confirmada_em"),
        to_attr="confirmadas",
    )


class LandingView(TemplateView):
    """Página institucional (raiz do site): o que é o ArenaMatch, para jogadores e arenas."""

    template_name = "site/inicio.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        abertas = OpenMatch.objects.vitrine().filter(status=StatusPartida.ABERTA)
        contexto.update(
            total_partidas=abertas.count(),
            total_vagas=abertas.aggregate(total=Sum("vagas_disponiveis"))["total"] or 0,
            total_arenas=Arena.objects.count(),
            total_jogadores=Booking.objects.filter(status=StatusInscricao.CONFIRMADA)
            .values("player")
            .distinct()
            .count(),
            destaques=list(abertas.prefetch_related(_confirmados_com_perfil())[:3]),
        )
        return contexto


def redirecionar_para_o_app(request: HttpRequest, caminho: str) -> HttpResponse:
    """Links antigos da vitrine (antes em ``/``) agora vivem em ``/app/``."""
    destino = f"/app/{caminho}"
    if request.META.get("QUERY_STRING"):
        destino += f"?{request.META['QUERY_STRING']}"
    return redirect(destino, permanent=True)


class VitrineView(ListView):
    """Feed de partidas abertas: filtros de um toque, rostos de quem vai e "perto de mim"."""

    template_name = "arena/index.html"
    context_object_name = "partidas"

    def get_queryset(self) -> list[OpenMatch]:
        self.filtro = FiltroVitrineForm(self.request.GET or None)
        usuario = self.request.user
        self.perfil = jogadores.perfil_do(usuario)
        partidas = OpenMatch.objects.vitrine().filtrar(**self.filtro.filtros())
        if self.request.GET.get("meu_nivel") and self.perfil:
            partidas = partidas.para_o_nivel(self.perfil.nivel)
        partidas = list(partidas.prefetch_related(_confirmados_com_perfil()))
        self.coordenadas = ler_coordenadas(self.request.GET.get("lat"), self.request.GET.get("lng"))
        for partida in partidas:
            arena = partida.time_slot.court.arena
            partida.distancia = (
                distancia_km(*self.coordenadas, float(arena.latitude), float(arena.longitude))
                if self.coordenadas and arena.latitude is not None
                else None
            )
            partida.bloqueio = (
                jogadores.motivo_inelegivel(partida, usuario, Posicao.LINHA, perfil=self.perfil)
                if usuario.is_authenticated and usuario.is_player and self.perfil
                else None
            )
            partida.goleiros_livres = partida.vagas_goleiro - sum(
                1 for inscricao in partida.confirmadas if inscricao.posicao == Posicao.GOLEIRO
            )
        if self.coordenadas:
            partidas.sort(key=lambda p: (p.distancia is None, p.distancia or 0))
        return partidas

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        usuario = self.request.user
        contexto.update(
            filtro=self.filtro,
            perfil=self.perfil,
            perto=self.coordenadas is not None,
            meu_nivel=bool(self.request.GET.get("meu_nivel")),
            saldo=razao.saldo_do_jogador(usuario) if usuario.is_authenticated else None,
            pode_ser_goleiro=bool(self.perfil and self.perfil.pode_ser_goleiro),
            filtros_ativos=bool(self.request.GET),
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
        motivo_linha = motivo_goleiro = None
        if usuario.is_authenticated:
            minha = partida.inscricoes.filter(player=usuario, status__in=STATUS_INSCRICAO_ATIVA).first()
            na_lista = WaitlistEntry.objects.filter(partida=partida, jogador=usuario).exists()
            if usuario.is_player:
                motivo_linha = jogadores.motivo_inelegivel(partida, usuario, Posicao.LINHA)
                motivo_goleiro = jogadores.motivo_inelegivel(partida, usuario, Posicao.GOLEIRO)
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
            # Mensagem só quando nenhuma das vagas serve para o jogador.
            motivo_inelegivel=motivo_linha if motivo_linha and (motivo_goleiro or not partida.vagas_goleiro) else None,
            perfil_incompleto=usuario.is_authenticated and usuario.is_player and jogadores.perfil_do(usuario) is None,
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

    def _posicoes(self, partida: OpenMatch) -> list[str]:
        """Vagas (linha, goleiro) que o jogador pode pegar nesta partida."""
        return [
            posicao
            for posicao in (Posicao.LINHA, Posicao.GOLEIRO)
            if jogadores.motivo_inelegivel(partida, self.request.user, posicao) is None
        ]

    def _formulario(self, partida: OpenMatch, dados: Any = None) -> CheckoutForm:
        return CheckoutForm(
            dados,
            partida=partida,
            saldo=razao.saldo_do_jogador(self.request.user),
            posicoes=self._posicoes(partida),
        )

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
        if jogadores.perfil_do(usuario) is None:
            messages.info(self.request, "Antes da primeira partida, conte rapidinho como você joga.")
            destino = reverse("arena:checkout", args=[partida.pk])
            return redirect(f"{reverse('arena:configurar_perfil')}?next={destino}")
        posicoes = self._posicoes(partida)
        if not posicoes or (posicoes == [Posicao.GOLEIRO] and not partida.vagas_goleiro):
            messages.warning(self.request, jogadores.motivo_inelegivel(partida, usuario, Posicao.LINHA))
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
    """Comprovante da inscrição (visível apenas para o próprio jogador), com o QR do check-in."""

    template_name = "arena/inscricao.html"
    context_object_name = "inscricao"

    def get_queryset(self) -> QuerySet:
        return Booking.objects.filter(player=self.request.user).select_related(
            "open_match__time_slot__court__arena"
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        inscricao = self.object
        partida = inscricao.open_match
        confirmada = inscricao.status == StatusInscricao.CONFIRMADA
        contexto.update(
            url_check_in=self.request.build_absolute_uri(
                reverse("gestor:check_in_inscricao", args=[inscricao.pk])
            ),
            times=jogadores.montar_times(partida) if confirmada and partida.jogo_confirmado else None,
            pode_avaliar=jogadores.pode_avaliar(partida, self.request.user),
        )
        return contexto


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
        for inscricao in anteriores:
            inscricao.pode_avaliar = jogadores.pode_avaliar(inscricao.open_match, self.request.user)
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
    """Login com usuário e senha (o padrão do app é entrar com o celular)."""

    template_name = "arena/entrar.html"
    redirect_authenticated_user = True


CHAVE_TELEFONE_SESSAO = "acesso_telefone"


class EntrarTelefoneView(FormView):
    """Passo 1 do login por celular: envia o código por SMS."""

    template_name = "arena/entrar_telefone.html"
    form_class = TelefoneForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated:
            return redirect("arena:vitrine")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        contexto["next"] = self.request.GET.get("next") or self.request.POST.get("next", "")
        return contexto

    def form_valid(self, form: TelefoneForm) -> HttpResponse:
        try:
            codigo = acesso.solicitar_codigo(form.cleaned_data["telefone"])
        except ValidationError as erro:
            form.add_error("telefone", erro)
            return self.form_invalid(form)
        self.request.session[CHAVE_TELEFONE_SESSAO] = acesso.normalizar_telefone(form.cleaned_data["telefone"])
        if settings.DEBUG and acesso.obter_sms().simulado:
            messages.info(self.request, f"Modo de demonstração: o código enviado por SMS é {codigo}.")
        destino = reverse("arena:verificar_codigo")
        proximo = self.request.POST.get("next")
        return redirect(f"{destino}?next={proximo}" if proximo else destino)


class VerificarCodigoView(FormView):
    """Passo 2 do login por celular: confere o código e entra (ou cria a conta)."""

    template_name = "arena/verificar_codigo.html"
    form_class = CodigoAcessoForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.telefone = request.session.get(CHAVE_TELEFONE_SESSAO)
        if not self.telefone:
            return redirect("arena:entrar_telefone")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        contexto.update(
            telefone=acesso.formatar_telefone(self.telefone),
            next=self.request.GET.get("next") or self.request.POST.get("next", ""),
        )
        return contexto

    def form_valid(self, form: CodigoAcessoForm) -> HttpResponse:
        try:
            usuario = acesso.validar_codigo(self.telefone, form.cleaned_data["codigo"], form.cleaned_data["nome"])
        except ValidationError as erro:
            form.add_error("codigo", erro)
            return self.form_invalid(form)
        login(self.request, usuario, backend="django.contrib.auth.backends.ModelBackend")
        self.request.session.pop(CHAVE_TELEFONE_SESSAO, None)
        destino = _destino_seguro(
            self.request, self.request.POST.get("next") or self.request.GET.get("next"), reverse("arena:vitrine")
        )
        if usuario.is_player and jogadores.perfil_do(usuario) is None:
            messages.success(self.request, "Conta criada! Agora conte rapidinho como você joga.")
            return redirect(f"{reverse('arena:configurar_perfil')}?next={destino}")
        messages.success(self.request, f"Bem-vindo de volta, {usuario.first_name or usuario.username}!")
        return redirect(destino)


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
        destino = _destino_seguro(self.request, destino, reverse("arena:vitrine"))
        return f"{reverse('arena:configurar_perfil')}?next={destino}"


class ConfigurarPerfilView(LoginRequiredMixin, FormView):
    """Questionário do perfil: posição, gol e nível (calculado a partir das respostas)."""

    template_name = "arena/perfil_configurar.html"
    form_class = PerfilJogadorForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated and not request.user.is_player:
            messages.warning(request, "Perfis de jogador são só para contas de jogador.")
            return redirect("arena:vitrine")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        self.perfil = jogadores.perfil_do(self.request.user)
        kwargs["nivel_travado"] = self.perfil is not None and self.perfil.nivel_origem == OrigemNivel.AJUSTADO
        if self.perfil is not None:
            kwargs["initial"] = {
                "apelido": self.perfil.apelido,
                "posicao": self.perfil.posicao,
                "joga_no_gol": self.perfil.joga_no_gol,
                "regiao": self.perfil.regiao,
            }
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        contexto.update(perfil=self.perfil, next=self.request.GET.get("next") or self.request.POST.get("next", ""))
        return contexto

    def form_valid(self, form: PerfilJogadorForm) -> HttpResponse:
        dados = form.cleaned_data
        perfil = jogadores.salvar_perfil(
            self.request.user,
            posicao=dados["posicao"],
            joga_no_gol=dados["joga_no_gol"],
            apelido=dados["apelido"],
            regiao=dados["regiao"],
            nivel_declarado=form.nivel_declarado(),
        )
        messages.success(self.request, f"Perfil salvo. Seu nível: {perfil.nivel} · {perfil.get_nivel_display()}.")
        destino = self.request.POST.get("next") or self.request.GET.get("next")
        return redirect(_destino_seguro(self.request, destino, reverse("arena:perfil")))


class PerfilView(LoginRequiredMixin, TemplateView):
    """Perfil do jogador: nível, posição, partidas jogadas, confiabilidade e elogios."""

    template_name = "arena/perfil.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_player and jogadores.perfil_do(request.user) is None:
            return redirect("arena:configurar_perfil")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        contexto.update(
            perfil=jogadores.perfil_do(self.request.user),
            estatisticas=jogadores.estatisticas(self.request.user),
            saldo=razao.saldo_do_jogador(self.request.user),
        )
        return contexto


class AvaliarPartidaView(LoginRequiredMixin, View):
    """Depois do jogo: nível da partida, elogios e sinais de nível dos colegas."""

    template_name = "arena/avaliar_partida.html"

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.partida = get_object_or_404(OpenMatch.objects.com_relacionados(), pk=kwargs["pk"])
        if not jogadores.pode_avaliar(self.partida, request.user):
            messages.info(request, "Esta partida não está disponível para avaliação.")
            return redirect("arena:minhas_inscricoes")
        return super().dispatch(request, *args, **kwargs)

    def handle_no_permission(self) -> HttpResponse:
        return redirect(f"{reverse('arena:entrar')}?next={self.request.get_full_path()}")

    def get(self, request: HttpRequest, pk: str) -> HttpResponse:
        return self._exibir(AvaliacaoPartidaForm())

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        form = AvaliacaoPartidaForm(request.POST)
        if not form.is_valid():
            return self._exibir(form)
        colegas = jogadores.colegas_de_partida(self.partida, request.user)
        elogios = {str(c.player_id): request.POST.get(f"elogio_{c.player_id}", "") for c in colegas}
        sinais = {str(c.player_id): request.POST.get(f"sinal_{c.player_id}", "") for c in colegas}
        try:
            jogadores.registrar_avaliacao(
                self.partida,
                request.user,
                form.cleaned_data["percepcao"],
                {alvo: tipo for alvo, tipo in elogios.items() if tipo},
                {alvo: direcao for alvo, direcao in sinais.items() if direcao},
            )
        except ValidationError as erro:
            messages.error(request, _mensagens(erro))
        else:
            messages.success(request, "Valeu pela avaliação! Ela ajuda a montar jogos mais equilibrados.")
        return redirect("arena:minhas_inscricoes")

    def _exibir(self, form: AvaliacaoPartidaForm) -> HttpResponse:
        return render(
            self.request,
            self.template_name,
            {
                "partida": self.partida,
                "form": form,
                "colegas": jogadores.colegas_de_partida(self.partida, self.request.user),
                "tipos_elogio": TipoElogio.choices,
                "direcoes": DirecaoNivel.choices,
                "com_faixa": self.partida.nivel_competitividade != NivelCompetitividade.ABERTA,
            },
        )


# =============================================================================
# Pelada de grupo (C2C): o organizador vende as vagas que faltam
# =============================================================================


class OrganizarView(LoginRequiredMixin, TemplateView):
    """Painel do organizador: carteira (saldo e saque via Pix) e as peladas dele."""

    template_name = "arena/organizar.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        contexto.update(peladas.resumo_do_organizador(self.request.user))
        contexto.setdefault("form_pix", ChavePixForm(instance=contexto["wallet"]))
        contexto["valor_minimo_saque"] = VALOR_MINIMO_SAQUE
        return contexto

    def post(self, request: HttpRequest) -> HttpResponse:
        """Salva a chave Pix (o formulário fica na mesma tela)."""
        form = ChavePixForm(request.POST, instance=peladas.wallet_do(request.user))
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form_pix=form))
        form.save()
        messages.success(request, "Chave Pix salva. Os saques vão para ela.")
        return redirect("arena:organizar")


class NovaPeladaView(LoginRequiredMixin, FormView):
    """O organizador publica as vagas que faltam na pelada do grupo."""

    template_name = "arena/pelada_nova.html"
    form_class = NovaPeladaForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated and not request.user.is_player:
            messages.warning(request, "Só contas de jogador organizam peladas.")
            return redirect("arena:vitrine")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        contexto["taxas"] = NovaPeladaForm.taxas()
        return contexto

    def form_valid(self, form: NovaPeladaForm) -> HttpResponse:
        dados = form.cleaned_data
        try:
            pelada = peladas.criar_pelada(
                self.request.user,
                dados["quadra"],
                dados["dia"],
                dados["hora_inicio"],
                dados["hora_fim"],
                titulo=dados["titulo"] or peladas.titulo_padrao(self.request.user),
                vagas_linha=dados["vagas_linha"],
                valor_por_vaga=dados["valor_por_vaga"],
                vagas_goleiro=dados["vagas_goleiro"],
                valor_goleiro=dados["valor_goleiro"],
                nivel=dados["nivel"],
            )
        except ValidationError as erro:
            form.add_error(None, _mensagens(erro))
            return self.form_invalid(form)
        messages.success(
            self.request,
            f"{pelada.titulo} está no feed: {pelada.vagas_totais} vaga(s) a "
            f"{brl(pelada.preco_final_jogador)}. Compartilhe o link com a galera.",
        )
        return redirect(pelada)


class CancelarPeladaView(LoginRequiredMixin, View):
    """O organizador desiste das vagas; quem comprou recebe o dinheiro de volta."""

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        pelada = get_object_or_404(OpenMatch, pk=pk, organizador=request.user)
        try:
            reembolsados = peladas.cancelar_pelada(pelada, request.user)
        except ValidationError as erro:
            messages.error(request, _mensagens(erro))
        else:
            messages.success(
                request,
                f"Vagas canceladas. {reembolsados} jogador(es) reembolsado(s)."
                if reembolsados
                else "Vagas canceladas. Ninguém tinha comprado, então não houve reembolso.",
            )
        return redirect("arena:organizar")


class SacarView(LoginRequiredMixin, View):
    """Saque via Pix de todo o saldo disponível do organizador."""

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            saque = razao.solicitar_saque(request.user)
        except ValidationError as erro:
            messages.error(request, _mensagens(erro))
        else:
            messages.success(request, f"Saque de {brl(saque.valor)} enviado para a sua chave Pix.")
        return redirect("arena:organizar")


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
    """Início do portal: os números do dinheiro e o botão "Abrir quadra"."""

    template_name = "arena/manager_dashboard.html"
    secao = "dashboard"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        dias, grades = gestao.semana_da_arena(self.arena)
        contexto.update(indicadores=gestao.indicadores_dashboard(self.arena, grades), hoje=dias[0])
        return contexto


class GestorAbrirQuadraView(GestorRequiredMixin, TemplateView):
    """Horários livres do dia por quadra: um toque publica a partida com os valores sugeridos.

    ``?dia=AAAA-MM-DD`` escolhe um dos próximos 7 dias.
    """

    template_name = "arena/manager_abrir_quadra.html"
    secao = "dashboard"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        dias, grades = gestao.semana_da_arena(self.arena)
        try:
            indice = dias.index(parse_date(self.request.GET.get("dia") or "") or dias[0])
        except ValueError:
            indice = 0
        contexto.update(
            dias=gestao.dias_do_painel(dias, grades),
            dia=dias[indice],
            quadras_do_dia=gestao.agenda_do_dia(grades, indice),
            hoje=dias[0],
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
                (tipo.PELADA, "Pelada de grupo", contagem[tipo.PELADA]),
                (tipo.PARTIDA, "Partida aberta", contagem[tipo.PARTIDA] + contagem[tipo.LOTADA]),
                (tipo.VAGO, "Livre", contagem[tipo.VAGO]),
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
                f"Partida cancelada. {reembolsados} jogador(es) reembolsado(s) automaticamente."
                if reembolsados
                else "Partida cancelada. Ninguém tinha comprado vaga, então não houve reembolso.",
            )
        return redirect(_destino_seguro(request, request.POST.get("voltar"), reverse("gestor:dashboard")))


class GestorCheckInView(GestorRequiredMixin, TemplateView):
    """Recepção: partidas de hoje com a lista de presença e os times sugeridos."""

    template_name = "arena/manager_check_in.html"
    secao = "check_in"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        hoje = timezone.localdate()
        partidas_de_hoje = (
            OpenMatch.objects.filter(time_slot__court__arena=self.arena, time_slot__data=hoje)
            .exclude(status=StatusPartida.CANCELADA)
            .com_relacionados()
            .order_by("time_slot__hora_inicio")
        )
        contexto["partidas"] = [
            {
                "partida": partida,
                "inscricoes": partida.inscricoes.filter(status=StatusInscricao.CONFIRMADA)
                .select_related("player__perfil")
                .order_by("posicao", "player__first_name"),
                "times": jogadores.montar_times(partida),
            }
            for partida in partidas_de_hoje
        ]
        return contexto

    def post(self, request: HttpRequest) -> HttpResponse:
        inscricao = get_object_or_404(
            Booking, pk=request.POST.get("inscricao"), open_match__time_slot__court__arena__in=self.arenas
        )
        try:
            jogadores.registrar_check_in(inscricao)
        except ValidationError as erro:
            messages.error(request, _mensagens(erro))
        else:
            messages.success(request, f"Check-in de {inscricao.player.nome_publico} feito.")
        return redirect("gestor:check_in")


class GestorCheckInInscricaoView(GestorRequiredMixin, TemplateView):
    """Destino do QR do comprovante: mostra o jogador e confirma a presença."""

    template_name = "arena/manager_check_in_inscricao.html"
    secao = "check_in"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        contexto["inscricao"] = self._inscricao()
        contexto["pode_fazer_check_in"] = jogadores.pode_fazer_check_in(contexto["inscricao"])
        return contexto

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        inscricao = self._inscricao()
        try:
            jogadores.registrar_check_in(inscricao)
        except ValidationError as erro:
            messages.error(request, _mensagens(erro))
        else:
            messages.success(request, f"Check-in de {inscricao.player.nome_publico} feito. Bom jogo!")
        return redirect("gestor:check_in_inscricao", pk=pk)

    def _inscricao(self) -> Booking:
        return get_object_or_404(
            Booking.objects.select_related("player__perfil", "open_match__time_slot__court"),
            pk=self.kwargs["pk"],
            open_match__time_slot__court__arena__in=self.arenas,
        )


class GestorFinanceiroView(GestorRequiredMixin, TemplateView):
    """Carteira da arena: saldo disponível, a liberar, extrato e repasses."""

    template_name = "arena/manager_financeiro.html"
    secao = "financeiro"
    por_pagina = 20
    periodos = (("", "Todo o período"), ("mes", "Este mês"), ("a_liberar", "A liberar"))
    tipos = (
        ("", "Tudo"),
        (TipoLancamento.VENDA_VAGA, "Vendas"),
        (TipoLancamento.ESTORNO, "Devoluções"),
        (TipoLancamento.REPASSE, "Transferências"),
        (TipoLancamento.AJUSTE_FECHAMENTO, "Centavos"),
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
