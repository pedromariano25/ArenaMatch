"""Rotas do projeto: vitrine web (B2C), API REST e painel do gestor (Django Admin)."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('arena.api.urls')),
    path('api-auth/', include('rest_framework.urls')),
    path('', include('arena.urls')),
]
