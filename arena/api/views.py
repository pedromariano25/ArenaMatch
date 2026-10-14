"""Endpoints REST da frente B2C (app mobile e vitrine web)."""

from datetime import date

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from .. import checkout, jogadores, razao
from ..models import Arena, Booking, CustomUser, OpenMatch
from .permissions import IsJogador
from .serializers import (
    ArenaSerializer,
    CadastroJogadorSerializer,
    InscricaoSerializer,
    LancamentoSerializer,
    PartidaDetalheSerializer,
    PartidaSerializer,
    PerfilJogadorSerializer,
    PerfilSerializer,
)


def _data_do_parametro(request: Request, nome: str) -> date | None:
    """Lê um parâmetro de data (``AAAA-MM-DD``) da query string."""
    valor = request.query_params.get(nome)
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError as erro:
        raise ValidationError({nome: "Data inválida. Use o formato AAAA-MM-DD."}) from erro


class ApiRaizView(APIView):
    """Índice navegável da API do ArenaMatch."""

    permission_classes = (AllowAny,)

    def get(self, request: Request, format: str | None = None) -> Response:
        rotas = ("partidas", "arenas", "minhas_inscricoes", "carteira", "perfil", "cadastro", "token")
        return Response(
            {rota: reverse(f"api:{rota}", request=request, format=format) for rota in rotas}
        )


class PartidaListView(generics.ListAPIView):
    """Feed de partidas abertas que ainda não começaram (Aberta ou Lotada).

    Filtros opcionais: ``nivel``, ``piso``, ``arena`` (slug), ``data``,
    ``de`` e ``ate`` (datas no formato AAAA-MM-DD).
    """

    serializer_class = PartidaSerializer
    permission_classes = (AllowAny,)

    def get_queryset(self) -> QuerySet:
        params = self.request.query_params
        data = _data_do_parametro(self.request, "data")
        return OpenMatch.objects.vitrine().filtrar(
            nivel=params.get("nivel"),
            piso=params.get("piso"),
            arena=params.get("arena"),
            de=data or _data_do_parametro(self.request, "de"),
            ate=data or _data_do_parametro(self.request, "ate"),
        )


class PartidaDetailView(generics.RetrieveAPIView):
    """Detalhes de uma partida, com a lista pública de jogadores inscritos."""

    serializer_class = PartidaDetalheSerializer
    permission_classes = (AllowAny,)
    queryset = OpenMatch.objects.com_relacionados()


class InscricaoCreateView(generics.CreateAPIView):
    """Checkout: reserva a vaga e cobra o jogador autenticado.

    Envie ``posicao`` (``linha`` ou ``goleiro``) e ``metodo_pagamento`` (``pix``,
    ``cartao`` ou ``credito``). No Pix, a resposta traz o código copia e cola e a
    inscrição fica aguardando pagamento até ``reservada_ate``. Cartão, crédito e
    goleiro voltam confirmados. Regras de negócio (lotada, crédito insuficiente...)
    retornam HTTP 400.
    """

    serializer_class = InscricaoSerializer
    permission_classes = (IsAuthenticated, IsJogador)

    def perform_create(self, serializer: BaseSerializer) -> None:
        partida = get_object_or_404(OpenMatch, pk=self.kwargs["pk"])
        dados = serializer.validated_data
        serializer.instance = checkout.iniciar_checkout(
            partida,
            self.request.user,
            posicao=dados.get("posicao"),
            metodo=dados.get("metodo_pagamento"),
        )


class MinhasInscricoesListView(generics.ListAPIView):
    """Inscrições do jogador autenticado, da partida mais recente para a mais antiga."""

    serializer_class = InscricaoSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self) -> QuerySet:
        return (
            Booking.objects.filter(player=self.request.user)
            .select_related("open_match__time_slot__court__arena")
            .order_by("-open_match__time_slot__data", "-open_match__time_slot__hora_inicio")
        )


class InscricaoDetailView(generics.RetrieveDestroyAPIView):
    """Consulta (GET) ou cancela (DELETE) uma inscrição do próprio jogador.

    Reservas são canceladas sem custo; vagas pagas, até 24h antes do jogo, com
    crédito integral. Fora disso, HTTP 400 (use o repasse para a lista de espera).
    """

    serializer_class = InscricaoSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self) -> QuerySet:
        return Booking.objects.filter(player=self.request.user).select_related(
            "open_match__time_slot__court__arena"
        )

    def perform_destroy(self, instance: Booking) -> None:
        checkout.cancelar_inscricao(instance)


