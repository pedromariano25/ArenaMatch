"""Ciclo de vida da inscrição: checkout, pagamento, cancelamento, repasse e lista de espera.

1. ``iniciar_checkout`` cria a inscrição como reserva, que segura a vaga por
   ``MINUTOS_RESERVA``, e a cobrança no gateway.
2. O gateway aprova o pagamento (na hora, no cartão; por notificação, no Pix) e
   ``confirmar_pagamento`` confirma a vaga e lança a venda no razão.
3. Sem pagamento no prazo, ``expirar_reservas`` devolve a vaga à partida.

Goleiros não pagam: a vaga deles é confirmada direto. O crédito do jogador
(recebido em cancelamentos) também confirma a vaga na hora.
"""

import logging
from datetime import datetime
from functools import partial

from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import notificacoes, razao
from .formatacao import formatar_brl
from .models import (
    STATUS_INSCRICAO_ATIVA,
    STATUS_PARTIDA_ATIVA,
    Booking,
    MetodoPagamento,
    OpenMatch,
    Payment,
    Posicao,
    StatusInscricao,
    StatusPagamento,
    WaitlistEntry,
)
from .pagamentos import Gateway, StatusCobranca, obter_gateway

logger = logging.getLogger(__name__)

METODOS_PAGOS = (MetodoPagamento.PIX, MetodoPagamento.CARTAO, MetodoPagamento.CREDITO)


# --- Checkout ----------------------------------------------------------------


def iniciar_checkout(
    partida: OpenMatch,
    jogador: AbstractBaseUser,
    *,
    posicao: str = Posicao.LINHA,
    metodo: str = MetodoPagamento.PIX,
) -> Booking:
    """Reserva a vaga e cobra o jogador. Devolve a inscrição confirmada ou aguardando pagamento.

    Raises:
        ValidationError: partida lotada ou indisponível, crédito insuficiente,
            pagamento recusado etc.
    """
    if posicao == Posicao.GOLEIRO:
        metodo = MetodoPagamento.GRATUITO
    elif metodo not in METODOS_PAGOS:
        raise ValidationError("Escolha Pix, cartão ou crédito para pagar a vaga.")
    gateway = obter_gateway()
    with transaction.atomic():
        partida = OpenMatch.objects.select_for_update().get(pk=partida.pk)
        expirar_reservas_da_partida(partida)
        if metodo in (MetodoPagamento.GRATUITO, MetodoPagamento.CREDITO):
            return _confirmar_sem_gateway(partida, jogador, posicao, metodo)
        inscricao = Booking.objects.create(
            open_match=partida, player=jogador, posicao=posicao, metodo_pagamento=metodo
        )
        pagamento = Payment.objects.create(
            booking=inscricao,
            metodo=metodo,
            valor=inscricao.valor_total,
            gateway=gateway.nome,
            expira_em=inscricao.reservada_ate,
        )

    try:
        cobranca = gateway.cobrar(pagamento)
    except Exception as erro:
        logger.exception("Falha ao criar a cobrança %s no gateway.", pagamento.pk)
        _encerrar_tentativa(pagamento, StatusPagamento.RECUSADO)
        raise ValidationError("Não foi possível iniciar o pagamento. Tente de novo em instantes.") from erro

    pagamento.gateway_id = cobranca.gateway_id
    pagamento.pix_copia_e_cola = cobranca.pix_copia_e_cola
    pagamento.resposta_gateway = cobranca.resposta
    pagamento.save()
    if cobranca.status == StatusCobranca.APROVADA:
        return confirmar_pagamento(pagamento, resposta=cobranca.resposta)
    if cobranca.status == StatusCobranca.RECUSADA:
        _encerrar_tentativa(pagamento, StatusPagamento.RECUSADO)
        raise ValidationError("Pagamento recusado. Tente outra forma de pagamento.")
    return inscricao


