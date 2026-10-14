"""Rotas da vitrine web B2C."""

from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "arena"

urlpatterns = [
    path("", views.VitrineView.as_view(), name="vitrine"),
    path("partidas/<uuid:pk>/", views.PartidaDetalheView.as_view(), name="partida_detalhe"),
    path("partidas/<uuid:pk>/checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("partidas/<uuid:pk>/lista-de-espera/", views.ListaDeEsperaView.as_view(), name="lista_de_espera"),
    path("inscricoes/<uuid:pk>/", views.InscricaoView.as_view(), name="inscricao"),
    path("inscricoes/<uuid:pk>/pagamento/", views.PagamentoView.as_view(), name="pagamento"),
    path(
        "inscricoes/<uuid:pk>/pagamento/simular/",
        views.SimularPagamentoView.as_view(),
        name="simular_pagamento",
    ),
    path(
        "inscricoes/<uuid:pk>/cancelar/",
        views.CancelarInscricaoView.as_view(),
        name="cancelar_inscricao",
    ),
    path("inscricoes/<uuid:pk>/repassar/", views.RepassarVagaView.as_view(), name="repassar_vaga"),
    path("minhas-inscricoes/", views.MinhasInscricoesView.as_view(), name="minhas_inscricoes"),
    path("partidas/<uuid:pk>/avaliar/", views.AvaliarPartidaView.as_view(), name="avaliar_partida"),
    path("perfil/", views.PerfilView.as_view(), name="perfil"),
    path("perfil/configurar/", views.ConfigurarPerfilView.as_view(), name="configurar_perfil"),
    path("entrar/", views.EntrarView.as_view(), name="entrar"),
    path("sair/", LogoutView.as_view(), name="sair"),
    path("cadastro/", views.CadastroView.as_view(), name="cadastro"),
]
