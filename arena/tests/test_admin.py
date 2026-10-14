"""Painel B2B: páginas do admin, escopo por gestor e actions customizadas."""

from datetime import time
from decimal import Decimal

from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from arena.models import Booking, CustomUser, OpenMatch, StatusHorario, StatusInscricao, StatusPartida

from .fabricas import comprar, criar_arena, criar_gestor, criar_horario, criar_jogador, criar_partida, criar_quadra

PERMISSOES_GESTOR = [
    "view_arena",
    "change_arena",
    *[f"{acao}_{modelo}" for modelo in ("court", "timeslot", "openmatch", "booking") for acao in ("view", "add", "change", "delete")],
]


class AdminSuperusuarioTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_superuser("root", "root@example.com", None)
        cls.partida = criar_partida(vagas=4)
        cls.inscricao = Booking.objects.create(open_match=cls.partida, player=criar_jogador())

    def setUp(self):
        self.client.force_login(self.admin)

    def test_paginas_carregam(self):
        urls = [
            reverse("admin:index"),
            *[reverse(f"admin:arena_{modelo}_changelist") for modelo in ("arena", "court", "timeslot", "openmatch", "booking", "customuser")],
            *[reverse(f"admin:arena_{modelo}_changelist") for modelo in ("payment", "ledgeraccount", "ledgerentry", "payout", "waitlistentry")],
            *[reverse(f"admin:arena_{modelo}_add") for modelo in ("arena", "court", "timeslot", "openmatch", "customuser")],
            reverse("admin:arena_openmatch_change", args=[self.partida.pk]),
            reverse("admin:arena_booking_change", args=[self.inscricao.pk]),
            reverse("admin:arena_arena_change", args=[self.partida.time_slot.court.arena_id]),
            reverse("admin:arena_timeslot_changelist") + "?periodo=amanha&status__exact=ocioso",
            reverse("admin:arena_openmatch_changelist") + "?periodo=futuros",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_painel_inicial_com_indicadores(self):
        resposta = self.client.get(reverse("admin:index"))
        self.assertContains(resposta, "Resumo dos próximos 7 dias")
        self.assertContains(resposta, '<span class="valor">1/4</span>', html=True)

    def test_inscricoes_sao_somente_leitura(self):
        self.assertEqual(self.client.get(reverse("admin:arena_booking_add")).status_code, 403)
        resposta = self.client.get(reverse("admin:arena_booking_change", args=[self.inscricao.pk]))
        self.assertNotContains(resposta, 'name="_save"')

    def test_action_cancelar_partidas_reembolsa(self):
        paga = comprar(self.partida)
        resposta = self.client.post(
            reverse("admin:arena_openmatch_changelist"),
            {"action": "cancelar_partidas", ACTION_CHECKBOX_NAME: [self.partida.pk]},
            follow=True,
        )
        self.assertContains(resposta, "1 jogador(es) reembolsado(s)")
        self.partida.refresh_from_db()
        paga.refresh_from_db()
        self.assertEqual((self.partida.status, paga.status), (StatusPartida.CANCELADA, StatusInscricao.REEMBOLSADA))


class AdminConversaoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_superuser("root", "root@example.com", None)
        cls.quadra = criar_quadra(capacidade_padrao=10)
        cls.ocioso = criar_horario(cls.quadra, time(19), time(20), status=StatusHorario.OCIOSO)
        cls.confirmado = criar_horario(cls.quadra, time(20), time(21), status=StatusHorario.CONFIRMADO)

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse("admin:arena_timeslot_changelist")
        self.selecao = {
            "action": "converter_para_partida_aberta",
            ACTION_CHECKBOX_NAME: [self.ocioso.pk, self.confirmado.pk],
        }

    def test_tela_intermediaria_lista_elegiveis(self):
        resposta = self.client.post(self.url, self.selecao)
        self.assertTemplateUsed(resposta, "admin/arena/timeslot/converter_partida_aberta.html")
        self.assertEqual(resposta.context["elegiveis"], [self.ocioso])
        self.assertEqual([h for h, _ in resposta.context["inelegiveis"]], [self.confirmado])
        self.assertFalse(OpenMatch.objects.exists())

    def test_aplicar_cria_partidas_com_capacidade_da_quadra(self):
        dados = self.selecao | {
            "aplicar": "1",
            "valor_total_aluguel": "275,00",
            "nivel_competitividade": "avancado",
            "vagas_totais": "",
        }
        resposta = self.client.post(self.url, dados, follow=True)
        self.assertContains(resposta, "1 partida(s) aberta(s) criada(s)")
        partida = OpenMatch.objects.get()
        self.assertEqual(partida.time_slot, self.ocioso)
        self.assertEqual(
            (partida.vagas_totais, partida.vagas_goleiro, partida.vagas_disponiveis, partida.valor_total_aluguel, partida.nivel_competitividade),
            (10, 2, 10, Decimal("275.00"), "avancado"),
        )


class AdminEscopoGestorTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        permissoes = Permission.objects.filter(content_type__app_label="arena", codename__in=PERMISSOES_GESTOR)
        cls.gestor = criar_gestor()
        cls.gestor.user_permissions.set(permissoes)
        cls.minha_arena = criar_arena(cls.gestor)
        cls.minha_quadra = criar_quadra(cls.minha_arena)
        cls.arena_alheia = criar_arena()
        cls.quadra_alheia = criar_quadra(cls.arena_alheia)
        criar_horario(cls.minha_quadra)
        criar_horario(cls.quadra_alheia)

    def setUp(self):
        self.client.force_login(self.gestor)

    def test_listagens_mostram_so_as_proprias_arenas(self):
        arenas = self.client.get(reverse("admin:arena_arena_changelist")).context["cl"].queryset
        self.assertEqual(list(arenas), [self.minha_arena])
        horarios = self.client.get(reverse("admin:arena_timeslot_changelist")).context["cl"].queryset
        self.assertEqual({h.court_id for h in horarios}, {self.minha_quadra.pk})

    def test_objeto_de_outro_gestor_inacessivel(self):
        resposta = self.client.get(reverse("admin:arena_arena_change", args=[self.arena_alheia.pk]))
        self.assertEqual(resposta.status_code, 302)

    def test_opcoes_de_quadra_restritas(self):
        form = self.client.get(reverse("admin:arena_timeslot_add")).context["adminform"].form
        self.assertEqual(list(form.fields["court"].queryset), [self.minha_quadra])

    def test_gestor_nao_ve_usuarios(self):
        self.assertEqual(self.client.get(reverse("admin:arena_customuser_changelist")).status_code, 403)

    def test_gestor_nao_troca_o_responsavel_da_arena(self):
        resposta = self.client.get(reverse("admin:arena_arena_change", args=[self.minha_arena.pk]))
        self.assertNotIn("manager", resposta.context["adminform"].form.fields)