def _confirmar_sem_gateway(
    partida: OpenMatch, jogador: AbstractBaseUser, posicao: str, metodo: str
) -> Booking:
    """Goleiro (grátis) ou pagamento com crédito: a vaga é confirmada na hora."""
    inscricao = Booking(
        open_match=partida,
        player=jogador,
        posicao=posicao,
        metodo_pagamento=metodo,
        status=StatusInscricao.CONFIRMADA,
    )
    if metodo == MetodoPagamento.GRATUITO:
        inscricao.save()
        _apos_confirmacao(inscricao)
        return inscricao

    carteira = razao.bloquear_carteira_do_jogador(jogador)
    total = sum(partida.valores_da_vaga(posicao, metodo))
    saldo = razao.saldo(carteira.lancamentos.all())
    if saldo < total:
        raise ValidationError(
            f"Seu crédito ({formatar_brl(saldo)}) não cobre esta vaga ({formatar_brl(total)})."
        )
    inscricao.save()
    pagamento = Payment.objects.create(
        booking=inscricao,
        metodo=metodo,
        status=StatusPagamento.APROVADO,
        valor=inscricao.valor_total,
        gateway="credito",
        aprovado_em=timezone.now(),
    )
    razao.registrar_venda(inscricao, pagamento)
    _apos_confirmacao(inscricao)
    return inscricao


def confirmar_pagamento(pagamento: Payment, *, resposta: dict | None = None) -> Booking:
    """Confirma a vaga de um pagamento aprovado e lança a venda no razão.

    Idempotente: notificações repetidas do gateway não duplicam nada. Se a reserva
    venceu e a vaga já foi para outro jogador, o pagamento é devolvido.
    """
    gateway = obter_gateway()
    with transaction.atomic():
        pagamento = Payment.objects.select_for_update().select_related("booking").get(pk=pagamento.pk)
        inscricao = pagamento.booking
        if pagamento.status in (StatusPagamento.APROVADO, StatusPagamento.ESTORNADO):
            return inscricao  # Notificação repetida.
        agora = timezone.now()
        pagamento.aprovado_em = agora
        pagamento.tarifa_gateway = gateway.tarifa(pagamento.metodo, pagamento.valor)
        if resposta:
            pagamento.resposta_gateway = resposta
        if pagamento.status in (StatusPagamento.CANCELADO, StatusPagamento.RECUSADO):
            # O dinheiro chegou numa cobrança já encerrada (ex.: reserva cancelada).
            _devolver_pagamento(pagamento, gateway)
            return inscricao

        pagamento.status = StatusPagamento.APROVADO
        pagamento.save()
        inscricao.status = StatusInscricao.CONFIRMADA
        inscricao.confirmada_em = agora
        try:
            inscricao.save()
        except ValidationError:
            # Pagamento depois do prazo, com a vaga já ocupada por outro jogador.
            inscricao.refresh_from_db()
            _devolver_pagamento(pagamento, gateway)
            return inscricao

        razao.registrar_venda(inscricao, pagamento)
        _apos_confirmacao(inscricao)
    return inscricao


def _devolver_pagamento(pagamento: Payment, gateway: Gateway) -> None:
    """Estorna um pagamento que não virou vaga; a tarifa do gateway fica como custo."""
    pagamento.status = StatusPagamento.ESTORNADO
    pagamento.estornado_em = timezone.now()
    pagamento.save()
    razao.registrar_tarifa(pagamento)
    transaction.on_commit(partial(gateway.estornar, pagamento))
    notificacoes.avisar_pagamento_devolvido(pagamento.booking)


def processar_notificacao(gateway_id: str, *, aprovado: bool, resposta: dict | None = None) -> Payment:
    """Aplica uma notificação (webhook) do gateway ao pagamento correspondente.

    Raises:
        Payment.DoesNotExist: nenhum pagamento com esse identificador.
    """
    pagamento = Payment.objects.get(gateway_id=gateway_id)
    if aprovado:
        confirmar_pagamento(pagamento, resposta=resposta)
    else:
        _encerrar_tentativa(pagamento, StatusPagamento.RECUSADO, resposta=resposta)
    pagamento.refresh_from_db()
    return pagamento


def simular_pagamento(inscricao: Booking) -> Booking:
    """Aprova o Pix pendente de uma inscrição (só com gateways simulados)."""
    if not obter_gateway().permite_simulacao:
        raise ValidationError("Este ambiente não permite simular pagamentos.")
    pagamento = inscricao.pagamentos.filter(status=StatusPagamento.PENDENTE).first()
    if pagamento is None:
        raise ValidationError("Não há pagamento pendente nesta inscrição.")
    return confirmar_pagamento(pagamento, resposta={"simulado": True})


