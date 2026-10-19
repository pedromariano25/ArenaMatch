"""Pelada de grupo (C2C): preço, divisão do pagamento, goleiro de aluguel, carteira e telas."""

from datetime import time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from arena import gestao, partidas, peladas, razao
from arena.models import (
    LedgerEntry,
    MetodoPagamento,
    MotivoCancelamento,
    OpenMatch,
    Posicao,
    Saque,
    StatusHorario,
    StatusInscricao,
    StatusPartida,
    TipoChavePix,
    TipoConta,
    TipoLancamento,
    TipoReserva,
    Wallet,
)

from .fabricas import amanha, comprar, criar_arena, criar_gestor, criar_horario, criar_jogador, criar_quadra, mover_partida


class PeladaBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.gestor = criar_gestor()
        cls.arena = criar_arena(cls.gestor)
        cls.quadra = criar_quadra(cls.arena)
        cls.organizador = criar_jogador()

    def criar(self, **dados) -> OpenMatch:
        valores = {
            "titulo": "Pelada da Firma",
            "vagas_linha": 2,
            "valor_por_vaga": Decimal("15.00"),
        } | dados
        return peladas.criar_pelada(self.organizador, self.quadra, amanha(), time(20), time(21), **valores)


class PrecoEDivisaoTest(PeladaBase):
    def test_jogador_paga_vinte_e_organizador_recebe_quinze(self):
        pelada = self.criar()
        self.assertTrue(pelada.pelada_de_grupo)
        self.assertEqual((pelada.preco_vaga_base, pelada.valor_taxa_vaga, pelada.preco_final_jogador), (Decimal("15.00"), Decimal("5.00"), Decimal("20.00")))
        # Acima do mínimo, vale o percentual: R$ 30 + 20% = R$ 36.
        caro = peladas.criar_pelada(
            self.organizador, self.quadra, amanha(), time(21), time(22), titulo="Caro", vagas_linha=1, valor_por_vaga=Decimal("30")
        )
        self.assertEqual(caro.preco_final_jogador, Decimal("36.00"))

    def test_valor_da_vaga_vai_para_o_organizador_e_a_taxa_para_a_plataforma(self):
        pelada = self.criar()
        inscricao = comprar(pelada)
        self.assertEqual(inscricao.status, StatusInscricao.CONFIRMADA)

        lancamentos = LedgerEntry.objects.filter(inscricao=inscricao, tipo__in=(TipoLancamento.VENDA_VAGA, TipoLancamento.TAXA_SERVICO))
        por_conta = {(item.conta.tipo, item.tipo): item.valor for item in lancamentos.select_related("conta")}
        self.assertEqual(
            por_conta,
            {
                (TipoConta.ORGANIZADOR, TipoLancamento.VENDA_VAGA): Decimal("15.00"),
                (TipoConta.PLATAFORMA, TipoLancamento.TAXA_SERVICO): Decimal("5.00"),
            },
        )
        self.assertFalse(LedgerEntry.objects.filter(conta__tipo=TipoConta.ARENA).exists())
        saldo = razao.saldo_do_organizador(self.organizador)
        self.assertEqual((saldo.disponivel, saldo.a_liberar), (Decimal("0"), Decimal("15.00")))

    def test_cartao_tem_o_acrescimo_e_o_organizador_recebe_o_mesmo(self):
        pelada = self.criar()
        inscricao = comprar(pelada, metodo=MetodoPagamento.CARTAO)
        self.assertEqual(inscricao.valor_total, Decimal("21.00"))
        self.assertEqual(inscricao.valor_vaga, Decimal("15.00"))


class GoleiroDeAluguelTest(PeladaBase):
    def test_goleiro_pago_tem_preco_proprio_sem_taxa_minima(self):
        pelada = self.criar(vagas_goleiro=1, valor_goleiro=Decimal("10.00"))
        self.assertEqual((pelada.preco_goleiro, pelada.valor_taxa_goleiro), (Decimal("12.00"), Decimal("2.00")))
        goleiro = comprar(pelada, posicao=Posicao.GOLEIRO)
        self.assertFalse(goleiro.gratuita)
        self.assertEqual((goleiro.valor_vaga, goleiro.valor_taxa, goleiro.valor_total), (Decimal("10.00"), Decimal("2.00"), Decimal("12.00")))
        self.assertEqual(razao.saldo_do_organizador(self.organizador).a_liberar, Decimal("10.00"))

    def test_goleiro_gratis_continua_sem_pagamento(self):
        pelada = self.criar(vagas_goleiro=1)
        goleiro = comprar(pelada, posicao=Posicao.GOLEIRO)
        self.assertTrue(goleiro.gratuita)
        self.assertEqual(goleiro.valor_total, Decimal("0"))

    def test_partida_da_arena_continua_com_goleiro_gratis(self):
        partida = gestao.abrir_partida(self.quadra, amanha(), time(18), time(19), Decimal("240"), "aberta", 14)
        self.assertTrue(partida.goleiro_gratis)
        self.assertTrue(comprar(partida, posicao=Posicao.GOLEIRO).gratuita)


