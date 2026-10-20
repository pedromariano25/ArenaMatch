"""Endpoints REST da frente B2C (app mobile e vitrine web)."""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from .. import acesso, checkout, jogadores, peladas, razao
from ..forms import ChavePixForm
from ..models import VALOR_MINIMO_SAQUE, Arena, Booking, CustomUser, OpenMatch
from .permissions import IsJogador
from .serializers import (
    ArenaSerializer,
    CadastroJogadorSerializer,
    InscricaoSerializer,
    LancamentoSerializer,
    NovaPeladaSerializer,
    PartidaDetalheSerializer,
    PartidaSerializer,
    PeladaDoOrganizadorSerializer,
    PerfilJogadorSerializer,
    PerfilSerializer,
    SaqueSerializer,
    SolicitarCodigoSerializer,
    VerificarCodigoSerializer,
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


def _reais(valor: Decimal) -> str:
    """Valor em reais com duas casas, como nos demais campos de dinheiro da API."""
    return f"{valor:.2f}"


class ApiRaizView(APIView):
    """Índice navegável da API do ArenaMatch."""

    permission_classes = (AllowAny,)

    def get(self, request: Request, format: str | None = None) -> Response:
        rotas = (
            "partidas",
            "arenas",
            "minhas_inscricoes",
            "carteira",
            "minhas_peladas",
            "carteira_organizador",
            "perfil",
            "solicitar_codigo",
            "cadastro",
            "token",
        )
        return Response(
            {rota: reverse(f"api:{rota}", request=request, format=format) for rota in rotas}
        )


class PartidaListView(generics.ListAPIView):
    """Feed de partidas abertas que ainda não começaram (Aberta ou Lotada).

    Filtros opcionais: ``nivel``, ``piso``, ``arena`` (slug), ``origem``
    (``arena`` ou ``pelada``), ``data``, ``de`` e ``ate`` (datas no formato AAAA-MM-DD).
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
            origem=params.get("origem"),
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


# --- Login pelo celular (sem senha) ---------------------------------------------


class SolicitarCodigoView(APIView):
    """Login pelo celular, passo 1: envia um código de 6 dígitos por SMS.

    Em desenvolvimento (``DEBUG`` com o SMS simulado), a resposta traz o ``codigo``.
    """

    permission_classes = (AllowAny,)

    def post(self, request: Request, format: str | None = None) -> Response:
        serializer = SolicitarCodigoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        telefone = serializer.validated_data["telefone"]
        try:
            codigo = acesso.solicitar_codigo(telefone)
        except DjangoValidationError as erro:
            raise ValidationError({"telefone": erro.messages}) from erro
        resposta = {"telefone": acesso.formatar_telefone(acesso.normalizar_telefone(telefone))}
        if settings.DEBUG and acesso.obter_sms().simulado:
            resposta["codigo"] = codigo
        return Response(resposta, status=status.HTTP_202_ACCEPTED)


class VerificarCodigoView(APIView):
    """Login pelo celular, passo 2: confere o código e devolve o token.

    No primeiro acesso, cria a conta de jogador com o ``nome`` enviado.
    ``precisa_de_perfil`` indica que o app deve abrir o questionário de nível.
    """

    permission_classes = (AllowAny,)

    def post(self, request: Request, format: str | None = None) -> Response:
        serializer = VerificarCodigoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data
        try:
            usuario = acesso.validar_codigo(dados["telefone"], dados["codigo"], dados["nome"])
        except DjangoValidationError as erro:
            raise ValidationError({"codigo": erro.messages}) from erro
        token, _ = Token.objects.get_or_create(user=usuario)
        return Response(
            {
                "token": token.key,
                "usuario": PerfilSerializer(usuario).data,
                "precisa_de_perfil": usuario.is_player and jogadores.perfil_do(usuario) is None,
            }
        )


# --- Pelada de grupo (C2C) e carteira do organizador ----------------------------


class MinhasPeladasView(generics.ListCreateAPIView):
    """Peladas de grupo que o jogador organiza (GET) e publicação de vagas (POST).

    No POST, só ``quadra``, ``dia``, ``hora_inicio``, ``vagas_linha`` e
    ``valor_por_vaga`` são obrigatórios. O horário precisa ser o de mensalista do
    grupo na quadra (ou estar livre). Regras de negócio retornam HTTP 400.
    """

    permission_classes = (IsAuthenticated, IsJogador)

    def get_queryset(self) -> QuerySet:
        return peladas.peladas_do(self.request.user)

    def get_serializer_class(self) -> type[BaseSerializer]:
        return NovaPeladaSerializer if self.request.method == "POST" else PeladaDoOrganizadorSerializer

    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        entrada = NovaPeladaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data
        pelada = peladas.criar_pelada(
            request.user,
            dados["quadra"],
            dados["dia"],
            dados["hora_inicio"],
            dados["hora_fim"],
            titulo=dados["titulo"] or peladas.titulo_padrao(request.user),
            vagas_linha=dados["vagas_linha"],
            valor_por_vaga=dados["valor_por_vaga"],
            vagas_goleiro=dados["vagas_goleiro"],
            valor_goleiro=dados["valor_goleiro"],
            nivel=dados["nivel"],
        )
        pelada = self.get_queryset().get(pk=pelada.pk)
        saida = PeladaDoOrganizadorSerializer(pelada, context=self.get_serializer_context())
        return Response(saida.data, status=status.HTTP_201_CREATED)


class CancelarPeladaView(APIView):
    """O organizador desiste das vagas: quem comprou recebe o dinheiro de volta."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: str) -> Response:
        pelada = get_object_or_404(OpenMatch, pk=pk, organizador=request.user)
        return Response({"reembolsados": peladas.cancelar_pelada(pelada, request.user)})


class CarteiraOrganizadorView(APIView):
    """Saldo das vagas vendidas nas peladas, chave Pix, últimos saques e movimentações.

    O valor de cada vaga libera no dia seguinte ao jogo (``a_liberar`` vira ``disponivel``).
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, format: str | None = None) -> Response:
        wallet = peladas.wallet_do(request.user)
        saldo = razao.saldo_do_organizador(request.user)
        return Response(
            {
                "disponivel": _reais(saldo.disponivel),
                "a_liberar": _reais(saldo.a_liberar),
                "sacado": _reais(saldo.sacado),
                "valor_minimo_saque": _reais(VALOR_MINIMO_SAQUE),
                "chave_pix": {"tipo": wallet.tipo_chave_pix, "chave": wallet.chave_pix} if wallet.pode_sacar else None,
                "saques": SaqueSerializer(wallet.saques.all()[:5], many=True).data,
                "movimentacoes": LancamentoSerializer(razao.extrato_do_organizador(request.user)[:20], many=True).data,
            }
        )


class ChavePixView(APIView):
    """Cadastra ou troca (PUT) a chave Pix que recebe os saques.

    Envie ``tipo_chave_pix`` (``cpf``, ``celular``, ``email`` ou ``aleatoria``) e ``chave_pix``.
    """

    permission_classes = (IsAuthenticated,)

    def put(self, request: Request, format: str | None = None) -> Response:
        form = ChavePixForm(request.data, instance=peladas.wallet_do(request.user))
        if not form.is_valid():
            raise ValidationError({campo: list(erros) for campo, erros in form.errors.items()})
        wallet = form.save()
        return Response({"tipo": wallet.tipo_chave_pix, "chave": wallet.chave_pix})


class SaqueView(APIView):
    """Saca via Pix todo o saldo disponível (HTTP 400 sem chave Pix ou abaixo do mínimo)."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, format: str | None = None) -> Response:
        saque = razao.solicitar_saque(request.user)
        return Response(SaqueSerializer(saque).data, status=status.HTTP_201_CREATED)