def _encerrar_tentativa(pagamento: Payment, status: str, *, resposta: dict | None = None) -> None:
    """Pagamento recusado ou abandonado: a reserva é cancelada e a vaga volta."""
    with transaction.atomic():
        pagamento = Payment.objects.select_for_update().select_related("booking").get(pk=pagamento.pk)
        if pagamento.status != StatusPagamento.PENDENTE:
            return
        pagamento.status = status
        if resposta:
            pagamento.resposta_gateway = resposta
        pagamento.save()
        inscricao = pagamento.booking
        if inscricao.status == StatusInscricao.AGUARDANDO_PAGAMENTO:
            inscricao.status = StatusInscricao.CANCELADA
            inscricao.cancelada_em = timezone.now()
            inscricao.save()
            notificacoes.avisar_vaga_aberta(inscricao.open_match)


def _apos_confirmacao(inscricao: Booking) -> None:
    """Tira o jogador da lista de espera, resolve repasses e avisa o jogador."""
    WaitlistEntry.objects.filter(
        partida_id=inscricao.open_match_id, jogador_id=inscricao.player_id
    ).delete()
    _resolver_repasses(inscricao.open_match, inscricao.posicao)
    notificacoes.avisar_inscricao_confirmada(inscricao)


def _resolver_repasses(partida: OpenMatch, posicao: str) -> None:
    """Se a vaga nova era de alguém em repasse, quem repassou recebe crédito integral.

    Vagas em repasse não ocupam lugar; quando as vagas pagas (contando as em
    repasse) passam da capacidade, os repasses mais antigos são concluídos.
    """
    pagas = Booking.objects.filter(
        open_match=partida, posicao=posicao, status=StatusInscricao.CONFIRMADA
    )
    reservas = Booking.objects.filter(
        open_match=partida,
        posicao=posicao,
        status=StatusInscricao.AGUARDANDO_PAGAMENTO,
        reservada_ate__gt=timezone.now(),
    )
    excedente = pagas.count() + reservas.count() - partida.capacidade(posicao)
    if excedente <= 0:
        return
    em_repasse = pagas.filter(repasse_solicitado_em__isnull=False).order_by("repasse_solicitado_em")
    for inscricao in em_repasse[:excedente]:
        inscricao.status = StatusInscricao.CANCELADA
        inscricao.cancelada_em = timezone.now()
        inscricao.save()
        razao.registrar_estorno(inscricao, credito=True)
        notificacoes.avisar_vaga_repassada(inscricao)


# --- Expiração ---------------------------------------------------------------


def expirar_reservas(agora: datetime | None = None) -> int:
    """Expira as reservas sem pagamento no prazo e devolve as vagas (rotina do agendador)."""
    agora = agora or timezone.now()
    partidas = OpenMatch.objects.filter(
        pk__in=Booking.objects.reservas_vencidas(agora).values("open_match_id")
    ).values_list("pk", flat=True)
    total = 0
    for partida_id in partidas:
        with transaction.atomic():
            partida = OpenMatch.objects.select_for_update().get(pk=partida_id)
            total += expirar_reservas_da_partida(partida, agora)
    return total


def expirar_reservas_da_partida(partida: OpenMatch, agora: datetime | None = None) -> int:
    """Expira as reservas vencidas de uma partida já travada pela transação atual."""
    vencidas = list(Booking.objects.filter(open_match=partida).reservas_vencidas(agora))
    if not vencidas:
        return 0
    gateway = obter_gateway()
    for inscricao in vencidas:
        inscricao.status = StatusInscricao.EXPIRADA
        inscricao.save()
        for pagamento in inscricao.pagamentos.filter(status=StatusPagamento.PENDENTE):
            pagamento.status = StatusPagamento.EXPIRADO
            pagamento.save()
            transaction.on_commit(partial(gateway.cancelar, pagamento))
    notificacoes.avisar_vaga_aberta(partida)
    return len(vencidas)


# --- Cancelamento e repasse --------------------------------------------------