class RegrasDaPeladaTest(PeladaBase):
    def test_nao_e_cancelada_por_falta_de_quorum(self):
        pelada = self.criar()
        mover_partida(pelada, timezone.now() + timedelta(hours=2))  # já passou do prazo do mínimo
        partidas.conferir_quorum()
        pelada.refresh_from_db()
        self.assertEqual(pelada.status, StatusPartida.ABERTA)
        self.assertIsNotNone(pelada.quorum_conferido_em)

    def test_usa_o_horario_de_mensalista_cadastrado_pela_arena(self):
        horario = criar_horario(self.quadra, time(20), time(21), tipo_reserva=TipoReserva.MENSALISTA)
        pelada = self.criar()
        self.assertEqual(pelada.time_slot, horario)

    def test_sem_horario_cadastrado_cria_o_do_grupo(self):
        pelada = self.criar()
        horario = pelada.time_slot
        self.assertEqual((horario.tipo_reserva, horario.status), (TipoReserva.MENSALISTA, StatusHorario.CONFIRMADO))

    def test_recusa_horario_avulso_bloqueado_ou_ocupado(self):
        criar_horario(self.quadra, time(20), time(21), tipo_reserva=TipoReserva.AVULSO)
        with self.assertRaisesMessage(ValidationError, "não está reservado para um grupo"):
            self.criar()
        criar_horario(self.quadra, time(18), time(20))  # 18h-20h
        with self.assertRaises(ValidationError):
            peladas.criar_pelada(self.organizador, self.quadra, amanha(), time(19), time(20), titulo="X", vagas_linha=1, valor_por_vaga=Decimal("10"))

    def test_recusa_horario_passado_e_longe_demais(self):
        ontem = timezone.localdate() - timedelta(days=1)
        with self.assertRaisesMessage(ValidationError, "já começou"):
            peladas.criar_pelada(self.organizador, self.quadra, ontem, time(20), time(21), titulo="X", vagas_linha=1, valor_por_vaga=Decimal("10"))
        longe = timezone.localdate() + timedelta(days=40)
        with self.assertRaisesMessage(ValidationError, "antecedência"):
            peladas.criar_pelada(self.organizador, self.quadra, longe, time(20), time(21), titulo="X", vagas_linha=1, valor_por_vaga=Decimal("10"))

    def test_organizador_nao_compra_vaga_na_propria_pelada(self):
        pelada = self.criar()
        with self.assertRaisesMessage(ValidationError, "Você organiza esta pelada"):
            comprar(pelada, jogador=self.organizador)

    def test_cancelar_reembolsa_e_so_o_organizador_pode(self):
        pelada = self.criar()
        inscricao = comprar(pelada)
        with self.assertRaises(ValidationError):
            peladas.cancelar_pelada(pelada, criar_jogador())
        self.assertEqual(peladas.cancelar_pelada(pelada, self.organizador), 1)
        pelada.refresh_from_db()
        inscricao.refresh_from_db()
        self.assertEqual((pelada.status, pelada.motivo_cancelamento), (StatusPartida.CANCELADA, MotivoCancelamento.ORGANIZADOR))
        self.assertEqual(inscricao.status, StatusInscricao.REEMBOLSADA)
        self.assertEqual(razao.saldo_do_organizador(self.organizador).a_liberar, Decimal("0"))

    def test_reabre_a_pelada_cancelada_no_mesmo_horario(self):
        pelada = self.criar()
        peladas.cancelar_pelada(pelada, self.organizador)
        reaberta = self.criar(vagas_linha=3)
        self.assertEqual(reaberta.pk, pelada.pk)
        self.assertEqual((reaberta.status, reaberta.vagas_totais), (StatusPartida.ABERTA, 3))


class SaqueTest(PeladaBase):
    def setUp(self):
        self.pelada = self.criar()
        comprar(self.pelada)
        partidas.finalizar_partidas(self.pelada.time_slot.fim + timedelta(minutes=1))
        self.depois = self.pelada.time_slot.fim + timedelta(days=1, minutes=1)

    def test_exige_chave_pix_e_saldo_minimo(self):
        with self.assertRaisesMessage(ValidationError, "chave Pix"):
            razao.solicitar_saque(self.organizador, self.depois)
        Wallet.objects.create(usuario=self.organizador, tipo_chave_pix=TipoChavePix.EMAIL, chave_pix="org@example.com")
        with self.assertRaisesMessage(ValidationError, "saque mínimo"):
            razao.solicitar_saque(self.organizador)  # antes de liberar: R$ 0,00 disponível

    def test_saca_todo_o_saldo_liberado(self):
        Wallet.objects.create(usuario=self.organizador, tipo_chave_pix=TipoChavePix.EMAIL, chave_pix="org@example.com")
        saque = razao.solicitar_saque(self.organizador, self.depois)
        self.assertEqual((saque.valor, saque.chave_pix), (Decimal("15.00"), "org@example.com"))
        saldo = razao.saldo_do_organizador(self.organizador, self.depois)
        self.assertEqual((saldo.disponivel, saldo.sacado), (Decimal("0"), Decimal("15.00")))
        self.assertEqual(Saque.objects.count(), 1)

    def test_repasse_automatico_das_arenas_nao_toca_no_saldo_do_organizador(self):
        razao.gerar_repasses(self.depois)
        self.assertEqual(razao.saldo_do_organizador(self.organizador, self.depois).disponivel, Decimal("15.00"))


