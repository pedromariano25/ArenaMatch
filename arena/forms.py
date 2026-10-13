"""Formulários do painel B2B (admin) e da vitrine web B2C."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.db.models import QuerySet
from django.utils import timezone

from .models import Arena, Court, CustomUser, NivelCompetitividade, TipoPiso


class ConverterPartidaForm(forms.Form):
    """Parâmetros da action que converte horários livres em partidas abertas."""

    preco_por_vaga = forms.DecimalField(
        label="Preço por vaga (R$)",
        min_value=Decimal("0"),
        max_digits=8,
        decimal_places=2,
        initial=Decimal("25.00"),
        localize=True,
    )
    nivel_competitividade = forms.ChoiceField(
        label="Nível",
        choices=NivelCompetitividade.choices,
        initial=NivelCompetitividade.MISTO,
    )
    vagas_totais = forms.IntegerField(
        label="Vagas por partida",
        min_value=1,
        max_value=32767,
        required=False,
        help_text="Deixe em branco para usar a capacidade padrão de cada quadra.",
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
            ("semana", "Próximos 7 dias"),
        ],
    )
    nivel = forms.ChoiceField(
        required=False, choices=[("", "Todos os níveis"), *NivelCompetitividade.choices]
    )
    piso = forms.ChoiceField(required=False, choices=[("", "Todos os pisos"), *TipoPiso.choices])
    arena = forms.ChoiceField(required=False)

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
        intervalos = {
            "hoje": (hoje, hoje),
            "amanha": (hoje + timedelta(days=1), hoje + timedelta(days=1)),
            "semana": (hoje, hoje + timedelta(days=6)),
        }
        de, ate = intervalos.get(dados["dia"], (None, None))
        return {
            "nivel": dados["nivel"] or None,
            "piso": dados["piso"] or None,
            "arena": dados["arena"] or None,
            "de": de,
            "ate": ate,
        }


# --- Portal do Gestor (ArenaManager) -----------------------------------------


class AbrirPartidaForm(forms.Form):
    """Botão "Transformar em Partida Aberta" da agenda do gestor."""

    quadra = forms.ModelChoiceField(queryset=Court.objects.none())
    dia = forms.DateField()
    hora_inicio = forms.TimeField()
    hora_fim = forms.TimeField()
    preco_por_vaga = forms.DecimalField(
        label="Preço por vaga (R$)",
        min_value=Decimal("0"),
        max_digits=8,
        decimal_places=2,
        localize=True,
    )
    nivel_competitividade = forms.ChoiceField(
        label="Nível", choices=NivelCompetitividade.choices, initial=NivelCompetitividade.MISTO
    )
    vagas_totais = forms.IntegerField(label="Vagas", min_value=1, max_value=32767, required=False)

    def __init__(self, *args: Any, quadras: QuerySet[Court], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["quadra"].queryset = quadras


class ArenaConfigForm(forms.ModelForm):
    """Dados da arena editáveis pelo gestor (CNPJ e responsável ficam de fora)."""

    class Meta:
        model = Arena
        fields = ("nome", "telefone_contato", "endereco_completo", "hora_abertura", "hora_fechamento")
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
