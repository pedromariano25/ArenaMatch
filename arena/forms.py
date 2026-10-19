"""Formulários do painel B2B (admin) e da vitrine web B2C."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.db.models import QuerySet
from django.utils import timezone

from .jogadores import EXPERIENCIAS, FREQUENCIAS, calcular_nivel
from .models import (
    MEIA_NOITE,
    TAXA_C2C_MINIMA,
    TAXA_C2C_PERCENTUAL,
    Arena,
    Court,
    CustomUser,
    MetodoPagamento,
    NivelCompetitividade,
    OpenMatch,
    PercepcaoNivel,
    Posicao,
    PosicaoJogador,
    TipoChavePix,
    TipoPiso,
    Wallet,
)
from .validators import validar_cpf


class ConverterPartidaForm(forms.Form):
    """Parâmetros da action que converte horários livres em partidas abertas."""

    valor_total_aluguel = forms.DecimalField(
        label="Valor total do aluguel (R$)",
        min_value=Decimal("0.01"),
        max_digits=10,
        decimal_places=2,
        initial=Decimal("200.00"),
        localize=True,
        help_text="Quanto a quadra recebe com todas as vagas vendidas. O preço da vaga é calculado.",
    )
    nivel_competitividade = forms.ChoiceField(
        label="Nível",
        choices=NivelCompetitividade.choices,
        initial=NivelCompetitividade.ABERTA,
    )
    vagas_totais = forms.IntegerField(
        label="Vagas por partida",
        min_value=1,
        max_value=32767,
        required=False,
        help_text="Deixe em branco para usar a capacidade padrão de cada quadra.",
    )
    vagas_goleiro = forms.IntegerField(
        label="Vagas de goleiro",
        min_value=0,
        max_value=32767,
        required=False,
        help_text="Goleiros não pagam. Em branco: 2 a partir de 8 jogadores.",
    )


class CadastroJogadorForm(UserCreationForm):
    """Cadastro público de jogadores pela vitrine."""

    first_name = forms.CharField(label="Nome", max_length=150)
    last_name = forms.CharField(label="Sobrenome", max_length=150, required=False)
    email = forms.EmailField(label="E-mail")

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ("first_name", "last_name", "username", "email", "telefone")

    def clean_email(self) -> str:
        """Impede dois cadastros com o mesmo e-mail (sem diferenciar maiúsculas)."""
        email = self.cleaned_data["email"].strip().lower()
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Já existe uma conta com este e-mail.")
        return email

    def save(self, commit: bool = True) -> CustomUser:
        """Cria o usuário já marcado como jogador."""
        usuario = super().save(commit=False)
        usuario.is_player = True
        if commit:
            usuario.save()
        return usuario


class FiltroVitrineForm(forms.Form):
    """Filtros (via GET) do feed de partidas abertas."""

    dia = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Qualquer dia"),
            ("hoje", "Hoje"),
            ("amanha", "Amanhã"),
            ("fim_de_semana", "Fim de semana"),
            ("semana", "Próximos 7 dias"),
        ],
    )
    nivel = forms.ChoiceField(
        required=False, choices=[("", "Todos os níveis"), *NivelCompetitividade.choices]
    )
    piso = forms.ChoiceField(required=False, choices=[("", "Todos os pisos"), *TipoPiso.choices])
    arena = forms.ChoiceField(required=False)
    origem = forms.ChoiceField(
        required=False,
        choices=[("", "Todas"), ("arena", "Arenas parceiras"), ("pelada", "Peladas de grupo")],
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["arena"].choices = [
            ("", "Todas as arenas"),
            *Arena.objects.order_by("nome").values_list("slug", "nome"),
        ]

    @property
    def ativo(self) -> bool:
        """Indica se algum filtro foi aplicado."""
        return self.is_valid() and any(self.cleaned_data.values())

    def filtros(self) -> dict[str, Any]:
        """Converte os dados válidos em argumentos de ``OpenMatchQuerySet.filtrar()``."""
        if not self.is_valid():
            return {}
        dados = self.cleaned_data
        hoje = timezone.localdate()
        sabado = hoje + timedelta(days=(5 - hoje.weekday()) % 7)
        if hoje.weekday() == 6:
            sabado = hoje - timedelta(days=1)  # domingo: o fim de semana é hoje
        intervalos = {
            "hoje": (hoje, hoje),
            "amanha": (hoje + timedelta(days=1), hoje + timedelta(days=1)),
            "fim_de_semana": (max(sabado, hoje), sabado + timedelta(days=1)),
            "semana": (hoje, hoje + timedelta(days=6)),
        }
        de, ate = intervalos.get(dados["dia"], (None, None))
        return {
            "nivel": dados["nivel"] or None,
            "piso": dados["piso"] or None,
            "arena": dados["arena"] or None,
            "origem": dados["origem"] or None,
            "de": de,
            "ate": ate,
        }


# --- Portal do Gestor (ArenaManager) -----------------------------------------


class AbrirPartidaForm(forms.Form):
    """Botão "Transformar em Partida Aberta" da agenda do gestor.

    O gestor informa só o aluguel e as vagas; o nível é opcional (padrão: Misto).
    """

    quadra = forms.ModelChoiceField(queryset=Court.objects.none())
    dia = forms.DateField()
    hora_inicio = forms.TimeField()
    hora_fim = forms.TimeField()
    valor_total_aluguel = forms.DecimalField(
        label="Valor do aluguel (R$)",
        min_value=Decimal("0.01"),
        max_digits=10,
        decimal_places=2,
        localize=True,
    )
    vagas_totais = forms.IntegerField(label="Vagas", min_value=1, max_value=32767, required=False)
    vagas_goleiro = forms.IntegerField(label="Goleiros", min_value=0, max_value=32767, required=False)
    nivel_competitividade = forms.ChoiceField(
        label="Nível", choices=NivelCompetitividade.choices, required=False
    )

    def __init__(self, *args: Any, quadras: QuerySet[Court], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["quadra"].queryset = quadras

    def clean_nivel_competitividade(self) -> str:
        return self.cleaned_data["nivel_competitividade"] or NivelCompetitividade.ABERTA


class ArenaConfigForm(forms.ModelForm):
    """Dados da arena editáveis pelo gestor (CNPJ e responsável ficam de fora)."""

    class Meta:
        model = Arena
        fields = (
            "nome",
            "telefone_contato",
            "endereco_completo",
            "hora_abertura",
            "hora_fechamento",
            "quorum_percentual",
            "horas_prazo_quorum",
            "latitude",
            "longitude",
        )
        widgets = {
            "hora_abertura": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "hora_fechamento": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }


class QuadraForm(forms.ModelForm):
    """Cadastro de quadra no portal do gestor (a arena vem da instância)."""

    class Meta:
        model = Court
        fields = ("nome_ou_numero", "tipo_piso", "capacidade_padrao")

    def clean_nome_ou_numero(self) -> str:
        """Impede duas quadras com o mesmo nome na arena.

        A constraint do modelo inclui ``arena``, que não é campo do formulário;
        sem esta checagem, o ModelForm pularia a validação de unicidade.
        """
        nome = self.cleaned_data["nome_ou_numero"].strip()
        repetida = (
            Court.objects.filter(arena_id=self.instance.arena_id, nome_ou_numero__iexact=nome)
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if repetida:
            raise forms.ValidationError("Já existe uma quadra com este nome nesta arena.")
        return nome


# --- Checkout (vitrine) --------------------------------------------------------


class CheckoutForm(forms.Form):
    """Escolha da vaga (linha ou goleiro) e da forma de pagamento."""

    posicao = forms.ChoiceField(
        label="Vaga", choices=Posicao.choices, initial=Posicao.LINHA, widget=forms.RadioSelect
    )
    metodo = forms.ChoiceField(
        label="Pagamento",
        choices=[
            (MetodoPagamento.PIX, "Pix"),
            (MetodoPagamento.CARTAO, "Cartão de crédito"),
            (MetodoPagamento.CREDITO, "Crédito ArenaMatch"),
        ],
        initial=MetodoPagamento.PIX,
        required=False,
        widget=forms.RadioSelect,
    )

    def __init__(
        self,
        *args: Any,
        partida: OpenMatch,
        saldo: Decimal,
        posicoes: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.partida = partida
        posicoes = posicoes or [Posicao.LINHA, Posicao.GOLEIRO]
        if not partida.vagas_goleiro:
            posicoes = [posicao for posicao in posicoes if posicao != Posicao.GOLEIRO]
        self.fields["posicao"].choices = [(p, Posicao(p).label) for p in posicoes]
        self.fields["posicao"].initial = posicoes[0] if posicoes else Posicao.LINHA
        if saldo < partida.preco_final_jogador:
            self.fields["metodo"].choices = [
                opcao for opcao in self.fields["metodo"].choices if opcao[0] != MetodoPagamento.CREDITO
            ]

    def clean(self) -> dict[str, Any]:
        dados = super().clean()
        if dados.get("posicao") == Posicao.GOLEIRO and self.partida.goleiro_gratis:
            dados["metodo"] = MetodoPagamento.GRATUITO
        elif not dados.get("metodo"):
            self.add_error("metodo", "Escolha a forma de pagamento.")
        return dados


# --- Perfil do jogador e avaliação pós-jogo ---------------------------------------


class PerfilJogadorForm(forms.Form):
    """Questionário do perfil: posição, disposição para o gol e nível (1 a 5)."""

    apelido = forms.CharField(label="Apelido", max_length=30, required=False)
    posicao = forms.ChoiceField(label="Posição", choices=PosicaoJogador.choices, widget=forms.RadioSelect)
    joga_no_gol = forms.BooleanField(label="Também topo jogar no gol (a vaga de goleiro é grátis)", required=False)
    regiao = forms.CharField(label="Bairro ou região", max_length=80, required=False)
    autoavaliacao = forms.TypedChoiceField(
        label="Como você se avalia?",
        coerce=int,
        widget=forms.RadioSelect,
        choices=[
            (1, "Estou começando ou voltando a jogar"),
            (2, "Jogo por diversão, sem muita técnica"),
            (3, "Jogo bem, tenho bom fundamento"),
            (4, "Jogo muito bem, decido partidas"),
            (5, "Jogo em alto nível"),
        ],
    )
    frequencia = forms.ChoiceField(
        label="Com que frequência você joga?",
        choices=[(codigo, rotulo) for codigo, rotulo, _ in FREQUENCIAS],
        widget=forms.RadioSelect,
    )
    experiencia = forms.ChoiceField(
        label="Qual é a sua experiência?",
        choices=[(codigo, rotulo) for codigo, rotulo, _ in EXPERIENCIAS],
        widget=forms.RadioSelect,
    )

    QUESTIONARIO = ("autoavaliacao", "frequencia", "experiencia")

    def __init__(self, *args: Any, nivel_travado: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if nivel_travado:
            # Nível ajustado pela comunidade: o jogador não o redefine sozinho.
            for campo in self.QUESTIONARIO:
                del self.fields[campo]

    def nivel_declarado(self) -> int | None:
        if "autoavaliacao" not in self.cleaned_data:
            return None
        return calcular_nivel(
            self.cleaned_data["autoavaliacao"], self.cleaned_data["frequencia"], self.cleaned_data["experiencia"]
        )


class AvaliacaoPartidaForm(forms.Form):
    """Percepção do nível do jogo; elogios e sinais vêm de campos por colega."""

    percepcao = forms.ChoiceField(
        label="Como foi o nível do jogo?", choices=PercepcaoNivel.choices, widget=forms.RadioSelect
    )


# --- Login por celular -----------------------------------------------------------


class TelefoneForm(forms.Form):
    """Passo 1: o celular que recebe o código."""

    telefone = forms.CharField(
        label="Celular com DDD",
        max_length=20,
        widget=forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel", "placeholder": "(11) 91234-5678"}),
    )


class CodigoAcessoForm(forms.Form):
    """Passo 2: o código recebido (e o nome, se for o primeiro acesso)."""

    codigo = forms.CharField(
        label="Código de 6 dígitos",
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "placeholder": "000000"}),
    )
    nome = forms.CharField(
        label="Seu nome (no primeiro acesso)",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )


# --- Pelada de grupo (C2C) ----------------------------------------------------------


class QuadraParceiraField(forms.ModelChoiceField):
    def label_from_instance(self, quadra: Court) -> str:
        return f"{quadra.arena.nome} · {quadra.nome_ou_numero} ({quadra.get_tipo_piso_display()})"


class NovaPeladaForm(forms.Form):
    """O organizador abre as vagas que faltam na pelada do grupo."""

    titulo = forms.CharField(
        label="Nome da pelada",
        max_length=80,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Pelada da Firma"}),
    )
    quadra = QuadraParceiraField(
        label="Onde vocês jogam",
        queryset=Court.objects.select_related("arena").order_by("arena__nome", "nome_ou_numero"),
        empty_label="Escolha a arena e a quadra",
        help_text="Só arenas parceiras do ArenaMatch, por enquanto.",
    )
    dia = forms.DateField(label="Dia", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    hora_inicio = forms.TimeField(label="Começa", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    hora_fim = forms.TimeField(label="Termina", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    vagas_linha = forms.IntegerField(label="Vagas que faltam (linha)", min_value=1, max_value=20, initial=2)
    valor_por_vaga = forms.DecimalField(
        label="Você recebe por vaga (R$)",
        min_value=Decimal("1.00"),
        max_value=Decimal("500.00"),
        max_digits=6,
        decimal_places=2,
        initial=Decimal("15.00"),
        localize=True,
    )
    vagas_goleiro = forms.IntegerField(label="Vagas de goleiro", min_value=0, max_value=2, initial=0)
    valor_goleiro = forms.DecimalField(
        label="Você recebe por goleiro (R$)",
        min_value=Decimal("0"),
        max_value=Decimal("500.00"),
        max_digits=6,
        decimal_places=2,
        initial=Decimal("0"),
        localize=True,
        help_text="Zero: o goleiro joga de graça (o grupo banca).",
    )
    nivel = forms.ChoiceField(
        label="Nível do jogo", choices=NivelCompetitividade.choices, initial=NivelCompetitividade.ABERTA
    )

    def clean(self) -> dict[str, Any]:
        dados = super().clean()
        inicio, fim = dados.get("hora_inicio"), dados.get("hora_fim")
        if inicio and fim and fim <= inicio and fim != MEIA_NOITE:
            self.add_error("hora_fim", "O horário de término precisa ser depois do início.")
        return dados

    @staticmethod
    def taxas() -> dict[str, Decimal]:
        """Contrato da pelada de grupo, para a prévia do preço na tela."""
        return {"percentual": TAXA_C2C_PERCENTUAL, "minima": TAXA_C2C_MINIMA}


class ChavePixForm(forms.ModelForm):
    """Chave Pix que recebe os saques do organizador."""

    class Meta:
        model = Wallet
        fields = ("tipo_chave_pix", "chave_pix")
        labels = {"tipo_chave_pix": "Tipo da chave", "chave_pix": "Chave Pix"}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["tipo_chave_pix"].required = True
        self.fields["chave_pix"].required = True

    def clean(self) -> dict[str, Any]:
        dados = super().clean()
        tipo, chave = dados.get("tipo_chave_pix"), (dados.get("chave_pix") or "").strip()
        if not tipo or not chave:
            return dados
        digitos = "".join(filter(str.isdigit, chave))
        if tipo == TipoChavePix.CPF:
            try:
                validar_cpf(digitos)
            except forms.ValidationError as erro:
                self.add_error("chave_pix", erro)
            chave = digitos
        elif tipo == TipoChavePix.CELULAR:
            if len(digitos.removeprefix("55")) not in (10, 11):
                self.add_error("chave_pix", "Informe o celular com DDD.")
            chave = "+55" + digitos.removeprefix("55")
        elif tipo == TipoChavePix.EMAIL:
            try:
                forms.EmailField().clean(chave)
            except forms.ValidationError:
                self.add_error("chave_pix", "Informe um e-mail válido.")
            chave = chave.lower()
        elif len(chave.replace("-", "")) != 32:
            self.add_error("chave_pix", "A chave aleatória tem 32 caracteres (letras e números).")
        dados["chave_pix"] = chave
        return dados
