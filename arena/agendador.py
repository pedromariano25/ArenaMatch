"""Agendador das rotinas automáticas (APScheduler).

Roda num processo separado do servidor web: ``python manage.py agendador``.
Mantenha uma única instância por ambiente. As rotinas são idempotentes, mas duas
instâncias fariam o mesmo trabalho em dobro.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler
from django.conf import settings

from .rotinas import ROTINAS


def criar_agendador() -> BlockingScheduler:
    """Monta o agendador com as rotinas registradas; todas rodam logo ao iniciar."""
    fuso = ZoneInfo(settings.TIME_ZONE)
    # Uma rotina por vez: elas mexem nas mesmas partidas e inscrições.
    agendador = BlockingScheduler(
        timezone=fuso, executors={"default": ThreadPoolExecutor(max_workers=1)}
    )
    agora = datetime.now(fuso)
    for item in ROTINAS.values():
        agendador.add_job(
            item.executar,
            "interval",
            minutes=item.minutos,
            id=item.nome,
            name=item.descricao,
            next_run_time=agora,
            max_instances=1,
            # Execuções perdidas (ex.: computador suspenso) viram uma só, com qualquer atraso.
            coalesce=True,
            misfire_grace_time=None,
        )
    return agendador
