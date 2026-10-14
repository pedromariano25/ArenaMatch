"""Entrar com o telefone: código de uso único por SMS (sem senha).

1. ``solicitar_codigo`` gera um código de 6 dígitos, guarda só o hash e o envia.
2. ``validar_codigo`` confere o código e devolve o usuário daquele telefone,
   criando a conta de jogador no primeiro acesso.

Os limites (validade, tentativas e pedidos por janela) impedem adivinhação e
abuso de envio. O envio passa por ``ARENAMATCH_SMS_BACKEND``; em desenvolvimento,
o ``SmsConsole`` só registra a mensagem.
"""

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from .formatacao import apenas_digitos
from .models import CodigoAcesso, CustomUser

logger = logging.getLogger(__name__)

MINUTOS_DE_VALIDADE = 10
MAXIMO_DE_TENTATIVAS = 5
MAXIMO_DE_CODIGOS = 3
JANELA_DE_PEDIDOS = timedelta(minutes=15)


class SmsConsole:
    """Desenvolvimento: registra a mensagem no log em vez de enviar."""

    simulado = True

    def enviar(self, telefone: str, mensagem: str) -> None:
        logger.warning("SMS para %s: %s", formatar_telefone(telefone), mensagem)


class SmsMemoria:
    """Testes: guarda as mensagens em ``caixa_de_saida``."""

    simulado = True
    caixa_de_saida: list[tuple[str, str]] = []

    def enviar(self, telefone: str, mensagem: str) -> None:
        self.caixa_de_saida.append((telefone, mensagem))


def obter_sms() -> SmsConsole | SmsMemoria:
    return import_string(settings.ARENAMATCH_SMS_BACKEND)()


def normalizar_telefone(valor: str) -> str:
    """Telefone brasileiro só com dígitos (DDD + número), sem o 55.

    Raises:
        ValidationError: número sem DDD ou com tamanho inválido.
    """
    digitos = apenas_digitos(valor)
    if digitos.startswith("55") and len(digitos) in (12, 13):
        digitos = digitos[2:]
    if len(digitos) not in (10, 11) or digitos[0] == "0":
        raise ValidationError("Informe o celular com DDD. Ex.: (11) 91234-5678.", code="telefone_invalido")
    return digitos


def formatar_telefone(digitos: str) -> str:
    """``11912345678`` → ``(11) 91234-5678``."""
    return f"({digitos[:2]}) {digitos[2:-4]}-{digitos[-4:]}"


def solicitar_codigo(telefone: str) -> str:
    """Gera e envia o código. Devolve o código (exibido na tela só em modo de demonstração).

    Raises:
        ValidationError: telefone inválido ou pedidos demais em pouco tempo.
    """
    digitos = normalizar_telefone(telefone)
    recentes = CodigoAcesso.objects.filter(telefone=digitos, created_at__gte=timezone.now() - JANELA_DE_PEDIDOS)
    if recentes.count() >= MAXIMO_DE_CODIGOS:
        raise ValidationError("Você pediu códigos demais. Espere alguns minutos e tente de novo.", code="limite")
    codigo = f"{secrets.randbelow(1_000_000):06d}"
    CodigoAcesso.objects.create(
        telefone=digitos,
        codigo_hash=make_password(codigo),
        expira_em=timezone.now() + timedelta(minutes=MINUTOS_DE_VALIDADE),
    )
    obter_sms().enviar(digitos, f"Seu código ArenaMatch é {codigo}. Vale por {MINUTOS_DE_VALIDADE} minutos.")
    return codigo


def validar_codigo(telefone: str, codigo: str, nome: str = "") -> CustomUser:
    """Confere o código e devolve o usuário do telefone (cria um jogador no primeiro acesso).

    A tentativa errada é gravada antes de o erro ser lançado: dentro da transação,
    o erro desfaria a contagem e as tentativas ficariam ilimitadas.

    Raises:
        ValidationError: código errado, expirado, já usado ou tentativas esgotadas.
    """
    digitos = normalizar_telefone(telefone)
    with transaction.atomic():
        pendente = (
            CodigoAcesso.objects.select_for_update()
            .filter(telefone=digitos, usado_em__isnull=True, expira_em__gt=timezone.now())
            .first()
        )
        if pendente is None or pendente.tentativas >= MAXIMO_DE_TENTATIVAS:
            erro = ValidationError("Código expirado. Peça um novo.", code="codigo_expirado")
        else:
            pendente.tentativas += 1
            if check_password(apenas_digitos(codigo), pendente.codigo_hash):
                pendente.usado_em = timezone.now()
                pendente.save(update_fields=["tentativas", "usado_em", "updated_at"])
                return usuario_do_telefone(digitos) or _criar_jogador(digitos, nome)
            pendente.save(update_fields=["tentativas", "updated_at"])
            restantes = MAXIMO_DE_TENTATIVAS - pendente.tentativas
            erro = ValidationError(f"Código incorreto. Restam {restantes} tentativa(s).", code="codigo_incorreto")
    raise erro


def usuario_do_telefone(digitos: str) -> CustomUser | None:
    """Usuário ativo cujo telefone (com qualquer máscara) tem esses dígitos."""
    candidatos = CustomUser.objects.filter(is_active=True, telefone__endswith=digitos[-4:])
    return next((u for u in candidatos if apenas_digitos(u.telefone).removeprefix("55") == digitos), None)


def _criar_jogador(digitos: str, nome: str) -> CustomUser:
    nome = nome.strip()
    primeiro, _, resto = nome.partition(" ")
    username = f"tel{digitos}"
    while CustomUser.objects.filter(username=username).exists():
        username = f"tel{digitos}{secrets.randbelow(1000)}"
    jogador = CustomUser(
        username=username,
        first_name=primeiro[:150],
        last_name=resto[:150],
        telefone=formatar_telefone(digitos),
        is_player=True,
    )
    jogador.set_unusable_password()
    jogador.full_clean()
    jogador.save()
    return jogador
