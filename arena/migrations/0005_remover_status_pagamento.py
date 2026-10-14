from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("arena", "0004_converter_status_das_inscricoes"),
    ]

    operations = [
        migrations.RemoveField(
            model_name='booking',
            name='status_pagamento',
        ),
        migrations.AddConstraint(
            model_name='booking',
            constraint=models.UniqueConstraint(condition=models.Q(('status__in', ('aguardando_pagamento', 'confirmada'))), fields=('open_match', 'player'), name='booking_inscricao_ativa_unica', violation_error_message='Este jogador já tem uma inscrição ativa nesta partida.'),
        ),
    ]
