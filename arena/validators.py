"""Validadores e normalizadores de dados brasileiros usados pelos modelos."""

import re

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

_NAO_ALFANUMERICO = re.compile(r"[^0-9A-Za-z]")

# Pesos do cálculo dos dígitos verificadores do CNPJ (o 1º dígito usa os 12 últimos).
_PESOS_CNPJ = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)

validar_telefone = RegexValidator(
    regex=r"^\+?[\d\s().-]{8,20}$",
    message="Informe um telefone válido. Ex.: (11) 91234-5678.",
    code="telefone_invalido",
)


def normalizar_documento(valor: str | None) -> str:
    """Remove a máscara de um CPF/CNPJ (pontos, barras, hífens, espaços) e o põe em maiúsculas."""
    return _NAO_ALFANUMERICO.sub("", valor or "").upper()


def digitos_verificadores_cpf(base: str) -> str:
    """Calcula os 2 dígitos verificadores para os 9 primeiros dígitos de um CPF."""
    for tamanho in (9, 10):
        pesos = range(tamanho + 1, 1, -1)
        soma = sum(int(digito) * peso for digito, peso in zip(base[:tamanho], pesos))
        base += str((soma * 10 % 11) % 10)
    return base[-2:]


def validar_cpf(valor: str) -> None:
    """Valida um CPF, com ou sem máscara, pelos dígitos verificadores.

    Raises:
        ValidationError: se o CPF não tiver 11 dígitos, tiver todos os dígitos
            iguais ou tiver dígitos verificadores incorretos.
    """
    cpf = normalizar_documento(valor)
    if not re.fullmatch(r"\d{11}", cpf) or len(set(cpf)) == 1:
        raise ValidationError("CPF inválido.", code="cpf_invalido")
    if cpf[9:] != digitos_verificadores_cpf(cpf[:9]):
        raise ValidationError("CPF inválido.", code="cpf_invalido")


def _digito_verificador_cnpj(base: str) -> str:
    """Calcula um dígito verificador do CNPJ (valor de cada caractere = código ASCII - 48)."""
    pesos = _PESOS_CNPJ[-len(base):]
    soma = sum((ord(caractere) - 48) * peso for caractere, peso in zip(base, pesos))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def digitos_verificadores_cnpj(base: str) -> str:
    """Calcula os 2 dígitos verificadores para os 12 primeiros caracteres de um CNPJ."""
    primeiro = _digito_verificador_cnpj(base[:12])
    return primeiro + _digito_verificador_cnpj(base[:12] + primeiro)


def validar_cnpj(valor: str) -> None:
    """Valida um CNPJ, com ou sem máscara, inclusive no formato alfanumérico.

    Desde julho de 2026, a Receita Federal emite CNPJs com letras nas 12 primeiras
    posições. Os dígitos verificadores continuam numéricos, e o cálculo
    (código ASCII - 48) coincide com o tradicional para CNPJs só com números.

    Raises:
        ValidationError: se o formato ou os dígitos verificadores forem inválidos.
    """
    cnpj = normalizar_documento(valor)
    if not re.fullmatch(r"[0-9A-Z]{12}\d{2}", cnpj) or len(set(cnpj)) == 1:
        raise ValidationError("CNPJ inválido.", code="cnpj_invalido")
    if cnpj[12:] != digitos_verificadores_cnpj(cnpj):
        raise ValidationError("CNPJ inválido.", code="cnpj_invalido")
