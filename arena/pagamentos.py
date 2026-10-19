"""Gateways de pagamento.

O ArenaMatch conversa com o provedor de pagamentos por uma interface única,
``Gateway``. Para trocar de fornecedor (Mercado Pago, Pagar.me, Stripe...),
implemente essa interface e aponte ``ARENAMATCH_GATEWAY_PAGAMENTO`` para a classe.

O ``MockGateway`` simula um provedor com split: o cartão é aprovado na hora e o
Pix fica pendente até a confirmação, que em desenvolvimento o próprio jogador
simula na tela de pagamento. Ele se recusa a funcionar fora do ambiente de
desenvolvimento, para nunca aprovar vagas sem dinheiro de verdade.
"""

import json
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from django.utils.module_loading import import_string

from .models import MetodoPagamento, arredondar

if TYPE_CHECKING:
    from .models import Arena, Payment


class StatusCobranca(StrEnum):
    """Resposta do gateway ao criar uma cobrança."""

    APROVADA = "aprovada"
    PENDENTE = "pendente"
    RECUSADA = "recusada"


@dataclass(frozen=True)
class Cobranca:
    """Cobrança criada no gateway."""

    status: StatusCobranca
    gateway_id: str
    pix_copia_e_cola: str = ""
    resposta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Notificacao:
    """Notificação (webhook) do gateway sobre uma cobrança."""

    gateway_id: str
    aprovado: bool
    resposta: dict[str, Any] = field(default_factory=dict)


class Gateway(ABC):
    """Contrato que todo provedor de pagamentos precisa cumprir."""

    nome: str = ""
    # Permite aprovar um Pix pela própria tela (só faz sentido em gateways simulados).
    permite_simulacao: bool = False

    @abstractmethod
    def cobrar(self, pagamento: "Payment") -> Cobranca:
        """Cria a cobrança (Pix ou cartão) com o split entre arena e plataforma."""

    @abstractmethod
    def cancelar(self, pagamento: "Payment") -> None:
        """Cancela uma cobrança ainda pendente (ex.: Pix não pago no prazo)."""

    @abstractmethod
    def estornar(self, pagamento: "Payment") -> None:
        """Devolve ao jogador um pagamento aprovado."""

    @abstractmethod
    def transferir(self, arena: "Arena", valor: Decimal) -> str:
        """Repassa ``valor`` para a arena; devolve a referência da transferência."""

    @abstractmethod
    def transferir_pix(self, chave_pix: str, valor: Decimal) -> str:
        """Envia ``valor`` para uma chave Pix (saque do organizador); devolve a referência."""

    @abstractmethod
    def tarifa(self, metodo: str, valor: Decimal) -> Decimal:
        """Tarifa cobrada pelo gateway numa transação de ``valor``."""

    @abstractmethod
    def interpretar_notificacao(self, request: HttpRequest) -> Notificacao:
        """Valida e lê um webhook do gateway.

        Raises:
            PermissionDenied: assinatura ou origem inválida.
            ValueError: conteúdo malformado.
        """


class MockGateway(Gateway):
    """Gateway simulado para desenvolvimento e testes. Não movimenta dinheiro."""

    nome = "mock"
    permite_simulacao = True
    # Tarifas ilustrativas, na ordem de grandeza do mercado brasileiro.
    TARIFAS_PERCENTUAIS = {
        MetodoPagamento.PIX: Decimal("1.00"),
        MetodoPagamento.CARTAO: Decimal("5.00"),
    }

    def __init__(self) -> None:
        if not settings.ARENAMATCH_PERMITIR_GATEWAY_SIMULADO:
            raise ImproperlyConfigured(
                "O MockGateway só roda em desenvolvimento. Configure um gateway real em "
                "ARENAMATCH_GATEWAY_PAGAMENTO."
            )

    def cobrar(self, pagamento: "Payment") -> Cobranca:
        gateway_id = f"mock_{secrets.token_hex(10)}"
        if pagamento.metodo == MetodoPagamento.CARTAO:
            return Cobranca(StatusCobranca.APROVADA, gateway_id, resposta={"simulado": True})
        return Cobranca(
            StatusCobranca.PENDENTE,
            gateway_id,
            pix_copia_e_cola=self._pix_copia_e_cola(gateway_id, pagamento.valor),
            resposta={"simulado": True},
        )

    def cancelar(self, pagamento: "Payment") -> None:
        """Nada a fazer: a cobrança simulada só existe no nosso banco."""

    def estornar(self, pagamento: "Payment") -> None:
        """Nada a fazer: o estorno simulado é só o registro no nosso banco."""

    def transferir(self, arena: "Arena", valor: Decimal) -> str:
        return f"mock_tr_{secrets.token_hex(8)}"

    def transferir_pix(self, chave_pix: str, valor: Decimal) -> str:
        return f"mock_pix_{secrets.token_hex(8)}"

    def tarifa(self, metodo: str, valor: Decimal) -> Decimal:
        percentual = self.TARIFAS_PERCENTUAIS.get(metodo, Decimal("0"))
        return arredondar(valor * percentual / 100)

    def interpretar_notificacao(self, request: HttpRequest) -> Notificacao:
        """Aceita ``{"gateway_id": "...", "status": "aprovado" | "recusado"}`` em JSON."""
        dados = json.loads(request.body or b"{}")
        gateway_id, status = dados.get("gateway_id"), dados.get("status")
        if not isinstance(gateway_id, str) or status not in ("aprovado", "recusado"):
            raise ValueError("Notificação inválida.")
        return Notificacao(gateway_id, status == "aprovado", dados)

    @staticmethod
    def _pix_copia_e_cola(gateway_id: str, valor: Decimal) -> str:
        """Código no formato visual de um Pix, marcado como teste (não é pagável)."""
        return (
            "00020126580014BR.GOV.BCB.PIX0136ARENAMATCH-TESTE-NAO-PAGUE"
            f"5204000053039865406{valor:.2f}5802BR5910ARENAMATCH6009SAO PAULO"
            f"62{len(gateway_id) + 4:02d}05{len(gateway_id):02d}{gateway_id}6304TEST"
        )


def obter_gateway() -> Gateway:
    """Instancia o gateway configurado em ``ARENAMATCH_GATEWAY_PAGAMENTO``."""
    return import_string(settings.ARENAMATCH_GATEWAY_PAGAMENTO)()
