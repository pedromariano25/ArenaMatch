"""Rotas do projeto: site (landing), app do jogador (B2C), Portal do Gestor (B2B), API e back-office."""

from django.contrib import admin
from django.urls import include, path, re_path

from arena.views import LandingView, PagamentoWebhookView, redirecionar_para_o_app

urlpatterns = [
    path('admin/', admin.site.urls),
    path('manager/', include('arena.urls_gestor')),
    path('api/', include('arena.api.urls')),
    path('pagamentos/webhook/', PagamentoWebhookView.as_view(), name='webhook_pagamentos'),
    path('api-auth/', include('rest_framework.urls')),
    path('app/', include('arena.urls')),
    path('', LandingView.as_view(), name='inicio'),
    # Links antigos da vitrine, de quando ela ficava na raiz do site.
    re_path(
        r'^(?P<caminho>(partidas|inscricoes|minhas-inscricoes|perfil|entrar|cadastro)/.*)$',
        redirecionar_para_o_app,
    ),
]