class _AcaoNaInscricaoView(APIView):
    """Base das ações do jogador sobre a própria inscrição."""

    permission_classes = (IsAuthenticated,)

    def inscricao(self) -> Booking:
        return get_object_or_404(Booking, pk=self.kwargs["pk"], player=self.request.user)

    def responder(self, inscricao: Booking) -> Response:
        inscricao.refresh_from_db()
        return Response(InscricaoSerializer(inscricao, context={"request": self.request}).data)


class RepassarVagaView(_AcaoNaInscricaoView):
    """Libera a vaga paga para a lista de espera (a menos de 24h do jogo)."""

    def post(self, request: Request, pk: str) -> Response:
        inscricao = self.inscricao()
        checkout.repassar_vaga(inscricao)
        return self.responder(inscricao)


class SimularPagamentoView(_AcaoNaInscricaoView):
    """Aprova o Pix pendente (apenas com o gateway simulado de desenvolvimento)."""

    def post(self, request: Request, pk: str) -> Response:
        inscricao = self.inscricao()
        checkout.simular_pagamento(inscricao)
        return self.responder(inscricao)


class ListaDeEsperaView(APIView):
    """Entra (POST) ou sai (DELETE) da lista de espera de uma partida."""

    permission_classes = (IsAuthenticated, IsJogador)

    def post(self, request: Request, pk: str) -> Response:
        partida = get_object_or_404(OpenMatch, pk=pk)
        checkout.entrar_na_lista_de_espera(partida, request.user, request.data.get("posicao", "linha"))
        return Response({"na_lista_de_espera": True}, status=status.HTTP_201_CREATED)

    def delete(self, request: Request, pk: str) -> Response:
        checkout.sair_da_lista_de_espera(get_object_or_404(OpenMatch, pk=pk), request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CarteiraView(APIView):
    """Crédito ArenaMatch do jogador (recebido em cancelamentos) e últimas movimentações."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, format: str | None = None) -> Response:
        return Response(
            {
                "saldo": str(razao.saldo_do_jogador(request.user)),
                "movimentacoes": LancamentoSerializer(
                    razao.extrato_do_jogador(request.user)[:20], many=True
                ).data,
            }
        )


class ArenaListView(generics.ListAPIView):
    """Arenas parceiras e suas quadras."""

    serializer_class = ArenaSerializer
    permission_classes = (AllowAny,)
    queryset = Arena.objects.prefetch_related("quadras").order_by("nome")


class CadastroJogadorView(generics.CreateAPIView):
    """Cria uma conta de jogador e devolve o token de autenticação."""

    serializer_class = CadastroJogadorSerializer
    permission_classes = (AllowAny,)


class PerfilView(generics.RetrieveAPIView):
    """Dados do usuário autenticado."""

    serializer_class = PerfilSerializer
    permission_classes = (IsAuthenticated,)

    def get_object(self) -> CustomUser:
        return self.request.user


class PerfilJogadorView(APIView):
    """Perfil esportivo do jogador: GET consulta; PUT cria ou atualiza (com o questionário)."""

    permission_classes = (IsAuthenticated, IsJogador)

    def get(self, request: Request, format: str | None = None) -> Response:
        perfil = jogadores.perfil_do(request.user)
        if perfil is None:
            return Response({"detail": "Perfil ainda não criado."}, status=status.HTTP_404_NOT_FOUND)
        return Response(PerfilJogadorSerializer(perfil).data)

    def put(self, request: Request, format: str | None = None) -> Response:
        serializer = PerfilJogadorSerializer(jogadores.perfil_do(request.user), data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data
        nivel = None
        if "autoavaliacao" in dados:
            nivel = jogadores.calcular_nivel(dados["autoavaliacao"], dados["frequencia"], dados["experiencia"])
        perfil = jogadores.salvar_perfil(
            request.user,
            posicao=dados["posicao"],
            joga_no_gol=dados.get("joga_no_gol", False),
            apelido=dados.get("apelido", ""),
            regiao=dados.get("regiao", ""),
            nivel_declarado=nivel,
        )
        return Response(PerfilJogadorSerializer(perfil).data)
