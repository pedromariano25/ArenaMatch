"""Comando populate_db (dados de demonstração)."""

from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from arena.models import Arena, Booking, Court, CustomUser, OpenMatch, StatusPartida

HASHER_RAPIDO = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@override_settings(PASSWORD_HASHERS=HASHER_RAPIDO)
class PopulateDbTest(TestCase):
    def popular(self) -> str:
        saida = StringIO()
        call_command("populate_db", force=True, stdout=saida)
        return saida.getvalue()

    def test_cria_cenario_de_demonstracao_completo(self):
        saida = self.popular()
        self.assertIn("Banco populado com sucesso", saida)
        self.assertEqual(Arena.objects.count(), 3)
        for arena in Arena.objects.all():
            self.assertGreaterEqual(arena.quadras.count(), 2)
        self.assertTrue(15 <= OpenMatch.objects.count() <= 20)
        self.assertTrue(OpenMatch.objects.filter(status=StatusPartida.LOTADA).exists())
        self.assertEqual(OpenMatch.objects.values("nivel_competitividade").distinct().count(), 3)
        self.assertGreater(Court.objects.count(), 5)

        admin = CustomUser.objects.get(username="admin")
        self.assertTrue(admin.is_superuser and admin.check_password("admin123"))
        gestor = CustomUser.objects.get(username="carlos.andrade")
        self.assertTrue(gestor.is_manager and gestor.check_password("gestor123"))
        self.assertTrue(gestor.groups.filter(name="Gestores").exists())
        self.assertTrue(Group.objects.get(name="Gestores").permissions.exists())
        self.assertTrue(CustomUser.objects.get(username="jogador").check_password("jogador123"))

    def test_rodar_de_novo_recria_os_dados_e_mantem_o_recalculo_de_vagas(self):
        self.popular()
        self.popular()
        self.assertEqual(Arena.objects.count(), 3)
        inscricao = Booking.objects.filter(open_match__status=StatusPartida.ABERTA).first()
        partida = inscricao.open_match
        livres = partida.vagas_disponiveis
        inscricao.delete()
        partida.refresh_from_db()
        self.assertEqual(partida.vagas_disponiveis, livres + 1)

    def test_recusa_rodar_sem_debug(self):
        with self.assertRaises(CommandError):
            call_command("populate_db", stdout=StringIO())
