"""Serializers da API B2C (app mobile e vitrine web)."""

from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.authtoken.models import Token

from ..models import STATUS_OCUPA_VAGA, Arena, Booking, Court, CustomUser, OpenMatch


class QuadraSerializer(serializers.ModelSerializer):
    """Quadra de uma arena."""

    tipo_piso_display = serializers.CharField(source="get_tipo_piso_display", read_only=True)

    class Meta:
        model = Court
        fields = ("id", "nome_ou_numero", "tipo_piso", "tipo_piso_display", "capacidade_padrao")


class ArenaResumoSerializer(serializers.ModelSerializer):
    """Dados públicos de uma arena, embutidos nas partidas."""

    class Meta:
        model = Arena
        fields = ("id", "nome", "slug", "endereco_completo", "telefone_contato")


class ArenaSerializer(ArenaResumoSerializer):
    """Arena com horário de funcionamento e quadras."""

    quadras = QuadraSerializer(many=True, read_only=True)

    class Meta(ArenaResumoSerializer.Meta):
        fields = (*ArenaResumoSerializer.Meta.fields, "hora_abertura", "hora_fechamento", "quadras")


class PartidaSerializer(serializers.ModelSerializer):
    """Partida aberta, achatada para consumo do frontend (horário, quadra e arena)."""

    url = serializers.HyperlinkedIdentityField(view_name="api:partida")
    arena = ArenaResumoSerializer(source="time_slot.court.arena", read_only=True)
    quadra = QuadraSerializer(source="time_slot.court", read_only=True)
    data = serializers.DateField(source="time_slot.data", read_only=True)
    hora_inicio = serializers.TimeField(source="time_slot.hora_inicio", format="%H:%M", read_only=True)
    hora_fim = serializers.TimeField(source="time_slot.hora_fim", format="%H:%M", read_only=True)
    nivel_display = serializers.CharField(source="get_nivel_competitividade_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    vagas_ocupadas = serializers.IntegerField(read_only=True)
    preco_final_jogador = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        read_only=True,
        help_text="Valor cobrado do jogador: parte da quadra + taxa de conveniência.",
    )
    aceita_inscricoes = serializers.BooleanField(read_only=True)

    class Meta:
        model = OpenMatch
        fields = (
            "id",
            "url",
            "arena",
            "quadra",
            "data",
            "hora_inicio",
            "hora_fim",
            "nivel_competitividade",
            "nivel_display",
            "vagas_totais",
            "vagas_disponiveis",
            "vagas_ocupadas",
            "preco_final_jogador",
            "status",
            "status_display",
            "aceita_inscricoes",
        )
        read_only_fields = (
            "nivel_competitividade",
            "vagas_totais",
            "vagas_disponiveis",
            "status",
        )


class PartidaDetalheSerializer(PartidaSerializer):
    """Partida com a lista pública de jogadores inscritos."""

    jogadores = serializers.SerializerMethodField(
        help_text="Nome público (primeiro nome e inicial) dos inscritos, por ordem de inscrição."
    )

    class Meta(PartidaSerializer.Meta):
        fields = (*PartidaSerializer.Meta.fields, "jogadores")

    def get_jogadores(self, partida: OpenMatch) -> list[str]:
        inscricoes = (
            partida.inscricoes.filter(status_pagamento__in=STATUS_OCUPA_VAGA)
            .select_related("player")
            .order_by("data_inscricao")
        )
        return [inscricao.player.nome_publico for inscricao in inscricoes]


class InscricaoSerializer(serializers.ModelSerializer):
    """Inscrição do jogador autenticado. Status e data são definidos pelo sistema."""

    partida = PartidaSerializer(source="open_match", read_only=True)
    status_pagamento_display = serializers.CharField(
        source="get_status_pagamento_display", read_only=True
    )
    pode_cancelar = serializers.BooleanField(read_only=True)

    class Meta:
        model = Booking
        fields = (
            "id",
            "partida",
            "status_pagamento",
            "status_pagamento_display",
            "data_inscricao",
            "pode_cancelar",
        )
        read_only_fields = ("status_pagamento", "data_inscricao")


class PerfilSerializer(serializers.ModelSerializer):
    """Dados do usuário autenticado."""

    class Meta:
        model = CustomUser
        fields = (
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "telefone",
            "is_player",
            "is_manager",
        )
        read_only_fields = fields


class CadastroJogadorSerializer(serializers.ModelSerializer):
    """Cadastro público de jogador; devolve o token de acesso para o app."""

    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    token = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = (
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "telefone",
            "password",
            "token",
        )
        extra_kwargs = {"first_name": {"required": True}, "email": {"required": True}}

    def validate_email(self, valor: str) -> str:
        email = valor.strip().lower()
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("Já existe uma conta com este e-mail.")
        return email

    def validate(self, dados: dict[str, Any]) -> dict[str, Any]:
        """Aplica os validadores de senha do Django (tamanho, senhas comuns, similaridade)."""
        candidato = CustomUser(**{campo: valor for campo, valor in dados.items() if campo != "password"})
        try:
            validate_password(dados["password"], user=candidato)
        except DjangoValidationError as erro:
            raise serializers.ValidationError({"password": list(erro.messages)}) from erro
        return dados

    def create(self, dados: dict[str, Any]) -> CustomUser:
        senha = dados.pop("password")
        usuario = CustomUser(**dados, is_player=True)
        usuario.set_password(senha)
        usuario.full_clean()
        usuario.save()
        return usuario

    def get_token(self, usuario: CustomUser) -> str:
        token, _ = Token.objects.get_or_create(user=usuario)
        return token.key
