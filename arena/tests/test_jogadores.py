"""Jogadores: nível, elegibilidade, goleiro, check-in, confiabilidade, avaliações e times."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from arena import checkout, jogadores, partidas
from arena.models import (
    Booking,
    DirecaoNivel,
    Elogio,
    NivelCompetitividade,
    OrigemNivel,
    PercepcaoNivel,
    PlayerProfile,
    Posicao,
    PosicaoJogador,
    StatusHorario,
    TipoElogio,
)

from .fabricas import comprar, criar_arena, criar_gestor, criar_horario, criar_jogador, criar_partida, criar_quadra, mover_partida


def jogo_terminado(partida, quem_fez_check_in=()) -> None:
    """Leva a partida para o passado recente, faz os check-ins e a encerra."""
    mover_partida(partida, timezone.now() - timedelta(minutes=30))
    for inscricao in quem_fez_check_in:
        jogadores.registrar_check_in(Booking.objects.get(pk=inscricao.pk))
    partidas.finalizar_partidas(partida.time_slot.fim + timedelta(minutes=1))
    partida.refresh_from_db()


class NivelTest(TestCase):
    def test_questionario_ancora_a_autoavaliacao(self):
        self.assertEqual(jogadores.calcular_nivel(1, "raro", "nunca"), 1)
        self.assertEqual(jogadores.calcular_nivel(5, "varias", "federado"), 5)
        self.assertEqual(jogadores.calcular_nivel(2, "varias", "federado"), 3)  # se subestimou
        self.assertEqual(jogadores.calcular_nivel(5, "raro", "nunca"), 3)  # se superestimou

    def test_perfil_ajustado_pela_comunidade_nao_e_redefinido_pelo_jogador(self):
        jogador = criar_jogador(nivel=2)
        PlayerProfile.objects.filter(jogador=jogador).update(nivel_origem=OrigemNivel.AJUSTADO)
        perfil = jogadores.salvar_perfil(jogador, posicao=PosicaoJogador.ATAQUE, nivel_declarado=5)
        self.assertEqual((perfil.nivel, perfil.posicao), (2, PosicaoJogador.ATAQUE))


class ElegibilidadeTest(TestCase):
    def setUp(self):
        self.avancada = criar_partida(vagas=4, nivel_competitividade=NivelCompetitividade.AVANCADO)
        mover_partida(self.avancada, timezone.now() + timedelta(days=2))

    def test_fora_da_faixa_nao_entra_ate_a_liberacao(self):
        mediano, forte = criar_jogador(nivel=3), criar_jogador(nivel=4)
        with self.assertRaisesMessage(ValidationError, "níveis 4 a 5"):
            comprar(self.avancada, mediano)
        comprar(self.avancada, forte)
        # A trava cai 1h antes do prazo do mínimo (padrão: 3h antes do jogo).
        mover_partida(self.avancada, timezone.now() + timedelta(hours=3, minutes=59))
        comprar(self.avancada, mediano)

    def test_sem_perfil_precisa_responder_o_questionario(self):
        with self.assertRaises(ValidationError) as ctx:
            comprar(self.avancada, criar_jogador(nivel=None))
        self.assertEqual(ctx.exception.code, "perfil_incompleto")

    def test_vaga_de_goleiro_so_para_quem_joga_no_gol(self):
        partida = criar_partida(vagas=4, vagas_goleiro=1)
        with self.assertRaisesMessage(ValidationError, "quem joga no gol"):
            comprar(partida, criar_jogador(joga_no_gol=False), posicao=Posicao.GOLEIRO)
        goleiro = criar_jogador(posicao=PosicaoJogador.GOLEIRO, joga_no_gol=False)
        PlayerProfile.objects.filter(jogador=goleiro).update(goleiro_suspenso_ate=timezone.localdate() + timedelta(days=3))
        with self.assertRaisesMessage(ValidationError, "suspensa"):
            comprar(partida, goleiro, posicao=Posicao.GOLEIRO)

    def test_lista_de_espera_tambem_respeita_o_nivel(self):
        with self.assertRaises(ValidationError):
            checkout.entrar_na_lista_de_espera(self.avancada, criar_jogador(nivel=2))


class CheckInEFaltasTest(TestCase):
    def setUp(self):
        self.partida = criar_partida(vagas=4, vagas_goleiro=1)
        self.presente = comprar(self.partida)
        self.ausente = comprar(self.partida)
        self.goleiro = comprar(self.partida, posicao=Posicao.GOLEIRO)

    def test_check_in_so_perto_do_jogo(self):
        with self.assertRaisesMessage(ValidationError, "1h antes"):
            jogadores.registrar_check_in(self.presente)

    def test_quem_nao_fez_check_in_falta_e_goleiro_perde_a_vaga_gratis(self):
        jogo_terminado(self.partida, [self.presente])
        for inscricao in (self.presente, self.ausente, self.goleiro):
            inscricao.refresh_from_db()
        self.assertEqual([self.presente.faltou, self.ausente.faltou, self.goleiro.faltou], [False, True, True])
        perfil_goleiro = PlayerProfile.objects.get(jogador=self.goleiro.player)
        self.assertTrue(perfil_goleiro.goleiro_suspenso)
        estatisticas = jogadores.estatisticas(self.ausente.player)
        self.assertEqual((estatisticas.partidas_jogadas, estatisticas.faltas, estatisticas.confiabilidade), (0, 1, 0))
        self.assertEqual(jogadores.estatisticas(self.presente.player).confiabilidade, 100)

    def test_sem_check_in_na_partida_ninguem_falta(self):
        jogo_terminado(self.partida)
        self.assertFalse(self.partida.inscricoes.filter(faltou=True).exists())
        self.assertEqual(jogadores.estatisticas(self.ausente.player).partidas_jogadas, 1)


class AvaliacaoTest(TestCase):
    def setUp(self):
        self.partida = criar_partida(vagas=6, nivel_competitividade=NivelCompetitividade.INTERMEDIARIO)
        self.alvo = criar_jogador(nivel=2)
        self.colegas = [criar_jogador() for _ in range(4)]
        for jogador in [self.alvo, *self.colegas]:
            comprar(self.partida, jogador)
        jogo_terminado(self.partida)

    def test_elogios_e_uma_avaliacao_por_jogador(self):
        autor, elogiado = self.colegas[:2]
        self.assertTrue(jogadores.pode_avaliar(self.partida, autor))
        jogadores.registrar_avaliacao(
            self.partida, autor, PercepcaoNivel.NA_MEDIDA, {str(elogiado.pk): TipoElogio.BOM_DE_PASSE}
        )
        self.assertEqual(Elogio.objects.get().alvo, elogiado)
        self.assertFalse(jogadores.pode_avaliar(self.partida, autor))
        with self.assertRaises(ValidationError):
            jogadores.registrar_avaliacao(self.partida, autor, PercepcaoNivel.NA_MEDIDA)
        self.assertFalse(jogadores.pode_avaliar(self.partida, criar_jogador()))  # não jogou

    def test_tres_colegas_sinalizando_ajustam_o_nivel(self):
        sinal = {str(self.alvo.pk): DirecaoNivel.ACIMA}
        for autor in self.colegas[:2]:
            jogadores.registrar_avaliacao(self.partida, autor, PercepcaoNivel.NA_MEDIDA, sinais=sinal)
        self.assertEqual(PlayerProfile.objects.get(jogador=self.alvo).nivel, 2)
        ajustados = jogadores.registrar_avaliacao(self.partida, self.colegas[2], PercepcaoNivel.NA_MEDIDA, sinais=sinal)
        perfil = PlayerProfile.objects.get(jogador=self.alvo)
        self.assertEqual((ajustados, perfil.nivel, perfil.nivel_origem), ([self.alvo], 3, OrigemNivel.AJUSTADO))


class TimesTest(TestCase):
    def test_times_equilibrados_com_um_goleiro_em_cada(self):
        partida = criar_partida(vagas=10, vagas_goleiro=2)
        for nivel in (5, 5, 4, 4, 3, 3, 2, 2):
            comprar(partida, criar_jogador(nivel=nivel))
        for _ in range(2):
            comprar(partida, criar_jogador(posicao=PosicaoJogador.GOLEIRO), posicao=Posicao.GOLEIRO)
        laranja, azul = jogadores.montar_times(partida)
        self.assertEqual((len(laranja.jogadores), len(azul.jogadores)), (4, 4))
        self.assertTrue(laranja.goleiro and azul.goleiro)
        self.assertLessEqual(abs(laranja.forca - azul.forca), 2)


class TelasDoJogadorTest(TestCase):
    def test_cadastro_leva_ao_questionario_e_ele_define_o_nivel(self):
        resposta = self.client.post(
            reverse("arena:cadastro"),
            {
                "first_name": "Bia",
                "username": "bia",
                "email": "bia@example.com",
                "password1": "Bola-na-rede-2026",
                "password2": "Bola-na-rede-2026",
            },
        )
        self.assertRedirects(
            resposta, f"{reverse('arena:configurar_perfil')}?next={reverse('arena:vitrine')}", fetch_redirect_response=False
        )
        resposta = self.client.post(
            reverse("arena:configurar_perfil"),
            {"posicao": "ataque", "autoavaliacao": "4", "frequencia": "semanal", "experiencia": "amador", "next": "/"},
        )
        self.assertRedirects(resposta, "/")
        self.assertEqual(PlayerProfile.objects.get(jogador__username="bia").nivel, 4)
        self.assertContains(self.client.get(reverse("arena:perfil")), "partidas jogadas")

    def test_checkout_sem_perfil_manda_para_o_questionario(self):
        partida = criar_partida()
        self.client.force_login(criar_jogador(nivel=None))
        resposta = self.client.get(reverse("arena:checkout", args=[partida.pk]))
        self.assertTrue(resposta.url.startswith(reverse("arena:configurar_perfil")))

    def test_comprovante_tem_qr_de_check_in_e_avaliacao_pos_jogo(self):
        partida = criar_partida(vagas=3)
        jogador = criar_jogador()
        inscricao = comprar(partida, jogador)
        colega = comprar(partida)
        self.client.force_login(jogador)
        comprovante = self.client.get(reverse("arena:inscricao", args=[inscricao.pk]))
        self.assertContains(comprovante, reverse("gestor:check_in_inscricao", args=[inscricao.pk]))

        jogo_terminado(partida)
        url = reverse("arena:avaliar_partida", args=[partida.pk])
        self.assertContains(self.client.get(url), colega.player.nome_publico)
        self.client.post(url, {"percepcao": "na_medida", f"elogio_{colega.player_id}": "fair_play"})
        self.assertTrue(Elogio.objects.filter(alvo=colega.player, tipo="fair_play").exists())


class CheckInDoGestorTest(TestCase):
    def test_recepcao_marca_presenca_pelo_qr(self):
        gestor = criar_gestor()
        quadra = criar_quadra(criar_arena(gestor))
        partida = criar_partida(vagas=2, horario=criar_horario(quadra, status=StatusHorario.OCIOSO))
        inscricao = comprar(partida)
        mover_partida(partida, timezone.now() + timedelta(minutes=30))
        self.client.force_login(gestor)
        self.assertContains(self.client.get(reverse("gestor:check_in")), inscricao.player.get_full_name())
        url = reverse("gestor:check_in_inscricao", args=[inscricao.pk])
        self.assertContains(self.client.get(url), "Confirmar presença")
        self.client.post(url)
        inscricao.refresh_from_db()
        self.assertIsNotNone(inscricao.check_in_em)

        outro_gestor = criar_gestor()
        criar_arena(outro_gestor)
        self.client.force_login(outro_gestor)
        self.assertEqual(self.client.get(url).status_code, 404)


class PerfilApiTest(APITestCase):
    def test_cria_e_consulta_o_perfil(self):
        jogador = criar_jogador(nivel=None)
        self.client.force_authenticate(jogador)
        url = reverse("api:perfil_jogador")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.put(url, {"posicao": "meio"}).status_code, 400)
        resposta = self.client.put(
            url, {"posicao": "meio", "autoavaliacao": 3, "frequencia": "semanal", "experiencia": "amigos"}
        )
        self.assertEqual((resposta.status_code, resposta.data["nivel"]), (200, 3))
        self.assertEqual(self.client.get(reverse("api:perfil")).data["perfil"]["posicao"], "meio")
