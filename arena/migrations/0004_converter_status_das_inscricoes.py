"""Converte o status de pagamento manual (pendente/pago/reembolsado) no status da inscrição.

Inscrições pagas viram confirmadas; reembolsadas continuam reembolsadas. As
pendentes (do tempo do pagamento na arena) viram reservas já vencidas, que a
rotina de expiração encerra e cujas vagas voltam para as partidas.
"""

from django.db import migrations
from django.utils import timezone

MAPA = {
    "pago": "confirmada",
    "pendente": "aguardando_pagamento",
    "reembolsado": "reembolsada",
}


def converter(apps, schema_editor):
    Booking = apps.get_model("arena", "Booking")
    agora = timezone.now()
    for inscricao in Booking.objects.all():
        inscricao.status = MAPA.get(inscricao.status_pagamento, "cancelada")
        if inscricao.status == "confirmada":
            inscricao.confirmada_em = inscricao.data_inscricao
        elif inscricao.status == "aguardando_pagamento":
            inscricao.reservada_ate = agora
        inscricao.save(update_fields=["status", "confirmada_em", "reservada_ate"])


def desfazer(apps, schema_editor):
    Booking = apps.get_model("arena", "Booking")
    inverso = {"confirmada": "pago", "reembolsada": "reembolsado"}
    for inscricao in Booking.objects.all():
        inscricao.status_pagamento = inverso.get(inscricao.status, "pendente")
        inscricao.save(update_fields=["status_pagamento"])


class Migration(migrations.Migration):

    dependencies = [
        ("arena", "0003_fase1_checkout_razao"),
    ]

    operations = [
        migrations.RunPython(converter, desfazer),
    ]
