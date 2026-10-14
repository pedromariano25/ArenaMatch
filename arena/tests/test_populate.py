"""Comando populate_db (dados de demonstração)."""

from decimal import Decimal
from io import StringIO

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
