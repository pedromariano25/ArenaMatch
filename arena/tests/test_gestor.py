"""Portal do Gestor (ArenaManager): acesso, dashboard, agenda, financeiro e configurações."""

from datetime import time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from arena import gestao, partidas, razao
from arena.models import (
    Court,
    CustomUser,
    MetodoPagamento,
    OpenMatch,
    StatusHorario,
    StatusInscricao,
    StatusPartida,
    TimeSlot,
    TipoLancamento,
    TipoReserva,
)

from .fabricas import (
    amanha,
    comprar,
    criar_arena,
    criar_gestor,
    criar_horario,
    criar_jogador,
    criar_partida,
    criar_quadra,
)


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
            valor_total_aluguel=Decimal("120.00"),
        )
        comprar(partida)
        comprar(partida, pagar=False)  # Pix ainda pendente

        resposta = self.client.get(reverse("gestor:dashboard"))
        self.assertEqual(resposta.status_code, 200)
        indicadores = resposta.context["indicadores"]
        if partida.time_slot.data.month == timezone.localdate().month:
            self.assertEqual(indicadores.vendido_mes, Decimal("30.00"))
            self.assertEqual(indicadores.vagas_vendidas_mes, 1)
        self.assertEqual((indicadores.a_liberar, indicadores.disponivel), (Decimal("30.00"), Decimal("0")))
        self.assertEqual(indicadores.horarios_mensalistas, 1)
        self.assertGreater(indicadores.horarios_vagos, 0)
        self.assertEqual(indicadores.aluguel_por_horario, Decimal("120.00"))

        resumo = resposta.context["proximas"][0]
        self.assertEqual((resumo.garantido, resumo.em_pagamento), (Decimal("30.00"), Decimal("30.00")))
        self.assertContains(resposta, "Próximas partidas abertas")

    def test_cancelar_partida_reembolsa_os_jogadores(self):
        partida = criar_partida(vagas=4, horario=criar_horario(self.quadra, status=StatusHorario.OCIOSO))
        inscricao = comprar(partida)
        resposta = self.client.post(reverse("gestor:cancelar_partida", args=[partida.pk]), follow=True)
        self.assertContains(resposta, "1 jogador(es) reembolsado(s)")
        inscricao.refresh_from_db()
        self.assertEqual(inscricao.status, StatusInscricao.REEMBOLSADA)

    def test_nao_cancela_partida_de_outra_arena(self):
        alheia = criar_partida(horario=criar_horario(self.quadra_alheia, status=StatusHorario.OCIOSO))
        resposta = self.client.post(reverse("gestor:cancelar_partida", args=[alheia.pk]))
        self.assertEqual(resposta.status_code, 404)


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
                "valor_total_aluguel": "275,00",
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
            (partida.vagas_totais, partida.vagas_goleiro, partida.valor_total_aluguel, partida.status),
            (10, 2, Decimal("275.00"), StatusPartida.ABERTA),
        )
        self.assertEqual(partida.preco_final_jogador, Decimal("39.53"))  # 275 / 8 = 34,37 + 15%

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
                "valor_total_aluguel": "200",
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
        comprar(self.partida, metodo=MetodoPagamento.CARTAO)

    def test_extrato_e_saldo_da_carteira(self):
        alheia = criar_partida(horario=criar_horario(self.quadra_alheia, status=StatusHorario.OCIOSO))
        comprar(alheia)
        resposta = self.client.get(reverse("gestor:financeiro"))
        lancamentos = list(resposta.context["pagina"].object_list)
        self.assertEqual([(l.tipo, l.valor) for l in lancamentos], [(TipoLancamento.VENDA_VAGA, Decimal("25.00"))])
        self.assertEqual(resposta.context["resumo"]["a_liberar"], Decimal("25.00"))
        self.assertNotContains(resposta, "Marcar como pago")
        filtrada = self.client.get(reverse("gestor:financeiro"), {"tipo": "repasse"})
        self.assertEqual(list(filtrada.context["pagina"].object_list), [])

    def test_repasses_aparecem_no_historico(self):
        partidas.finalizar_partidas(self.partida.time_slot.fim + timedelta(minutes=1))
        razao.gerar_repasses(self.partida.time_slot.fim + timedelta(days=1, minutes=1))
        resposta = self.client.get(reverse("gestor:financeiro"))
        self.assertEqual([r.valor for r in resposta.context["repasses"]], [Decimal("25.00")])


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
                "quorum_percentual": "60",
                "horas_prazo_quorum": "4",
            },
        )
        self.arena.refresh_from_db()
        self.assertEqual(
            (self.arena.nome, self.arena.hora_abertura, self.arena.quorum_percentual), ("Arena Renovada", time(17), 60)
        )

        self.client.post(url, {"adicionar_quadra": "1", "nome_ou_numero": "Quadra Nova", "tipo_piso": "areia", "capacidade_padrao": "10"})
        self.assertTrue(Court.objects.filter(arena=self.arena, nome_ou_numero="Quadra Nova").exists())

    def test_quadra_duplicada_mostra_erro(self):
        resposta = self.client.post(
            reverse("gestor:configuracoes"),
            {"adicionar_quadra": "1", "nome_ou_numero": self.quadra.nome_ou_numero, "tipo_piso": "sintetico", "capacidade_padrao": "14"},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context["form_quadra"].errors)
