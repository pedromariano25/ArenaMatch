"""Formatação de valores para exibição: documentos, telefone e moeda."""

from decimal import Decimal


def apenas_digitos(valor: str | None) -> str:
    """Remove tudo o que não for dígito."""
    return "".join(caractere for caractere in valor or "" if caractere.isdigit())


def formatar_cnpj(cnpj: str | None) -> str:
    """Aplica a máscara ``00.000.000/0000-00`` a um CNPJ normalizado."""
    if not cnpj or len(cnpj) != 14:
        return cnpj or ""
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


def formatar_cpf(cpf: str | None) -> str:
    """Aplica a máscara ``000.000.000-00`` a um CPF normalizado."""
    if not cpf or len(cpf) != 11:
        return cpf or ""
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"


def formatar_brl(valor: Decimal | int | float | None) -> str:
    """Formata um valor como moeda brasileira, ex.: ``R$ 1.234,56``.

    O espaço após ``R$`` é não separável, para o valor não quebrar de linha.
    """
    if valor is None:
        return ""
    texto = f"{Decimal(valor):,.2f}"
    return "R$ " + texto.replace(",", "_").replace(".", ",").replace("_", ".")
