"""Rotas da API B2C (montadas em ``/api/``)."""

from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from . import views

app_name = "api"

urlpatterns = [
    path("", views.ApiRaizView.as_view(), name="raiz"),
    path("partidas/", views.PartidaListView.as_view(), name="partidas"),
    path("partidas/<uuid:pk>/", views.PartidaDetailView.as_view(), name="partida"),
    path("partidas/<uuid:pk>/inscricoes/", views.InscricaoCreateView.as_view(), name="inscrever"),
    path("arenas/", views.ArenaListView.as_view(), name="arenas"),
    path("minhas-inscricoes/", views.MinhasInscricoesListView.as_view(), name="minhas_inscricoes"),
    path("minhas-inscricoes/<uuid:pk>/", views.InscricaoDetailView.as_view(), name="inscricao"),
    path("auth/cadastro/", views.CadastroJogadorView.as_view(), name="cadastro"),
    path("auth/token/", obtain_auth_token, name="token"),
    path("me/", views.PerfilView.as_view(), name="perfil"),
]
