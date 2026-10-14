"""Fase 3: landing, app em /app/, links antigos, login por celular, filtros e "perto de mim"."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from arena import acesso
from arena.localizacao import distancia_km, ler_coordenadas
from arena.models import CodigoAcesso, CustomUser, NivelCompetitividade, StatusHorario

from .fabricas import comprar, criar_arena, criar_horario, criar_jogador, criar_partida, criar_quadra, mover_partida

SMS_EM_MEMORIA = "arena.acesso.SmsMemoria"


class SiteTest(TestCase):
    def test_landing_na_raiz_e_app_em_app(self):
        partida = criar_partida(vagas=4)
        comprar(partida)
        landing = self.client.get("/")
        self.assertContains(landing, "Entra no jogo.")
        self.assertContains(landing, "Horário vago vira receita.")
        self.assertEqual(landing.context["total_partidas"], 1)
        self.assertEqual(landing.context["total_jogadores"], 1)
        self.assertEqual(self.client.get("/app/").status_code, 200)

    def test_links_antigos_vao_para_o_app(self):
        partida = criar_partida()
        resposta = self.client.get(f"/partidas/{partida.pk}/?origem=whatsapp")
        self.assertRedirects(resposta, f"/app/partidas/{partida.pk}/?origem=whatsapp", status_code=301)

    def test_feed_mostra_quem_confirmou(self):
        partida = criar_partida(vagas=4)
        jogador = criar_jogador(first_name="Lucas", last_name="Oliveira")
        comprar(partida, jogador)
        resposta = self.client.get(reverse("arena:vitrine"))
        self.assertContains(resposta, "Lucas O.")
        self.assertContains(resposta, "confirmado")


class FiltrosDoFeedTest(TestCase):
    def test_meu_nivel_e_fim_de_semana(self):
        jogador = criar_jogador(nivel=2)
        iniciante = criar_partida(nivel_competitividade=NivelCompetitividade.INICIANTE)
        avancada = criar_partida(nivel_competitividade=NivelCompetitividade.AVANCADO)
        self.client.force_login(jogador)
        todas = self.client.get(reverse("arena:vitrine"))
        self.assertEqual({p.pk for p in todas.context["partidas"]}, {iniciante.pk, avancada.pk})
        bloqueada = next(p for p in todas.context["partidas"] if p.pk == avancada.pk)
        self.assertIn("níveis 4 a 5", bloqueada.bloqueio)
        meu_nivel = self.client.get(reverse("arena:vitrine"), {"meu_nivel": "1"})
        self.assertEqual([p.pk for p in meu_nivel.context["partidas"]], [iniciante.pk])
        self.assertEqual(self.client.get(reverse("arena:vitrine"), {"dia": "fim_de_semana"}).status_code, 200)

    def test_perto_de_mim_ordena_pela_distancia(self):
        longe = criar_arena(latitude=Decimal("-22.971100"), longitude=Decimal("-43.186300"))  # Rio
        perto = criar_arena(latitude=Decimal("-23.553600"), longitude=Decimal("-46.691400"))  # São Paulo
        partida_longe = criar_partida(horario=criar_horario(criar_quadra(longe), status=StatusHorario.OCIOSO))
        partida_perto = criar_partida(horario=criar_horario(criar_quadra(perto), status=StatusHorario.OCIOSO))
        resposta = self.client.get(reverse("arena:vitrine"), {"lat": "-23.5600", "lng": "-46.6500"})
        partidas = resposta.context["partidas"]
        self.assertEqual([p.pk for p in partidas], [partida_perto.pk, partida_longe.pk])
        self.assertLess(partidas[0].distancia, 10)
        self.assertGreater(partidas[1].distancia, 300)

    def test_distancia_e_coordenadas(self):
        self.assertAlmostEqual(distancia_km(-23.5505, -46.6333, -22.9068, -43.1729), 357, delta=5)
        self.assertIsNone(ler_coordenadas("abc", "1"))
        self.assertIsNone(ler_coordenadas("-95", "10"))
        self.assertEqual(ler_coordenadas("-23.5", "-46.6"), (-23.5, -46.6))


@override_settings(ARENAMATCH_SMS_BACKEND=SMS_EM_MEMORIA)
class LoginPorCelularTest(TestCase):
    def setUp(self):
        acesso.SmsMemoria.caixa_de_saida.clear()

    def codigo_enviado(self) -> str:
        return acesso.SmsMemoria.caixa_de_saida[-1][1].split(" é ")[1][:6]

    def test_primeiro_acesso_cria_jogador_e_pede_o_perfil(self):
        resposta = self.client.post(reverse("arena:entrar_telefone"), {"telefone": "+55 (11) 91234-5678"})
        self.assertRedirects(resposta, reverse("arena:verificar_codigo"))
        self.assertEqual(acesso.SmsMemoria.caixa_de_saida[-1][0], "11912345678")
        self.assertNotIn(self.codigo_enviado(), CodigoAcesso.objects.get().codigo_hash)  # só o hash

        resposta = self.client.post(
            reverse("arena:verificar_codigo"), {"codigo": self.codigo_enviado(), "nome": "Bia Rocha"}
        )
        jogador = CustomUser.objects.get(telefone="(11) 91234-5678")
        self.assertTrue(jogador.is_player)
        self.assertEqual((jogador.first_name, jogador.last_name), ("Bia", "Rocha"))
        self.assertTrue(resposta.url.startswith(reverse("arena:configurar_perfil")))

    def test_jogador_existente_entra_e_codigo_nao_se_reutiliza(self):
        jogador = criar_jogador(telefone="(21) 98888-7777")
        acesso.solicitar_codigo("21988887777")
        codigo = self.codigo_enviado()
        self.assertEqual(acesso.validar_codigo("(21) 98888-7777", codigo), jogador)
        with self.assertRaisesMessage(ValidationError, "expirado"):
            acesso.validar_codigo("21988887777", codigo)

    def test_codigo_errado_esgota_tentativas_e_limite_de_pedidos(self):
        acesso.solicitar_codigo("11900001111")
        for _ in range(acesso.MAXIMO_DE_TENTATIVAS):
            with self.assertRaises(ValidationError):
                acesso.validar_codigo("11900001111", "000000" if self.codigo_enviado() != "000000" else "111111")
        with self.assertRaisesMessage(ValidationError, "expirado"):
            acesso.validar_codigo("11900001111", self.codigo_enviado())
        acesso.solicitar_codigo("11900001111")
        acesso.solicitar_codigo("11900001111")
        with self.assertRaisesMessage(ValidationError, "códigos demais"):
            acesso.solicitar_codigo("11900001111")

    def test_codigo_vencido_e_telefone_invalido(self):
        acesso.solicitar_codigo("11900002222")
        CodigoAcesso.objects.update(expira_em=timezone.now() - timedelta(seconds=1))
        with self.assertRaisesMessage(ValidationError, "expirado"):
            acesso.validar_codigo("11900002222", self.codigo_enviado())
        with self.assertRaises(ValidationError):
            acesso.normalizar_telefone("12345")


class CheckoutRapidoTest(TestCase):
    def test_botao_do_card_leva_os_dados_do_checkout(self):
        partida = criar_partida(vagas=4, vagas_goleiro=1)
        mover_partida(partida, timezone.now() + timedelta(days=1))
        self.client.force_login(criar_jogador())
        resposta = self.client.get(reverse("arena:vitrine"))
        self.assertContains(resposta, f'data-checkout="{reverse("arena:checkout", args=[partida.pk])}"')
        self.assertContains(resposta, 'id="checkout-rapido"')
