"""Endpoints REST da frente B2C (app mobile e vitrine web)."""

from datetime import date

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from ..models import Arena, Booking, CustomUser, OpenMatch
from .permissions import IsJogador
from .serializers import (
    ArenaSerializer,
    CadastroJogadorSerializer,
    InscricaoSerializer,
    PartidaDetalheSerializer,
    PartidaSerializer,
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
        rotas = ("partidas", "arenas", "minhas_inscricoes", "perfil", "cadastro", "token")
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
    """Inscreve o jogador autenticado na partida (pagamento fica Pendente).

    As regras de negócio (partida lotada, já iniciada, inscrição duplicada...)
    retornam HTTP 400 com a mensagem correspondente.
    """

    serializer_class = InscricaoSerializer
    permission_classes = (IsAuthenticated, IsJogador)

    def perform_create(self, serializer: BaseSerializer) -> None:
        partida = get_object_or_404(OpenMatch, pk=self.kwargs["pk"])
        serializer.save(open_match=partida, player=self.request.user)


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

    Só inscrições pendentes, antes do início da partida, podem ser canceladas.
    """

    serializer_class = InscricaoSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self) -> QuerySet:
        return Booking.objects.filter(player=self.request.user).select_related(
            "open_match__time_slot__court__arena"
        )

    def perform_destroy(self, instance: Booking) -> None:
        instance.cancelar()


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