def cancelar_inscricao(inscricao: Booking) -> str:
    """Cancela a inscrição conforme a política e devolve a mensagem para o jogador.

    - Reserva (aguardando pagamento): cancelada, sem cobrança.
    - Vaga paga até 24h antes do jogo: cancelada, com crédito integral na carteira.
    - Vaga de goleiro (grátis): liberada a qualquer momento antes do jogo.
    - Vaga paga a menos de 24h: não cancela, mas pode ser repassada à lista de espera.

    Raises:
        ValidationError: fora da política de cancelamento.
    """
    gateway = obter_gateway()
    with transaction.atomic():
        partida = OpenMatch.objects.select_for_update().get(pk=inscricao.open_match_id)
        inscricao = Booking.objects.select_for_update().get(pk=inscricao.pk)
        if not inscricao.pode_cancelar:
            raise ValidationError(_motivo_sem_cancelamento(inscricao))
        reserva = inscricao.status == StatusInscricao.AGUARDANDO_PAGAMENTO
        inscricao.status = StatusInscricao.CANCELADA
        inscricao.cancelada_em = timezone.now()
        inscricao.save()
        if reserva:
            for pagamento in inscricao.pagamentos.filter(status=StatusPagamento.PENDENTE):
                pagamento.status = StatusPagamento.CANCELADO
                pagamento.save()
                transaction.on_commit(partial(gateway.cancelar, pagamento))
            mensagem = "Reserva cancelada. Nenhum valor foi cobrado."
        elif inscricao.gratuita:
            mensagem = "Vaga de goleiro liberada."
        else:
            razao.registrar_estorno(inscricao, credito=True)
            mensagem = (
                f"Inscrição cancelada. {formatar_brl(inscricao.valor_total)} voltaram como "
                "crédito na sua carteira."
            )
        notificacoes.avisar_vaga_aberta(partida)
    return mensagem


def _motivo_sem_cancelamento(inscricao: Booking) -> str:
    if inscricao.open_match.time_slot.ja_comecou:
        return "A partida já começou."
    if inscricao.em_repasse:
        return "Sua vaga já está em repasse para a lista de espera."
    if inscricao.status == StatusInscricao.CONFIRMADA:
        return (
            "Faltam menos de 24h para o jogo: a vaga não é reembolsada, mas você pode "
            "repassá-la para a lista de espera."
        )
    return "Esta inscrição não pode mais ser cancelada."


def repassar_vaga(inscricao: Booking) -> None:
    """Libera a vaga paga para a lista de espera (a menos de 24h do jogo).

    O jogador continua inscrito até alguém assumir a vaga; aí recebe crédito
    integral. Se ninguém assumir até o jogo, a vaga segue dele.
    """
    with transaction.atomic():
        partida = OpenMatch.objects.select_for_update().get(pk=inscricao.open_match_id)
        inscricao = Booking.objects.select_for_update().get(pk=inscricao.pk)
        if not inscricao.pode_repassar:
            raise ValidationError("Esta vaga não pode ser repassada agora.")
        inscricao.repasse_solicitado_em = timezone.now()
        inscricao.save()
        notificacoes.avisar_vaga_aberta(partida)


def desfazer_repasse(inscricao: Booking) -> None:
    """O jogador desiste do repasse, se ninguém tiver reservado a vaga ainda."""
    with transaction.atomic():
        OpenMatch.objects.select_for_update().get(pk=inscricao.open_match_id)
        inscricao = Booking.objects.select_for_update().get(pk=inscricao.pk)
        if not inscricao.em_repasse:
            raise ValidationError("Esta vaga não está em repasse.")
        inscricao.repasse_solicitado_em = None
        try:
            inscricao.save()
        except ValidationError as erro:
            raise ValidationError("Outro jogador já está pagando por esta vaga.") from erro


# --- Lista de espera ---------------------------------------------------------


def entrar_na_lista_de_espera(
    partida: OpenMatch, jogador: AbstractBaseUser, posicao: str = Posicao.LINHA
) -> WaitlistEntry:
    """Coloca o jogador na fila de avisos de vaga da partida."""
    if partida.status not in STATUS_PARTIDA_ATIVA or partida.time_slot.ja_comecou:
        raise ValidationError("Esta partida não aceita mais inscrições.")
    ja_inscrito = Booking.objects.filter(
        open_match=partida, player=jogador, status__in=STATUS_INSCRICAO_ATIVA
    ).exists()
    if ja_inscrito:
        raise ValidationError("Você já está nesta partida.")
    lugar, _ = WaitlistEntry.objects.get_or_create(
        partida=partida, jogador=jogador, defaults={"posicao": posicao}
    )
    return lugar


def sair_da_lista_de_espera(partida: OpenMatch, jogador: AbstractBaseUser) -> None:
    WaitlistEntry.objects.filter(partida=partida, jogador=jogador).delete()
