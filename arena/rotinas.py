"""Rotinas automáticas da plataforma, executadas pelo agendador (``manage.py agendador``).

Cada rotina é uma função sem argumentos registrada com ``@rotina``. Ela varre o
banco e age sobre o que estiver vencido, então precisa ser idempotente: rodar
com atraso ou duas vezes seguidas não pode duplicar nenhum efeito.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.core.management import call_command
from django.db import connections

Funcao = Callable[[], None]


def _reciclar_conexoes() -> None:
    """Fecha conexões vencidas ou quebradas, como o Django faz a cada requisição web.

    Conexões com transação aberta ficam como estão: fechá-las desfaria a transação.
    """
    for conexao in connections.all(initialized_only=True):
        if not conexao.in_atomic_block:
            conexao.close_if_unusable_or_obsolete()


@dataclass(frozen=True)
class Rotina:
    """Função executada periodicamente pelo agendador."""

    nome: str
    funcao: Funcao
    minutos: int
    descricao: str

    def executar(self) -> None:
        """Roda a rotina com conexões de banco válidas.

        Fora das requisições web, o Django não recicla conexões sozinho. Sem isso,
        um processo de longa duração reaproveitaria conexões vencidas ou quebradas.
        """
        _reciclar_conexoes()
        try:
            self.funcao()
        finally:
            _reciclar_conexoes()


ROTINAS: dict[str, Rotina] = {}


def rotina(*, minutos: int, descricao: str) -> Callable[[Funcao], Funcao]:
    """Registra a função decorada para rodar a cada ``minutos``."""

    def registrar(funcao: Funcao) -> Funcao:
        ROTINAS[funcao.__name__] = Rotina(funcao.__name__, funcao, minutos, descricao)
        return funcao

    return registrar


# --- Rotinas -----------------------------------------------------------------


@rotina(minutos=24 * 60, descricao="Apaga do banco as sessões de login expiradas.")
def limpar_sessoes_expiradas() -> None:
    call_command("clearsessions")
