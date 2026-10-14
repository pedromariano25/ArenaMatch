"""Motor financeiro: aluguel total + taxa da plataforma e valores congelados nas inscrições.

Converte os dados existentes: o aluguel de cada partida passa a ser o antigo preço
por vaga x vagas (a quadra mantém a receita esperada) e cada inscrição recebe a
parte da quadra e a taxa calculadas com as regras novas.
"""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

import django.core.validators
from django.db import migrations, models

CENTAVO = Decimal("0.01")


def converter_precos(apps, schema_editor):
    OpenMatch = apps.get_model("arena", "OpenMatch")
    Booking = apps.get_model("arena", "Booking")
    for partida in OpenMatch.objects.all():
        partida.valor_total_aluguel = partida.preco_por_vaga * partida.vagas_totais
        partida.save(update_fields=["valor_total_aluguel"])
    for inscricao in Booking.objects.select_related("open_match"):
        partida = inscricao.open_match
        base = (partida.valor_total_aluguel / partida.vagas_totais).quantize(
            CENTAVO, rounding=ROUND_CEILING
        )
        inscricao.valor_vaga = base
        inscricao.valor_taxa = (base * partida.taxa_plataforma_percentual / 100).quantize(
            CENTAVO, rounding=ROUND_HALF_UP
        )
        inscricao.save(update_fields=["valor_vaga", "valor_taxa"])


class Migration(migrations.Migration):

    dependencies = [
        ("arena", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="openmatch",
            name="valor_total_aluguel",
            field=models.DecimalField(
                decimal_places=2,
                max_digits=10,
                null=True,
                verbose_name="valor total do aluguel (R$)",
            ),
        ),
        migrations.AddField(
            model_name="openmatch",
            name="taxa_plataforma_percentual",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("15.00"),
                help_text="Taxa de serviço cobrada do jogador sobre a parte da quadra em cada vaga.",
                max_digits=5,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0")),
                    django.core.validators.MaxValueValidator(Decimal("100")),
                ],
                verbose_name="taxa da plataforma (%)",
            ),
        ),
        migrations.AddField(
            model_name="booking",
            name="valor_vaga",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                editable=False,
                help_text="Parte do aluguel paga nesta vaga (repasse à quadra), congelada na inscrição.",
                max_digits=8,
                verbose_name="valor para a quadra (R$)",
            ),
        ),
        migrations.AddField(
            model_name="booking",
            name="valor_taxa",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                editable=False,
                help_text="Receita da plataforma nesta vaga, congelada na inscrição.",
                max_digits=8,
                verbose_name="taxa de conveniência (R$)",
            ),
        ),
        migrations.RunPython(converter_precos, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="openmatch",
            name="preco_por_vaga",
        ),
        migrations.AlterField(
            model_name="openmatch",
            name="valor_total_aluguel",
            field=models.DecimalField(
                decimal_places=2,
                help_text="Quanto a quadra recebe com todas as vagas vendidas.",
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                verbose_name="valor total do aluguel (R$)",
            ),
        ),
    ]
