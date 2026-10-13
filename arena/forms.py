"""Formulários do painel B2B (admin) e da vitrine web B2C."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from .models import Arena, CustomUser, NivelCompetitividade, TipoPiso


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
