"""Vitrine web B2C: feed, detalhes, reserva, comprovante, cancelamento e cadastro."""

from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from arena.models import Booking, CustomUser, NivelCompetitividade, StatusPagamento

from .fabricas import criar_gestor, criar_jogador, criar_partida


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
        self.assertContains(resposta, "Reservar minha vaga")
        self.assertContains(resposta, "R$ 25,00")


class ReservaTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.jogador = criar_jogador()
        cls.partida = criar_partida(vagas=1)
        cls.url_reserva = reverse("arena:reservar", args=[cls.partida.pk])

    def test_reserva_exige_login(self):
        resposta = self.client.get(self.url_reserva)
        self.assertRedirects(resposta, f"{reverse('arena:entrar')}?next={self.url_reserva}")

    def test_confirmacao_e_criacao_da_inscricao(self):
        self.client.force_login(self.jogador)
        self.assertContains(self.client.get(self.url_reserva), "Confirmar reserva")

        resposta = self.client.post(self.url_reserva)
        inscricao = Booking.objects.get(player=self.jogador)
        self.assertRedirects(resposta, reverse("arena:inscricao", args=[inscricao.pk]))
        comprovante = self.client.get(resposta.url)
        self.assertContains(comprovante, "Vaga garantida!")
        self.assertContains(comprovante, "calendar.google.com")
        self.partida.refresh_from_db()
        self.assertEqual(self.partida.vagas_disponiveis, 0)

    def test_partida_lotada_mostra_mensagem(self):
        Booking.objects.create(open_match=self.partida, player=criar_jogador())
        self.client.force_login(self.jogador)
        resposta = self.client.post(self.url_reserva, follow=True)
        self.assertRedirects(resposta, self.partida.get_absolute_url())
        mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
        self.assertIn("Esta partida está lotada.", mensagens)

    def test_conta_que_nao_e_jogador_e_avisada(self):
        self.client.force_login(criar_gestor())
        resposta = self.client.get(self.url_reserva, follow=True)
        self.assertContains(resposta, "Sua conta não é de jogador")
        self.assertFalse(Booking.objects.exists())

    def test_comprovante_de_outro_jogador_e_404(self):
        inscricao = Booking.objects.create(open_match=self.partida, player=criar_jogador())
        self.client.force_login(self.jogador)
        self.assertEqual(self.client.get(reverse("arena:inscricao", args=[inscricao.pk])).status_code, 404)

    def test_cancelar_e_minhas_inscricoes(self):
        inscricao = Booking.objects.create(open_match=self.partida, player=self.jogador)
        self.client.force_login(self.jogador)
        self.assertContains(self.client.get(reverse("arena:minhas_inscricoes")), self.partida.time_slot.intervalo)

        resposta = self.client.post(reverse("arena:cancelar_inscricao", args=[inscricao.pk]))
        self.assertRedirects(resposta, reverse("arena:minhas_inscricoes"))
        self.assertFalse(Booking.objects.exists())

    def test_inscricao_paga_nao_pode_ser_cancelada(self):
        inscricao = Booking.objects.create(
            open_match=self.partida, player=self.jogador, status_pagamento=StatusPagamento.PAGO
        )
        self.client.force_login(self.jogador)
        self.client.post(reverse("arena:cancelar_inscricao", args=[inscricao.pk]))
        self.assertTrue(Booking.objects.filter(pk=inscricao.pk).exists())


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
        self.assertRedirects(resposta, destino)
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
        self.assertRedirects(resposta, reverse("arena:vitrine"))
