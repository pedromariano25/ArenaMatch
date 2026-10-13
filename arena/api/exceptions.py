"""Tratamento de exceções da API."""

from typing import Any

from django.core.exceptions import NON_FIELD_ERRORS
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.serializers import as_serializer_error
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler


def tratar_excecoes(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Converte a ``ValidationError`` do Django (lançada em ``save()``) em HTTP 400.

    Assim, as regras de negócio dos modelos (partida lotada, inscrição duplicada,
    horário indisponível...) chegam ao cliente como erros de validação legíveis.
    """
    if isinstance(exc, DjangoValidationError):
        erros = as_serializer_error(exc)
        if NON_FIELD_ERRORS in erros:
            erros[api_settings.NON_FIELD_ERRORS_KEY] = erros.pop(NON_FIELD_ERRORS)
        exc = ValidationError(detail=erros)
    return exception_handler(exc, context)
