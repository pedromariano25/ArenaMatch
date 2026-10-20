"""API usada pelo app Flutter: login pelo celular, pelada de grupo e carteira do organizador."""

from datetime import time, timedelta
from decimal import Decimal

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from arena import acesso, peladas
from arena.models import (
    LedgerEntry,
    OpenMatch,
    StatusInscricao,
    StatusPartida,
    TipoConta,
    TipoReserva,
    Wallet,
)

from .fabricas import amanha, comprar, criar_arena, criar_gestor, criar_horario, criar_jogador, criar_quadra

SMS_EM_MEMORIA = "arena.acesso.SmsMemoria"


@override_settings(ARENAMATCH_SMS_BACKEND=SMS_EM_MEMORIA)
class ApiLoginPeloCelularTest(APITestCase):
    def setUp(self):
        acesso.SmsMemoria.caixa_de_saida.clear()

    def codigo_enviado(self) -> str:
        return acesso.SmsMemoria.caixa_de_saida[-1][1].split(" é ")[1][:6]

    def test_primeiro_acesso_cria_o_jogador_e_devolve_o_token(self):
        resposta = self.client.post(reverse("api:solicitar_codigo"), {"telefone": "(11) 91234-5678"})
        self.assertEqual(resposta.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resposta.data["telefone"], "(11) 91234-5678")
        self.assertNotIn("codigo", resposta.data)  # só aparece com DEBUG ligado

        resposta = self.client.post(
            reverse("api:verificar_codigo"),
            {"telefone": "11912345678", "codigo": self.codigo_enviado(), "nome": "Bia Souza"},
        )
        self.assertEqual(resposta.status_code, status.HTTP_200_OK)
        self.assertTrue(resposta.data["precisa_de_perfil"])
        self.assertEqual(resposta.data["usuario"]["first_name"], "Bia")

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {resposta.data['token']}")
        self.assertEqual(self.client.get(reverse("api:perfil")).data["telefone"], "(11) 91234-5678")

    @override_settings(DEBUG=True)
    def test_em_desenvolvimento_a_resposta_traz_o_codigo(self):
        resposta = self.client.post(reverse("api:solicitar_codigo"), {"telefone": "11912345678"})
        self.assertEqual(resposta.data["codigo"], self.codigo_enviado())

    def test_erros_vem_no_campo_certo(self):
        resposta = self.client.post(reverse("api:solicitar_codigo"), {"telefone": "1234"})
        self.assertEqual(resposta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("DDD", resposta.data["telefone"][0])

        self.client.post(reverse("api:solicitar_codigo"), {"telefone": "11912345678"})
        errado = "000000" if self.codigo_enviado() != "000000" else "111111"
        resposta = self.client.post(reverse("api:verificar_codigo"), {"telefone": "11912345678", "codigo": errado})
        self.assertEqual(resposta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Código incorreto", resposta.data["codigo"][0])


class ApiPeladaDeGrupoTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.quadra = criar_quadra(criar_arena(criar_gestor()))
        cls.organizador = criar_jogador(first_name="Ana")

    def setUp(self):
        self.client.force_authenticate(self.organizador)

    def test_publica_com_o_minimo_e_aplica_os_padroes(self):
        resposta = self.client.post(
            reverse("api:minhas_peladas"),
            {
                "quadra": self.quadra.pk,
                "dia": amanha().isoformat(),
                "hora_inicio": "20:00",
                "vagas_linha": 2,
                "valor_por_vaga": "15.00",
            },
        )
        self.assertEqual(resposta.status_code, status.HTTP_201_CREATED, resposta.data)
        self.assertEqual((resposta.data["titulo"], resposta.data["hora_fim"]), ("Pelada do Ana", "21:00"))
        self.assertEqual((resposta.data["origem"], resposta.data["nivel_competitividade"]), ("pelada", "aberta"))
        self.assertEqual(resposta.data["precos"]["linha_pix"], "20.00")
        self.assertEqual((resposta.data["recebe_por_vaga"], resposta.data["arrecadado"]), ("15.00", "0.00"))
        self.assertTrue(resposta.data["pode_cancelar"])
        pelada = OpenMatch.objects.get()
        self.assertEqual(pelada.time_slot.tipo_reserva, TipoReserva.MENSALISTA)

        # A pelada aparece no feed com o filtro de origem.
        feed = self.client.get(reverse("api:partidas"), {"origem": "pelada"})
        self.assertEqual([p["id"] for p in feed.data["results"]], [str(pelada.pk)])
        self.assertEqual(self.client.get(reverse("api:partidas"), {"origem": "arena"}).data["count"], 0)

    def test_horario_ocupado_pela_arena_retorna_400(self):
        criar_horario(self.quadra, time(20), time(21), tipo_reserva=TipoReserva.AVULSO)
        resposta = self.client.post(
            reverse("api:minhas_peladas"),
            {"quadra": self.quadra.pk, "dia": amanha().isoformat(), "hora_inicio": "20:00", "vagas_linha": 2, "valor_por_vaga": "15"},
        )
        self.assertEqual(resposta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("não está reservado para um grupo", str(resposta.data))

    def test_lista_vendas_e_cancela_com_reembolso(self):
        pelada = peladas.criar_pelada(
            self.organizador, self.quadra, amanha(), time(20), time(21), titulo="Racha", vagas_linha=3, valor_por_vaga=Decimal("15")
        )
        inscricao = comprar(pelada)

        (item,) = self.client.get(reverse("api:minhas_peladas")).data["results"]
        self.assertEqual((item["titulo"], item["arrecadado"], item["jogadores_confirmados"]), ("Racha", "15.00", 1))

        resposta = self.client.post(reverse("api:cancelar_pelada", args=[pelada.pk]))
        self.assertEqual(resposta.data, {"reembolsados": 1})
        pelada.refresh_from_db()
        inscricao.refresh_from_db()
        self.assertEqual((pelada.status, inscricao.status), (StatusPartida.CANCELADA, StatusInscricao.REEMBOLSADA))

    def test_nao_cancela_a_pelada_de_outro_organizador(self):
        alheia = peladas.criar_pelada(
            criar_jogador(), self.quadra, amanha(), time(21), time(22), titulo="Outra", vagas_linha=2, valor_por_vaga=Decimal("15")
        )
        self.assertEqual(self.client.post(reverse("api:cancelar_pelada", args=[alheia.pk])).status_code, 404)

    def test_gestor_nao_organiza_pelada(self):
        self.client.force_authenticate(criar_gestor())
        self.assertEqual(self.client.get(reverse("api:minhas_peladas")).status_code, status.HTTP_403_FORBIDDEN)


class ApiCarteiraDoOrganizadorTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.quadra = criar_quadra(criar_arena(criar_gestor()))
        cls.organizador = criar_jogador()

    def setUp(self):
        self.client.force_authenticate(self.organizador)
        pelada = peladas.criar_pelada(
            self.organizador, self.quadra, amanha(), time(20), time(21), titulo="Racha", vagas_linha=2, valor_por_vaga=Decimal("15")
        )
        comprar(pelada)

    def test_saldo_a_liberar_e_saque_depois_de_liberar(self):
        carteira = self.client.get(reverse("api:carteira_organizador")).data
        self.assertEqual((carteira["disponivel"], carteira["a_liberar"]), ("0.00", "15.00"))
        self.assertIsNone(carteira["chave_pix"])
        self.assertEqual(carteira["valor_minimo_saque"], "10.00")

        sem_chave = self.client.post(reverse("api:saques"))
        self.assertEqual(sem_chave.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("chave Pix", str(sem_chave.data))

        invalida = self.client.put(reverse("api:chave_pix"), {"tipo_chave_pix": "cpf", "chave_pix": "111.111.111-11"})
        self.assertEqual(invalida.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("chave_pix", invalida.data)
        resposta = self.client.put(reverse("api:chave_pix"), {"tipo_chave_pix": "celular", "chave_pix": "(11) 91234-5678"})
        self.assertEqual(resposta.data, {"tipo": "celular", "chave": "+5511912345678"})

        # O dia seguinte ao jogo chegou: o valor da vaga libera para saque.
        LedgerEntry.objects.filter(conta__tipo=TipoConta.ORGANIZADOR).update(
            disponivel_em=timezone.now() - timedelta(minutes=1)
        )
        saque = self.client.post(reverse("api:saques"))
        self.assertEqual(saque.status_code, status.HTTP_201_CREATED)
        self.assertEqual((saque.data["valor"], saque.data["chave_pix"]), ("15.00", "+5511912345678"))

        carteira = self.client.get(reverse("api:carteira_organizador")).data
        self.assertEqual((carteira["disponivel"], carteira["sacado"]), ("0.00", "15.00"))
        self.assertEqual(len(carteira["saques"]), 1)
        self.assertEqual(Wallet.objects.get(usuario=self.organizador).chave_pix, "+5511912345678")
