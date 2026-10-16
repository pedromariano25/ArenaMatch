"""Comando populate_db (dados de demonstração)."""

from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum
from django.test import TestCase, override_settings

from arena import razao
from arena.models import (
    Arena,
    Booking,
    Court,
    CustomUser,
    LedgerEntry,
    OpenMatch,
    StatusInscricao,
    StatusPartida,
    TipoConta,
    TipoLancamento,
)

HASHER_RAPIDO = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@override_settings(PASSWORD_HASHERS=HASHER_RAPIDO)
class PopulateDbTest(TestCase):
    def popular(self, dias: int = 1) -> str:
        saida = StringIO()
        call_command("populate_db", force=True, dias_de_historico=dias, stdout=saida)
        return saida.getvalue()

    def test_cria_cenario_de_demonstracao_completo(self):
        saida = self.popular()
        self.assertIn("Banco populado com sucesso", saida)
        self.assertEqual(Arena.objects.count(), 3)
        for arena in Arena.objects.all():
            self.assertGreaterEqual(arena.quadras.count(), 2)
        self.assertGreater(Court.objects.count(), 5)
        self.assertTrue(OpenMatch.objects.filter(status=StatusPartida.LOTADA).exists())
        self.assertTrue(OpenMatch.objects.filter(status=StatusPartida.FINALIZADA).exists())
        self.assertTrue(Booking.objects.filter(status=StatusInscricao.AGUARDANDO_PAGAMENTO).exists())

        admin = CustomUser.objects.get(username="admin")
        self.assertTrue(admin.is_superuser and admin.check_password("admin123"))
        gestor = CustomUser.objects.get(username="carlos.andrade")
        self.assertTrue(gestor.is_manager and gestor.check_password("gestor123"))
        self.assertTrue(gestor.groups.filter(name="Gestores").exists())
        self.assertTrue(Group.objects.get(name="Gestores").permissions.exists())
        self.assertTrue(CustomUser.objects.get(username="jogador").check_password("jogador123"))

    def test_razao_bate_com_as_inscricoes(self):
        self.popular()
        for arena in Arena.objects.all():
            vendas = razao.saldo(
                LedgerEntry.objects.filter(
                    conta__tipo=TipoConta.ARENA,
                    conta__arena=arena,
                    tipo__in=(TipoLancamento.VENDA_VAGA, TipoLancamento.ESTORNO),
                )
            )
            confirmadas = Booking.objects.filter(
                open_match__time_slot__court__arena=arena, status=StatusInscricao.CONFIRMADA
            ).aggregate(total=Sum("valor_vaga"))["total"] or Decimal("0")
            self.assertEqual(vendas, confirmadas)

    def test_rodar_de_novo_recria_os_dados(self):
        self.popular(dias=0)
        self.popular(dias=0)
        self.assertEqual(Arena.objects.count(), 3)
        self.assertFalse(OpenMatch.objects.filter(status=StatusPartida.FINALIZADA).exists())

    def test_recusa_rodar_sem_debug(self):
        with self.assertRaises(CommandError):
            call_command("populate_db", stdout=StringIO())

    def test_se_vazio_nao_mexe_num_banco_com_dados(self):
        self.popular(dias=0)
        partidas = OpenMatch.objects.count()
        saida = StringIO()
        call_command("populate_db", force=True, se_vazio=True, stdout=saida)
        self.assertIn("nada foi alterado", saida.getvalue())
        self.assertEqual(OpenMatch.objects.count(), partidas)

    def test_em_producao_exige_se_vazio_e_senha_forte(self):
        with mock.patch.dict("os.environ", {"ARENAMATCH_SENHA_DEMO": "curta"}):
            with self.assertRaisesMessage(CommandError, "ARENAMATCH_SENHA_DEMO"):
                call_command("populate_db", se_vazio=True, stdout=StringIO())
        self.assertFalse(Arena.objects.exists())

    def test_senha_de_demonstracao_vale_para_todas_as_contas(self):
        senha = "uma-senha-longa-do-render"
        with mock.patch.dict("os.environ", {"ARENAMATCH_SENHA_DEMO": senha}):
            saida = StringIO()
            call_command("populate_db", se_vazio=True, dias_de_historico=0, stdout=saida)
        for login in ("admin", "carlos.andrade", "jogador", "lucas.oliveira"):
            self.assertTrue(CustomUser.objects.get(username=login).check_password(senha), login)
        self.assertNotIn(senha, saida.getvalue())
        self.assertNotIn("admin123", saida.getvalue())

    def test_partidas_abertas_suficientes_para_a_vitrine(self):
        self.popular(dias=0)
        abertas = OpenMatch.objects.futuras().filter(status=StatusPartida.ABERTA)
        self.assertGreaterEqual(abertas.count(), 15)
