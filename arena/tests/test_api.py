"""APIs B2C (Django REST Framework)."""

from datetime import time, timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from arena.models import Booking, CustomUser, NivelCompetitividade, StatusHorario, StatusPagamento, TimeSlot

from .fabricas import amanha, criar_gestor, criar_horario, criar_jogador, criar_partida, criar_quadra


class ApiPartidasTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.quadra = criar_quadra()
        cls.partida = criar_partida(
            vagas=3,
            horario=criar_horario(cls.quadra, time(19), time(20), status=StatusHorario.OCIOSO),
            nivel_competitividade=NivelCompetitividade.AVANCADO,
        )
        cls.outra = criar_partida(horario=criar_horario(cls.quadra, time(21), time(22), status=StatusHorario.OCIOSO))
        passada = criar_partida(horario=criar_horario(cls.quadra, time(8), time(9), status=StatusHorario.OCIOSO))
        TimeSlot.objects.filter(pk=passada.time_slot_id).update(data=timezone.localdate() - timedelta(days=1))
        Booking.objects.create(open_match=cls.partida, player=criar_jogador(first_name="Lucas", last_name="Oliveira"))

    def test_raiz_lista_endpoints(self):
        resposta = self.client.get(reverse("api:raiz"))
        self.assertEqual(resposta.status_code, status.HTTP_200_OK)
        self.assertIn("partidas", resposta.data)

    def test_lista_apenas_partidas_da_vitrine(self):
        resposta = self.client.get(reverse("api:partidas"))
        self.assertEqual(resposta.status_code, status.HTTP_200_OK)
        self.assertEqual(resposta.data["count"], 2)
        primeira = resposta.data["results"][0]
        self.assertEqual(primeira["id"], str(self.partida.pk))
        self.assertEqual((primeira["hora_inicio"], primeira["vagas_disponiveis"]), ("19:00", 2))
        self.assertEqual(primeira["arena"]["nome"], self.quadra.arena.nome)

    def test_filtros(self):
        url = reverse("api:partidas")
        self.assertEqual(self.client.get(url, {"nivel": "avancado"}).data["count"], 1)
        self.assertEqual(self.client.get(url, {"arena": self.quadra.arena.slug}).data["count"], 2)
        self.assertEqual(self.client.get(url, {"data": amanha().isoformat()}).data["count"], 2)
        self.assertEqual(self.client.get(url, {"piso": "areia"}).data["count"], 0)
        self.assertEqual(self.client.get(url, {"data": "13/10/2026"}).status_code, status.HTTP_400_BAD_REQUEST)

    def test_detalhe_com_jogadores(self):
        resposta = self.client.get(reverse("api:partida", args=[self.partida.pk]))
        self.assertEqual(resposta.data["jogadores"], ["Lucas O."])

    def test_arenas_com_quadras(self):
        resposta = self.client.get(reverse("api:arenas"))
        self.assertEqual(resposta.data["results"][0]["quadras"][0]["id"], str(self.quadra.pk))


class ApiInscricaoTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.jogador = criar_jogador()
        cls.partida = criar_partida(vagas=1)
        cls.url = reverse("api:inscrever", args=[cls.partida.pk])

    def test_anonimo_recebe_401(self):
        self.assertEqual(self.client.post(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_quem_nao_e_jogador_recebe_403(self):
        self.client.force_authenticate(criar_gestor())
        self.assertEqual(self.client.post(self.url).status_code, status.HTTP_403_FORBIDDEN)

    def test_inscricao_e_regras_de_negocio(self):
        self.client.force_authenticate(self.jogador)
        resposta = self.client.post(self.url)
        self.assertEqual(resposta.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resposta.data["status_pagamento"], StatusPagamento.PENDENTE)
        self.assertEqual(resposta.data["partida"]["vagas_disponiveis"], 0)

        duplicada = self.client.post(self.url)
        self.assertEqual(duplicada.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("lotada", str(duplicada.data["non_field_errors"]))

        self.client.force_authenticate(criar_jogador())
        lotada = self.client.post(self.url)
        self.assertEqual(lotada.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(str(lotada.data["non_field_errors"][0]), "Esta partida está lotada.")

    def test_minhas_inscricoes_e_cancelamento(self):
        self.client.force_authenticate(self.jogador)
        inscricao_id = self.client.post(self.url).data["id"]
        Booking.objects.create(open_match=criar_partida(vagas=5), player=criar_jogador())  # de outro jogador

        lista = self.client.get(reverse("api:minhas_inscricoes"))
        self.assertEqual([item["id"] for item in lista.data["results"]], [inscricao_id])

        url = reverse("api:inscricao", args=[inscricao_id])
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_204_NO_CONTENT)
        self.partida.refresh_from_db()
        self.assertEqual(self.partida.vagas_disponiveis, 1)

    def test_cancelar_inscricao_paga_retorna_400(self):
        inscricao = Booking.objects.create(
            open_match=self.partida, player=self.jogador, status_pagamento=StatusPagamento.PAGO
        )
        self.client.force_authenticate(self.jogador)
        resposta = self.client.delete(reverse("api:inscricao", args=[inscricao.pk]))
        self.assertEqual(resposta.status_code, status.HTTP_400_BAD_REQUEST)


class ApiCadastroETokenTest(APITestCase):
    def test_cadastro_devolve_token_que_autentica(self):
        resposta = self.client.post(
            reverse("api:cadastro"),
            {
                "username": "novato",
                "first_name": "Novo",
                "last_name": "Jogador",
                "email": "Novato@Example.com",
                "telefone": "(11) 91234-5678",
                "password": "Bola-na-rede-2026",
            },
        )
        self.assertEqual(resposta.status_code, status.HTTP_201_CREATED, resposta.data)
        usuario = CustomUser.objects.get(username="novato")
        self.assertTrue(usuario.is_player)
        self.assertEqual(usuario.email, "novato@example.com")

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {resposta.data['token']}")
        perfil = self.client.get(reverse("api:perfil"))
        self.assertEqual(perfil.data["username"], "novato")

    def test_cadastro_rejeita_senha_fraca_e_email_repetido(self):
        criar_jogador(email="ja@existe.com")
        resposta = self.client.post(
            reverse("api:cadastro"),
            {"username": "fraco", "first_name": "F", "email": "ja@existe.com", "password": "123"},
        )
        self.assertEqual(resposta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", resposta.data)

    def test_token_por_usuario_e_senha(self):
        CustomUser.objects.create_user("comsenha", password="Bola-na-rede-2026", is_player=True)
        resposta = self.client.post(
            reverse("api:token"), {"username": "comsenha", "password": "Bola-na-rede-2026"}
        )
        self.assertEqual(resposta.status_code, status.HTTP_200_OK)
        self.assertIn("token", resposta.data)
