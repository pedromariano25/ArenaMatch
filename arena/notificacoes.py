"""Avisos por e-mail aos jogadores: confirmações, vagas abertas e cancelamentos.

Os e-mails só saem depois do commit da transação, para nunca avisar sobre algo
que acabou desfeito. Cada destinatário recebe a própria mensagem (ninguém vê o
e-mail dos outros). Em desenvolvimento, eles aparecem no console.
"""

from collections.abc import Iterable

from django.conf import settings
from django.core.mail import send_mass_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from .formatacao import formatar_brl
from .models import Booking, OpenMatch, WaitlistEntry

# Quantos jogadores da lista de espera são avisados de cada vaga aberta.
AVISOS_POR_VAGA = 10


def _link(caminho: str) -> str:
    return settings.ARENAMATCH_URL_BASE.rstrip("/") + caminho


def _quando(partida: OpenMatch) -> str:
    horario = partida.time_slot
    return (
        f"{date_format(horario.data, 'l, d/m')} · {horario.intervalo} · "
        f"{horario.court.arena.nome} ({horario.court.nome_ou_numero})"
    )


def _enviar(assunto: str, mensagem: str, destinatarios: Iterable[str]) -> None:
    mensagens = [(assunto, mensagem, None, [email]) for email in dict.fromkeys(destinatarios) if email]
    if mensagens:
        transaction.on_commit(lambda: send_mass_mail(mensagens, fail_silently=True))


def avisar_inscricao_confirmada(inscricao: Booking) -> None:
    partida = inscricao.open_match
    valor = "Vaga de goleiro, sem custo." if inscricao.gratuita else f"Valor pago: {formatar_brl(inscricao.valor_total)}."
    _enviar(
        f"Vaga garantida: {_quando(partida)}",
        f"Você está dentro da partida de {_quando(partida)}.\n{valor}\n\n"
        f"Comprovante: {_link(reverse('arena:inscricao', args=[inscricao.pk]))}",
        [inscricao.player.email],
    )


def avisar_vaga_aberta(partida: OpenMatch) -> int:
    """Avisa a lista de espera que abriu vaga: quem garantir primeiro, joga."""
    fila = list(partida.lista_de_espera.select_related("jogador")[:AVISOS_POR_VAGA])
    if not fila:
        return 0
    _enviar(
        f"Abriu vaga: {_quando(partida)}",
        f"Uma vaga abriu na partida de {_quando(partida)}.\n"
        f"Quem garantir primeiro, joga: {_link(partida.get_absolute_url())}",
        [lugar.jogador.email for lugar in fila],
    )
    WaitlistEntry.objects.filter(pk__in=[lugar.pk for lugar in fila]).update(notificado_em=timezone.now())
    return len(fila)


def avisar_partida_cancelada(partida: OpenMatch, inscricoes: Iterable[Booking]) -> None:
    motivo = partida.get_motivo_cancelamento_display() or "Partida cancelada"
    _enviar(
        f"Partida cancelada: {_quando(partida)}",
        f"A partida de {_quando(partida)} foi cancelada ({motivo.lower()}).\n"
        "O valor pago volta integralmente pela mesma forma de pagamento "
        "(ou como crédito, se você pagou com crédito).",
        [inscricao.player.email for inscricao in inscricoes],
    )


def avisar_vaga_repassada(inscricao: Booking) -> None:
    _enviar(
        f"Sua vaga foi repassada: {_quando(inscricao.open_match)}",
        f"Outro jogador assumiu a vaga que você liberou. "
        f"{formatar_brl(inscricao.valor_total)} voltaram como crédito na sua carteira ArenaMatch.",
        [inscricao.player.email],
    )


def avisar_pagamento_devolvido(inscricao: Booking) -> None:
    _enviar(
        f"Pagamento devolvido: {_quando(inscricao.open_match)}",
        "Seu pagamento foi aprovado depois do prazo da reserva, e a vaga já tinha sido "
        "garantida por outro jogador. O valor foi devolvido integralmente.",
        [inscricao.player.email],
    )
