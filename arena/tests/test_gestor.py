"""Portal do Gestor (ArenaManager): acesso, dashboard, agenda, financeiro e configurações."""

from datetime import time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from arena import gestao
from arena.models import (
    Booking,
    Court,
    CustomUser,
    OpenMatch,
    StatusHorario,
    StatusPagamento,
    StatusPartida,
    TimeSlot,
    TipoReserva,
)

from .fabricas import amanha, criar_arena, criar_gestor, criar_horario, criar_jogador, criar_partida, criar_quadra


class AcessoPortalTest(TestCase):
    def test_anonimo_vai_para_o_login_do_portal(self):
        resposta = self.client.get(reverse("gestor:dashboard"))
        self.assertRedirects(resposta, f"{reverse('gestor:login')}?next={reverse('gestor:dashboard')}")

    def test_jogador_recebe_acesso_restrito(self):
        self.client.force_login(criar_jogador())
        resposta = self.client.get(reverse("gestor:dashboard"))
        self.assertEqual(resposta.status_code, 403)
        self.assertContains(resposta, "Acesso restrito a gestores", status_code=403)

    def test_gestor_sem_arena(self):
        self.client.force_login(criar_gestor())
        resposta = self.client.get(reverse("gestor:agenda"))
        self.assertContains(resposta, "Nenhuma arena vinculada", status_code=403)

    def test_login_leva_ao_dashboard(self):
        gestor = criar_gestor(username="gestora", password="Senha-forte-2026")
        criar_arena(gestor)
        resposta = self.client.post(
            reverse("gestor:login"), {"username": "gestora", "password": "Senha-forte-2026"}
        )
        self.assertRedirects(resposta, reverse("gestor:dashboard"))

    def test_superusuario_escolhe_a_arena(self):
        admin = CustomUser.objects.create_superuser("root", "root@example.com", None)
        primeira, segunda = criar_arena(nome="Arena A"), criar_arena(nome="Arena B")
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse("gestor:dashboard")).context["arena"], primeira)
        resposta = self.client.get(reverse("gestor:dashboard"), {"arena": segunda.slug})
        self.assertEqual(resposta.context["arena"], segunda)
        # A escolha fica na sessão.
        self.assertEqual(self.client.get(reverse("gestor:agenda")).context["arena"], segunda)


class PortalBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.gestor = criar_gestor()
        cls.arena = criar_arena(cls.gestor, hora_abertura=time(18), hora_fechamento=time(22))
        cls.quadra = criar_quadra(cls.arena, capacidade_padrao=10)
        cls.outro_gestor = criar_gestor()
        cls.quadra_alheia = criar_quadra(criar_arena(cls.outro_gestor))

    def setUp(self):
        self.client.force_login(self.gestor)


class DashboardTest(PortalBase):
    def test_indicadores_e_proximas_partidas(self):
        criar_horario(self.quadra, time(18), time(19), tipo_reserva=TipoReserva.MENSALISTA)
        partida = criar_partida(
            vagas=4,
            horario=criar_horario(self.quadra, time(19), time(20), status=StatusHorario.OCIOSO),
            preco_por_vaga=Decimal("30.00"),
        )
        Booking.objects.create(open_match=partida, player=criar_jogador(), status_pagamento=StatusPagamento.PAGO)
        Booking.objects.create(open_match=partida, player=criar_jogador())

        resposta = self.client.get(reverse("gestor:dashboard"))
        self.assertEqual(resposta.status_code, 200)
        indicadores = resposta.context["indicadores"]
        if partida.time_slot.data.month == timezone.localdate().month:
            self.assertEqual(indicadores.recebido_mes, Decimal("30.00"))
        self.assertEqual(indicadores.a_receber, Decimal("30.00"))
        self.assertEqual(indicadores.horarios_mensalistas, 1)
        self.assertGreater(indicadores.horarios_vagos, 0)
        self.assertEqual(indicadores.potencial_por_horario, Decimal("300.00"))

        resumo = resposta.context["proximas"][0]
        self.assertEqual((resumo.arrecadado, resumo.a_receber), (Decimal("30.00"), Decimal("30.00")))
        self.assertContains(resposta, "Próximas partidas abertas")


