"""Rotas do projeto: vitrine web (B2C), Portal do Gestor (B2B), API REST e back-office."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('manager/', include('arena.urls_gestor')),
    path('api/', include('arena.api.urls')),
    path('api-auth/', include('rest_framework.urls')),
    path('', include('arena.urls')),
]
