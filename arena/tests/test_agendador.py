"""Agendador de rotinas automáticas e comando ``agendador``."""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from arena.agendador import criar_agendador
from arena.rotinas import ROTINAS, Rotina


class AgendadorTest(TestCase):
    def test_agenda_todas_as_rotinas_registradas(self):
        tarefas = {tarefa.id: tarefa for tarefa in criar_agendador().get_jobs()}
        self.assertEqual(set(tarefas), set(ROTINAS))
        sessoes = tarefas["limpar_sessoes_expiradas"]
        self.assertEqual(sessoes.trigger.interval, timedelta(days=1))
        self.assertTrue(sessoes.coalesce)
        self.assertIsNone(sessoes.misfire_grace_time)
        self.assertEqual(sessoes.max_instances, 1)

    def test_uma_vez_executa_as_rotinas(self):
        agora = timezone.now()
        Session.objects.create(session_key="vencida", session_data="", expire_date=agora - timedelta(days=1))
        Session.objects.create(session_key="valida", session_data="", expire_date=agora + timedelta(days=1))
        saida = StringIO()
        call_command("agendador", uma_vez=True, stdout=saida)
        self.assertIn("limpar_sessoes_expiradas: ok", saida.getvalue())
        self.assertEqual(list(Session.objects.values_list("session_key", flat=True)), ["valida"])

    def test_rotina_com_erro_nao_impede_as_demais(self):
        executadas = []

        def falhar() -> None:
            raise RuntimeError("erro de propósito")

        rotinas = {
            "falhar": Rotina("falhar", falhar, 1, "Sempre falha."),
            "anotar": Rotina("anotar", lambda: executadas.append("anotar"), 1, "Registra a execução."),
        }
        erros = StringIO()
        with mock.patch.dict(ROTINAS, rotinas, clear=True):
            with self.assertRaisesMessage(CommandError, "Rotinas com falha: falhar."):
                call_command("agendador", uma_vez=True, stdout=StringIO(), stderr=erros)
        self.assertEqual(executadas, ["anotar"])
        self.assertIn("falhar: falhou (erro de propósito)", erros.getvalue())

    def test_recicla_so_conexoes_fora_de_transacao(self):
        livre = mock.Mock(in_atomic_block=False)
        em_transacao = mock.Mock(in_atomic_block=True)
        with mock.patch("arena.rotinas.connections.all", return_value=[livre, em_transacao]):
            Rotina("vazia", lambda: None, 1, "Não faz nada.").executar()
        self.assertEqual(livre.close_if_unusable_or_obsolete.call_count, 2)
        em_transacao.close_if_unusable_or_obsolete.assert_not_called()