class AgendaTest(PortalBase):
    def test_grade_semanal_identifica_os_status(self):
        dia = amanha()
        criar_horario(self.quadra, time(18), time(19), data=dia, tipo_reserva=TipoReserva.MENSALISTA)
        criar_partida(horario=criar_horario(self.quadra, time(19), time(20), data=dia, status=StatusHorario.OCIOSO))
        resposta = self.client.get(reverse("gestor:agenda"), {"semana": dia.isoformat()})
        self.assertEqual(resposta.status_code, 200)

        linhas = resposta.context["linhas"]
        self.assertEqual([linha.inicio for linha in linhas], [time(18), time(19), time(20), time(21)])
        coluna = resposta.context["dias"].index(dia)
        tipos = [linha.celulas[coluna].tipo for linha in linhas]
        self.assertEqual(tipos, ["mensalista", "partida", "vago", "vago"])
        self.assertContains(resposta, "Transformar em Partida Aberta")
        self.assertContains(resposta, "bg-blue-100 text-blue-800")

    def test_semana_invalida_usa_a_semana_atual(self):
        resposta = self.client.get(reverse("gestor:agenda"), {"semana": "2026-13-45"})
        self.assertEqual(resposta.context["dias"][0], gestao.inicio_da_semana(timezone.localdate()))

    def test_transformar_horario_vazio_em_partida(self):
        dia = amanha()
        resposta = self.client.post(
            reverse("gestor:abrir_partida"),
            {
                "quadra": self.quadra.pk,
                "dia": dia.isoformat(),
                "hora_inicio": "20:00",
                "hora_fim": "21:00",
                "preco_por_vaga": "27,50",
                "nivel_competitividade": "avancado",
                "vagas_totais": "",
                "voltar": f"{reverse('gestor:agenda')}?semana={dia.isoformat()}",
            },
            follow=True,
        )
        self.assertContains(resposta, "Partida aberta publicada no app")
        partida = OpenMatch.objects.get()
        self.assertEqual(partida.time_slot.status, StatusHorario.OCIOSO)
        self.assertEqual(
            (partida.vagas_totais, partida.preco_por_vaga, partida.status),
            (10, Decimal("27.50"), StatusPartida.ABERTA),
        )

    def test_reabre_partida_cancelada_e_recusa_horario_reservado(self):
        horario = criar_horario(self.quadra, time(20), time(21), status=StatusHorario.OCIOSO)
        cancelada = criar_partida(horario=horario)
        cancelada.status = StatusPartida.CANCELADA
        cancelada.save()
        gestao.abrir_partida(self.quadra, horario.data, time(20), time(21), Decimal("20"), "misto")
        cancelada.refresh_from_db()
        self.assertEqual(cancelada.status, StatusPartida.ABERTA)

        criar_horario(self.quadra, time(18), time(19), tipo_reserva=TipoReserva.MENSALISTA)
        with self.assertRaisesMessage(Exception, "já está reservado"):
            gestao.abrir_partida(self.quadra, amanha(), time(18), time(19), Decimal("20"), "misto")

    def test_nao_abre_partida_em_quadra_de_outro_gestor(self):
        self.client.post(
            reverse("gestor:abrir_partida"),
            {
                "quadra": self.quadra_alheia.pk,
                "dia": amanha().isoformat(),
                "hora_inicio": "19:00",
                "hora_fim": "20:00",
                "preco_por_vaga": "20",
                "nivel_competitividade": "misto",
            },
        )
        self.assertFalse(OpenMatch.objects.exists())
        self.assertFalse(TimeSlot.objects.exists())

    def test_nao_abre_partida_no_passado(self):
        ontem = timezone.localdate() - timedelta(days=1)
        with self.assertRaisesMessage(Exception, "já começou"):
            gestao.abrir_partida(self.quadra, ontem, time(19), time(20), Decimal("20"), "misto")


class FinanceiroTest(PortalBase):
    def setUp(self):
        super().setUp()
        self.partida = criar_partida(vagas=3, horario=criar_horario(self.quadra, status=StatusHorario.OCIOSO))
        self.inscricao = Booking.objects.create(open_match=self.partida, player=criar_jogador())

    def test_lista_apenas_inscricoes_da_arena(self):
        alheia = criar_partida(horario=criar_horario(self.quadra_alheia, status=StatusHorario.OCIOSO))
        Booking.objects.create(open_match=alheia, player=criar_jogador())
        resposta = self.client.get(reverse("gestor:financeiro"))
        self.assertEqual(list(resposta.context["pagina"].object_list), [self.inscricao])
        filtrada = self.client.get(reverse("gestor:financeiro"), {"status": "pago"})
        self.assertEqual(list(filtrada.context["pagina"].object_list), [])

    def test_marcar_pago_e_reembolsar(self):
        url = reverse("gestor:pagamento", args=[self.inscricao.pk])
        self.client.post(url, {"status": "pago"})
        self.inscricao.refresh_from_db()
        self.assertEqual(self.inscricao.status_pagamento, StatusPagamento.PAGO)

        self.client.post(url, {"status": "reembolsado"})
        self.inscricao.refresh_from_db()
        self.partida.refresh_from_db()
        self.assertEqual(self.inscricao.status_pagamento, StatusPagamento.REEMBOLSADO)
        self.assertEqual(self.partida.vagas_disponiveis, 3)

    def test_transicao_invalida_e_inscricao_alheia(self):
        resposta = self.client.post(
            reverse("gestor:pagamento", args=[self.inscricao.pk]), {"status": "reembolsado"}, follow=True
        )
        self.assertContains(resposta, "Não é possível mudar o pagamento")
        self.client.force_login(self.outro_gestor)
        resposta = self.client.post(reverse("gestor:pagamento", args=[self.inscricao.pk]), {"status": "pago"})
        self.assertEqual(resposta.status_code, 404)


class ConfiguracoesTest(PortalBase):
    def test_atualiza_arena_e_cadastra_quadra(self):
        url = reverse("gestor:configuracoes")
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(
            url,
            {
                "salvar_arena": "1",
                "nome": "Arena Renovada",
                "telefone_contato": "(11) 3000-9999",
                "endereco_completo": "Rua Nova, 10 – Centro, São Paulo – SP",
                "hora_abertura": "17:00",
                "hora_fechamento": "23:00",
            },
        )
        self.arena.refresh_from_db()
        self.assertEqual((self.arena.nome, self.arena.hora_abertura), ("Arena Renovada", time(17)))

        self.client.post(url, {"adicionar_quadra": "1", "nome_ou_numero": "Quadra Nova", "tipo_piso": "areia", "capacidade_padrao": "10"})
        self.assertTrue(Court.objects.filter(arena=self.arena, nome_ou_numero="Quadra Nova").exists())

    def test_quadra_duplicada_mostra_erro(self):
        resposta = self.client.post(
            reverse("gestor:configuracoes"),
            {"adicionar_quadra": "1", "nome_ou_numero": self.quadra.nome_ou_numero, "tipo_piso": "sintetico", "capacidade_padrao": "14"},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context["form_quadra"].errors)