class PortalDaArenaTest(PeladaBase):
    def test_agenda_mostra_a_pelada_de_grupo_e_ela_nao_conta_nas_vendas_da_arena(self):
        pelada = self.criar()
        comprar(pelada)
        self.client.force_login(self.gestor)
        resposta = self.client.get(reverse("gestor:agenda"), {"semana": amanha().isoformat()})
        celulas = [c for linha in resposta.context["linhas"] for c in linha.celulas if c.partida == pelada]
        self.assertEqual([c.tipo for c in celulas], ["pelada"])
        self.assertContains(resposta, "Pelada de grupo")
        painel = self.client.get(reverse("gestor:dashboard"))
        self.assertEqual(painel.context["indicadores"].vagas_vendidas_mes, 0)


class TelasDoOrganizadorTest(PeladaBase):
    def setUp(self):
        self.client.force_login(self.organizador)

    def test_publicar_vagas_pelo_app(self):
        resposta = self.client.post(
            reverse("arena:nova_pelada"),
            {
                "titulo": "Racha de Terça",
                "quadra": self.quadra.pk,
                "dia": amanha().isoformat(),
                "hora_inicio": "21:00",
                "hora_fim": "22:00",
                "vagas_linha": "3",
                "valor_por_vaga": "15,00",
                "vagas_goleiro": "1",
                "valor_goleiro": "10,00",
                "nivel": "aberta",
            },
        )
        pelada = OpenMatch.objects.get(titulo="Racha de Terça")
        self.assertRedirects(resposta, pelada.get_absolute_url())
        self.assertEqual((pelada.organizador, pelada.vagas_totais, pelada.vagas_goleiro), (self.organizador, 4, 1))
        self.assertEqual((pelada.preco_final_jogador, pelada.preco_goleiro), (Decimal("20.00"), Decimal("12.00")))
        pagina = self.client.get(pelada.get_absolute_url())
        self.assertContains(pagina, "Esta é a sua pelada")

    def test_painel_do_organizador_e_chave_pix(self):
        self.criar()
        resposta = self.client.get(reverse("arena:organizar"))
        self.assertContains(resposta, "Pelada da Firma")
        self.assertContains(resposta, "Cadastre a sua chave Pix")
        invalida = self.client.post(reverse("arena:organizar"), {"tipo_chave_pix": "cpf", "chave_pix": "111.111.111-11"})
        self.assertTrue(invalida.context["form_pix"].errors)
        self.client.post(reverse("arena:organizar"), {"tipo_chave_pix": "celular", "chave_pix": "(11) 91234-5678"})
        self.assertEqual(Wallet.objects.get(usuario=self.organizador).chave_pix, "+5511912345678")

    def test_outro_jogador_nao_cancela_a_pelada(self):
        pelada = self.criar()
        self.client.force_login(criar_jogador())
        resposta = self.client.post(reverse("arena:cancelar_pelada", args=[pelada.pk]))
        self.assertEqual(resposta.status_code, 404)


class FeedEApiTest(PeladaBase):
    def test_feed_diferencia_arena_e_pelada_e_filtra_pela_origem(self):
        pelada = self.criar()
        partida = gestao.abrir_partida(self.quadra, amanha(), time(18), time(19), Decimal("240"), "aberta", 14)
        feed = self.client.get(reverse("arena:vitrine"))
        self.assertContains(feed, "Pelada de grupo · por")
        self.assertContains(feed, "Arena parceira")
        so_peladas = self.client.get(reverse("arena:vitrine"), {"origem": "pelada"})
        self.assertEqual([p.pk for p in so_peladas.context["partidas"]], [pelada.pk])
        so_arenas = self.client.get(reverse("arena:vitrine"), {"origem": "arena"})
        self.assertEqual([p.pk for p in so_arenas.context["partidas"]], [partida.pk])

    def test_api_informa_a_origem_e_o_organizador(self):
        self.criar(vagas_goleiro=1, valor_goleiro=Decimal("10.00"))
        dados = self.client.get(reverse("api:partidas")).json()["results"][0]
        self.assertEqual((dados["origem"], dados["titulo"]), ("pelada", "Pelada da Firma"))
        self.assertEqual(dados["organizador"], self.organizador.nome_publico)
        self.assertEqual(dados["precos"]["goleiro"], "12.00")
