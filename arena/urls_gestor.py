"""Rotas do Portal do Gestor (ArenaManager), montadas em ``/manager/``."""

from django.contrib.auth.views import LogoutView
from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "gestor"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="gestor:dashboard"), name="inicio"),
    path("login/", views.GestorLoginView.as_view(), name="login"),
    path("sair/", LogoutView.as_view(next_page="gestor:login"), name="sair"),
    path("dashboard/", views.GestorDashboardView.as_view(), name="dashboard"),
    path("abrir-quadra/", views.GestorAbrirQuadraView.as_view(), name="abrir_quadra"),
    path("agenda/", views.GestorAgendaView.as_view(), name="agenda"),
    path("agenda/abrir-partida/", views.GestorAbrirPartidaView.as_view(), name="abrir_partida"),
    path(
        "partidas/<uuid:pk>/cancelar/",
        views.GestorCancelarPartidaView.as_view(),
        name="cancelar_partida",
    ),
    path("check-in/", views.GestorCheckInView.as_view(), name="check_in"),
    path("check-in/<uuid:pk>/", views.GestorCheckInInscricaoView.as_view(), name="check_in_inscricao"),
    path("financeiro/", views.GestorFinanceiroView.as_view(), name="financeiro"),
    path("configuracoes/", views.GestorConfiguracoesView.as_view(), name="configuracoes"),
]
