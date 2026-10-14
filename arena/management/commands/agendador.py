"""Comando ``agendador``: executa as rotinas automáticas da plataforma."""

from typing import Any

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from ...agendador import criar_agendador
from ...rotinas import ROTINAS


class Command(BaseCommand):
    help = (
        "Executa as rotinas automáticas, cada uma no seu intervalo, até ser interrompido. "
        "Rode um único processo por ambiente."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--uma-vez",
            action="store_true",
            help="Executa cada rotina uma vez e encerra (para cron ou conferência).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["uma_vez"]:
            self._executar_uma_vez()
            return

        agendador = criar_agendador()
        agendador.add_listener(self._registrar_execucao, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        for item in ROTINAS.values():
            self.stdout.write(f"  {item.nome}: a cada {item.minutos} min. {item.descricao}")
        self.stdout.write(self.style.SUCCESS("Agendador rodando. Pressione Ctrl+C para parar."))
        try:
            agendador.start()
        except (KeyboardInterrupt, SystemExit):
            self.stdout.write("Agendador encerrado.")

    def _executar_uma_vez(self) -> None:
        """Roda todas as rotinas; uma rotina com erro não impede as demais."""
        falhas = []
        for item in ROTINAS.values():
            try:
                item.executar()
            except Exception as erro:
                falhas.append(item.nome)
                self.stderr.write(f"{item.nome}: falhou ({erro})")
            else:
                self.stdout.write(self.style.SUCCESS(f"{item.nome}: ok"))
        if falhas:
            raise CommandError(f"Rotinas com falha: {', '.join(falhas)}.")

    def _registrar_execucao(self, evento: JobExecutionEvent) -> None:
        hora = timezone.localtime().strftime("%d/%m %H:%M:%S")
        if evento.exception:
            self.stderr.write(f"[{hora}] {evento.job_id}: falhou ({evento.exception})")
        else:
            self.stdout.write(f"[{hora}] {evento.job_id}: ok")
