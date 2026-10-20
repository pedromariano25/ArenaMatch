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
    path("partidas/<uuid:pk>/lista-de-espera/", views.ListaDeEsperaView.as_view(), name="lista_de_espera"),
    path("arenas/", views.ArenaListView.as_view(), name="arenas"),
    path("minhas-inscricoes/", views.MinhasInscricoesListView.as_view(), name="minhas_inscricoes"),
    path("minhas-inscricoes/<uuid:pk>/", views.InscricaoDetailView.as_view(), name="inscricao"),
    path("minhas-inscricoes/<uuid:pk>/repassar/", views.RepassarVagaView.as_view(), name="repassar"),
    path(
        "minhas-inscricoes/<uuid:pk>/simular-pagamento/",
        views.SimularPagamentoView.as_view(),
        name="simular_pagamento",
    ),
    path("carteira/", views.CarteiraView.as_view(), name="carteira"),
    path("peladas/", views.MinhasPeladasView.as_view(), name="minhas_peladas"),
    path("peladas/<uuid:pk>/cancelar/", views.CancelarPeladaView.as_view(), name="cancelar_pelada"),
    path("organizador/carteira/", views.CarteiraOrganizadorView.as_view(), name="carteira_organizador"),
    path("organizador/chave-pix/", views.ChavePixView.as_view(), name="chave_pix"),
    path("organizador/saques/", views.SaqueView.as_view(), name="saques"),
    path("auth/celular/", views.SolicitarCodigoView.as_view(), name="solicitar_codigo"),
    path("auth/celular/verificar/", views.VerificarCodigoView.as_view(), name="verificar_codigo"),
    path("auth/cadastro/", views.CadastroJogadorView.as_view(), name="cadastro"),
    path("auth/token/", obtain_auth_token, name="token"),
    path("me/", views.PerfilView.as_view(), name="perfil"),
    path("perfil-jogador/", views.PerfilJogadorView.as_view(), name="perfil_jogador"),
]
