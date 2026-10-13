"""Rotas da vitrine web B2C."""

from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "arena"

urlpatterns = [
    path("", views.VitrineView.as_view(), name="vitrine"),
    path("partidas/<uuid:pk>/", views.PartidaDetalheView.as_view(), name="partida_detalhe"),
    path("partidas/<uuid:pk>/reservar/", views.ReservarVagaView.as_view(), name="reservar"),
    path("inscricoes/<uuid:pk>/", views.InscricaoView.as_view(), name="inscricao"),
    path(
        "inscricoes/<uuid:pk>/cancelar/",
        views.CancelarInscricaoView.as_view(),
        name="cancelar_inscricao",
    ),
    path("minhas-inscricoes/", views.MinhasInscricoesView.as_view(), name="minhas_inscricoes"),
    path("entrar/", views.EntrarView.as_view(), name="entrar"),
    path("sair/", LogoutView.as_view(), name="sair"),
    path("cadastro/", views.CadastroView.as_view(), name="cadastro"),
]
