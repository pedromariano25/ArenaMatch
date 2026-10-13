"""Permissões da API B2C."""

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


class IsJogador(BasePermission):
    """Permite acesso apenas a usuários autenticados marcados como jogadores."""

    message = "Apenas contas de jogador podem se inscrever em partidas."

    def has_permission(self, request: Request, view: APIView) -> bool:
        usuario = request.user
        return bool(usuario and usuario.is_authenticated and usuario.is_player)
