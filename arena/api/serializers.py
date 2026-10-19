"""Serializers da API B2C (app mobile e vitrine web)."""

from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.authtoken.models import Token

from ..jogadores import EXPERIENCIAS, FREQUENCIAS

from ..models import (
    Arena,
    Booking,
    Court,
    CustomUser,
    LedgerEntry,
    MetodoPagamento,
    OpenMatch,
    Payment,
    PlayerProfile,
    Posicao,
    StatusPagamento,
)


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
    vagas_linha = serializers.IntegerField(read_only=True)
    precos = serializers.SerializerMethodField(
        help_text="Preço da vaga de linha e da de goleiro, no Pix (ou crédito) e no cartão (0.00 = grátis)."
    )
    origem = serializers.SerializerMethodField(help_text='"arena" (arena parceira) ou "pelada" (pelada de grupo).')
    organizador = serializers.SerializerMethodField(help_text="Nome público do organizador (só na pelada de grupo).")
    minimo_jogadores = serializers.IntegerField(read_only=True)
    jogadores_confirmados = serializers.IntegerField(read_only=True)
    jogo_confirmado = serializers.BooleanField(read_only=True)
    aceita_inscricoes = serializers.BooleanField(read_only=True)

    class Meta:
        model = OpenMatch
        fields = (
            "id",
            "url",
            "origem",
            "titulo",
            "organizador",
            "arena",
            "quadra",
            "data",
            "hora_inicio",
            "hora_fim",
            "nivel_competitividade",
            "nivel_display",
            "vagas_totais",
            "vagas_linha",
            "vagas_goleiro",
            "vagas_disponiveis",
            "vagas_ocupadas",
            "precos",
            "minimo_jogadores",
            "jogadores_confirmados",
            "jogo_confirmado",
            "status",
            "status_display",
            "aceita_inscricoes",
        )
        read_only_fields = (
            "nivel_competitividade",
            "vagas_totais",
            "vagas_goleiro",
            "vagas_disponiveis",
            "status",
        )

    def get_precos(self, partida: OpenMatch) -> dict[str, str]:
        return {
            "linha_pix": str(partida.preco_final_jogador),
            "linha_cartao": str(partida.preco_cartao),
            "goleiro": str(partida.preco_goleiro),
            "goleiro_cartao": str(partida.preco_goleiro_cartao),
        }

    def get_origem(self, partida: OpenMatch) -> str:
        return "pelada" if partida.pelada_de_grupo else "arena"

    def get_organizador(self, partida: OpenMatch) -> str | None:
        return partida.organizador.nome_publico if partida.pelada_de_grupo else None


class PartidaDetalheSerializer(PartidaSerializer):
    """Partida com a lista pública de jogadores inscritos."""

    jogadores = serializers.SerializerMethodField(
        help_text="Nome público (primeiro nome e inicial) dos inscritos, por ordem de inscrição."
    )

    class Meta(PartidaSerializer.Meta):
        fields = (*PartidaSerializer.Meta.fields, "jogadores")

    def get_jogadores(self, partida: OpenMatch) -> list[str]:
        inscricoes = partida.inscricoes.confirmadas().select_related("player").order_by("confirmada_em")
        return [inscricao.player.nome_publico for inscricao in inscricoes]


class PagamentoSerializer(serializers.ModelSerializer):
    """Cobrança da inscrição (o código Pix aparece enquanto o pagamento está pendente)."""

    class Meta:
        model = Payment
        fields = ("id", "metodo", "status", "valor", "pix_copia_e_cola", "expira_em", "aprovado_em")
        read_only_fields = fields


class InscricaoSerializer(serializers.ModelSerializer):
    """Inscrição do jogador autenticado. Status, valores e prazos vêm do checkout."""

    partida = PartidaSerializer(source="open_match", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    valor_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    pagamento = serializers.SerializerMethodField()
    pode_cancelar = serializers.BooleanField(read_only=True)
    pode_repassar = serializers.BooleanField(read_only=True)
    em_repasse = serializers.BooleanField(read_only=True)
    posicao = serializers.ChoiceField(choices=Posicao.choices, default=Posicao.LINHA)
    metodo_pagamento = serializers.ChoiceField(
        choices=[MetodoPagamento.PIX, MetodoPagamento.CARTAO, MetodoPagamento.CREDITO],
        default=MetodoPagamento.PIX,
        help_text="Ignorado na vaga de goleiro grátis.",
    )

    class Meta:
        model = Booking
        fields = (
            "id",
            "partida",
            "posicao",
            "metodo_pagamento",
            "status",
            "status_display",
            "valor_vaga",
            "valor_taxa",
            "valor_acrescimo",
            "valor_total",
            "reservada_ate",
            "data_inscricao",
            "confirmada_em",
            "pagamento",
            "pode_cancelar",
            "pode_repassar",
            "em_repasse",
        )
        read_only_fields = (
            "status",
            "valor_vaga",
            "valor_taxa",
            "valor_acrescimo",
            "reservada_ate",
            "data_inscricao",
            "confirmada_em",
        )

    def get_pagamento(self, inscricao: Booking) -> dict | None:
        pagamento = inscricao.pagamentos.exclude(status=StatusPagamento.CANCELADO).first()
        return PagamentoSerializer(pagamento).data if pagamento else None


class LancamentoSerializer(serializers.ModelSerializer):
    """Movimentação da carteira de crédito do jogador."""

    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = LedgerEntry
        fields = ("id", "tipo", "tipo_display", "valor", "descricao", "created_at")
        read_only_fields = fields


class PerfilJogadorSerializer(serializers.ModelSerializer):
    """Perfil esportivo. Envie o questionário para (re)calcular o nível declarado."""

    nivel_display = serializers.CharField(source="get_nivel_display", read_only=True)
    autoavaliacao = serializers.IntegerField(min_value=1, max_value=5, write_only=True, required=False)
    frequencia = serializers.ChoiceField(choices=[c for c, _, _ in FREQUENCIAS], write_only=True, required=False)
    experiencia = serializers.ChoiceField(choices=[c for c, _, _ in EXPERIENCIAS], write_only=True, required=False)

    class Meta:
        model = PlayerProfile
        fields = (
            "apelido",
            "posicao",
            "joga_no_gol",
            "regiao",
            "nivel",
            "nivel_display",
            "nivel_origem",
            "goleiro_suspenso_ate",
            "autoavaliacao",
            "frequencia",
            "experiencia",
        )
        read_only_fields = ("nivel", "nivel_origem", "goleiro_suspenso_ate")

    def validate(self, dados: dict[str, Any]) -> dict[str, Any]:
        questionario = [campo for campo in ("autoavaliacao", "frequencia", "experiencia") if campo in dados]
        if questionario and len(questionario) != 3:
            raise serializers.ValidationError("Envie as três respostas do questionário juntas.")
        if self.instance is None and not questionario:
            raise serializers.ValidationError("Responda o questionário para definir o seu nível.")
        return dados


class PerfilSerializer(serializers.ModelSerializer):
    """Dados do usuário autenticado."""

    perfil = PerfilJogadorSerializer(read_only=True)

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
            "perfil",
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
