"""Vitrine web B2C: feed, detalhes, checkout, pagamento, comprovante, cancelamento e cadastro."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from arena import razao
from arena.models import Booking, CustomUser, NivelCompetitividade, StatusInscricao, WaitlistEntry

from .fabricas import comprar, criar_gestor, criar_jogador, criar_partida, mover_partida


class VitrineTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.partida = criar_partida(vagas=2, nivel_competitividade=NivelCompetitividade.INICIANTE)
        cls.arena = cls.partida.time_slot.court.arena

    def test_feed_lista_partidas_e_filtra(self):
        resposta = self.client.get(reverse("arena:vitrine"))
        self.assertContains(resposta, self.arena.nome)
        self.assertEqual(list(resposta.context["partidas"]), [self.partida])
        self.assertEqual(resposta.context["total_vagas"], 2)
        filtrada = self.client.get(reverse("arena:vitrine"), {"nivel": "avancado"})
        self.assertEqual(list(filtrada.context["partidas"]), [])
        self.assertContains(filtrada, "Nenhuma partida encontrada")

    def test_detalhe_da_partida(self):
        resposta = self.client.get(self.partida.get_absolute_url())
        self.assertContains(resposta, "Garantir vaga")
        # R$ 25,00 da quadra + 15% de taxa de serviço; no cartão, 5% a mais.
        self.assertContains(resposta, "R$ 28,75")
        self.assertContains(resposta, "R$ 30,19 no cartão")
        self.assertNotContains(resposta, "direto na arena")


class CheckoutTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.jogador = criar_jogador()
        cls.partida = criar_partida(vagas=3, vagas_goleiro=1)
        cls.url = reverse("arena:checkout", args=[cls.partida.pk])

    def test_exige_login(self):
        resposta = self.client.get(self.url)
        self.assertRedirects(resposta, f"{reverse('arena:entrar')}?next={self.url}")

    def test_pix_leva_ao_pagamento_e_a_simulacao_confirma(self):
        self.client.force_login(self.jogador)
        self.assertContains(self.client.get(self.url), "Garanta sua vaga")
        resposta = self.client.post(self.url, {"posicao": "linha", "metodo": "pix"})
        inscricao = Booking.objects.get(player=self.jogador)
        self.assertRedirects(resposta, reverse("arena:pagamento", args=[inscricao.pk]))
        pagina = self.client.get(resposta.url)
        self.assertContains(pagina, "Pix copia e cola")
        self.assertContains(pagina, "Simular pagamento aprovado")

        self.client.post(reverse("arena:simular_pagamento", args=[inscricao.pk]))
        comprovante = self.client.get(reverse("arena:inscricao", args=[inscricao.pk]))
        self.assertContains(comprovante, "Vaga garantida!")
        self.assertContains(comprovante, "calendar.google.com")

    def test_cartao_confirma_direto(self):
        self.client.force_login(self.jogador)
        resposta = self.client.post(self.url, {"posicao": "linha", "metodo": "cartao"})
        inscricao = Booking.objects.get(player=self.jogador)
        self.assertRedirects(resposta, reverse("arena:inscricao", args=[inscricao.pk]))
        self.assertEqual(inscricao.status, StatusInscricao.CONFIRMADA)

    def test_goleiro_nao_paga(self):
        self.client.force_login(self.jogador)
        self.client.post(self.url, {"posicao": "goleiro"})
        inscricao = Booking.objects.get(player=self.jogador)
        self.assertEqual((inscricao.status, inscricao.valor_total), (StatusInscricao.CONFIRMADA, Decimal("0")))

    def test_partida_lotada_mostra_mensagem(self):
        for _ in range(2):
            comprar(self.partida)
        self.client.force_login(self.jogador)
        resposta = self.client.post(self.url, {"posicao": "linha", "metodo": "pix"}, follow=True)
        mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
        self.assertIn("Esta partida está lotada.", mensagens)

    def test_conta_que_nao_e_jogador_e_avisada(self):
        self.client.force_login(criar_gestor())
        resposta = self.client.get(self.url, follow=True)
        self.assertContains(resposta, "Sua conta não é de jogador")
        self.assertFalse(Booking.objects.exists())

    def test_comprovante_de_outro_jogador_e_404(self):
        inscricao = comprar(self.partida)
        self.client.force_login(self.jogador)
        self.assertEqual(self.client.get(reverse("arena:inscricao", args=[inscricao.pk])).status_code, 404)


class CancelamentoWebTest(TestCase):
    def setUp(self):
        self.jogador = criar_jogador()
        self.partida = criar_partida(vagas=2)
        mover_partida(self.partida, timezone.now() + timedelta(days=2))
        self.client.force_login(self.jogador)

    def test_cancelar_vira_credito_e_aparece_em_minhas_inscricoes(self):
        inscricao = comprar(self.partida, self.jogador)
        self.assertContains(self.client.get(reverse("arena:minhas_inscricoes")), self.partida.time_slot.intervalo)
        resposta = self.client.post(reverse("arena:cancelar_inscricao", args=[inscricao.pk]))
        self.assertRedirects(resposta, reverse("arena:minhas_inscricoes"))
        self.assertEqual(razao.saldo_do_jogador(self.jogador), Decimal("28.75"))
        self.assertContains(self.client.get(reverse("arena:minhas_inscricoes")), "R$ 28,75")

    def test_perto_do_jogo_so_repassa(self):
        mover_partida(self.partida, timezone.now() + timedelta(hours=5))
        inscricao = comprar(self.partida, self.jogador)
        self.client.post(reverse("arena:cancelar_inscricao", args=[inscricao.pk]))
        inscricao.refresh_from_db()
        self.assertEqual(inscricao.status, StatusInscricao.CONFIRMADA)
        self.client.post(reverse("arena:repassar_vaga", args=[inscricao.pk]))
        inscricao.refresh_from_db()
        self.assertTrue(inscricao.em_repasse)

    def test_lista_de_espera_em_partida_lotada(self):
        comprar(self.partida)
        comprar(self.partida)
        url = reverse("arena:lista_de_espera", args=[self.partida.pk])
        self.assertContains(self.client.get(self.partida.get_absolute_url()), "Entrar na lista de espera")
        self.client.post(url)
        self.assertTrue(WaitlistEntry.objects.filter(jogador=self.jogador).exists())
        self.client.post(url, {"acao": "sair"})
        self.assertFalse(WaitlistEntry.objects.exists())


class ContaTest(TestCase):
    def test_paginas_de_entrar_e_cadastro(self):
        self.assertContains(self.client.get(reverse("arena:entrar")), "Bem-vindo de volta")
        self.assertContains(self.client.get(reverse("arena:cadastro")), "Crie sua conta de jogador")

    def test_cadastro_cria_jogador_logado_e_respeita_next(self):
        destino = reverse("arena:minhas_inscricoes")
        resposta = self.client.post(
            reverse("arena:cadastro"),
            {
                "first_name": "Bia",
                "last_name": "Rocha",
                "username": "bia.rocha",
                "email": "bia@example.com",
                "telefone": "",
                "password1": "Bola-na-rede-2026",
                "password2": "Bola-na-rede-2026",
                "next": destino,
            },
        )
        # Depois do cadastro vem o questionário de perfil, que leva ao destino pedido.
        self.assertRedirects(
            resposta, f"{reverse('arena:configurar_perfil')}?next={destino}", fetch_redirect_response=False
        )
        usuario = CustomUser.objects.get(username="bia.rocha")
        self.assertTrue(usuario.is_player)
        self.assertEqual(self.client.session["_auth_user_id"], str(usuario.pk))

    def test_cadastro_ignora_next_externo(self):
        resposta = self.client.post(
            reverse("arena:cadastro"),
            {
                "first_name": "Caio",
                "username": "caio",
                "email": "caio@example.com",
                "password1": "Bola-na-rede-2026",
                "password2": "Bola-na-rede-2026",
                "next": "https://site-malicioso.example.com/",
            },
        )
        self.assertRedirects(
            resposta, f"{reverse('arena:configurar_perfil')}?next={reverse('arena:vitrine')}", fetch_redirect_response=False
        )
