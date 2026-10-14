"""Regras de negócio dos modelos, validadores e formatação."""

import uuid
from datetime import time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.forms import modelform_factory
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from arena import razao
from arena.formatacao import formatar_brl, formatar_cnpj, formatar_cpf
from arena.models import (
    MEIA_NOITE,
    Arena,
    Booking,
    Court,
    CustomUser,
    NivelCompetitividade,
    OpenMatch,
    Posicao,
    StatusHorario,
    StatusInscricao,
    StatusPartida,
    TimeSlot,
    TipoLancamento,
)
from arena.validators import validar_cnpj, validar_cpf

from .fabricas import (
    amanha,
    criar_arena,
    criar_gestor,
    criar_horario,
    criar_jogador,
    criar_partida,
    criar_quadra,
    inscrever,
    mover_partida,
)


class ValidadoresEFormatacaoTest(SimpleTestCase):
    def test_cpf(self):
        for valido in ("529.982.247-25", "52998224725"):
            validar_cpf(valido)
        for invalido in ("529.982.247-24", "111.111.111-11", "123", ""):
            with self.subTest(invalido=invalido), self.assertRaises(ValidationError):
                validar_cpf(invalido)

    def test_cnpj_numerico_e_alfanumerico(self):
        for valido in ("11.222.333/0001-81", "11222333000181", "12.ABC.345/01DE-35", "12abc34501de35"):
            validar_cnpj(valido)
        for invalido in ("11.222.333/0001-82", "00.000.000/0000-00", "12.ABC.345/01DE-36", "1234"):
            with self.subTest(invalido=invalido), self.assertRaises(ValidationError):
                validar_cnpj(invalido)

    def test_formatacao(self):
        self.assertEqual(formatar_brl(Decimal("1234.5")), "R$ 1.234,50")
        self.assertEqual(formatar_cnpj("11222333000181"), "11.222.333/0001-81")
        self.assertEqual(formatar_cpf("52998224725"), "529.982.247-25")


class UsuarioTest(TestCase):
    def test_uuid_cpf_normalizado_e_nomes(self):
        usuario = CustomUser.objects.create_user(
            "comcpf", cpf="529.982.247-25", first_name="Ana Beatriz", last_name="Souza Lima"
        )
        self.assertIsInstance(usuario.pk, uuid.UUID)
        self.assertEqual(usuario.cpf, "52998224725")
        self.assertEqual(usuario.nome_publico, "Ana S.")
        self.assertEqual(usuario.iniciais, "AL")

    def test_varios_usuarios_sem_cpf_e_cpf_duplicado(self):
        CustomUser.objects.create_user("semcpf1")
        CustomUser.objects.create_user("semcpf2")
        CustomUser.objects.create_user("original", cpf="52998224725")
        duplicado = CustomUser(username="dup", cpf="529.982.247-25")
        duplicado.set_unusable_password()
        with self.assertRaises(ValidationError) as ctx:
            duplicado.full_clean()
        self.assertIn("cpf", ctx.exception.message_dict)


class ArenaTest(TestCase):
    def test_normaliza_cnpj_e_gera_slug_unico(self):
        gestor = criar_gestor()
        arena = criar_arena(gestor, nome="Arena São João", cnpj="11.222.333/0001-81")
        outra = criar_arena(gestor, nome="Arena São João", cnpj="12.ABC.345/01DE-35")
        self.assertEqual((arena.cnpj, arena.slug), ("11222333000181", "arena-sao-joao"))
        self.assertEqual((outra.cnpj, outra.slug), ("12ABC34501DE35", "arena-sao-joao-2"))

    def test_cnpj_duplicado_mesmo_sem_mascara(self):
        criar_arena(cnpj="11.222.333/0001-81")
        with self.assertRaises(ValidationError) as ctx:
            criar_arena(cnpj="11222333000181")
        self.assertIn("cnpj", ctx.exception.message_dict)

    def test_gestor_precisa_ser_manager(self):
        with self.assertRaises(ValidationError) as ctx:
            criar_arena(gestor=criar_jogador())
        self.assertIn("manager", ctx.exception.message_dict)


class TimeSlotTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.quadra = criar_quadra()
        cls.outra_quadra = criar_quadra(arena=cls.quadra.arena)

    def horario(self, inicio, fim, **dados):
        return criar_horario(quadra=dados.pop("quadra", self.quadra), inicio=inicio, fim=fim, **dados)

    def test_fim_antes_do_inicio(self):
        with self.assertRaises(ValidationError) as ctx:
            self.horario(time(20), time(19))
        self.assertIn("hora_fim", ctx.exception.message_dict)

    def test_sobreposicao(self):
        self.horario(time(19), time(20))
        with self.assertRaises(ValidationError) as ctx:
            self.horario(time(19, 30), time(20, 30))
        self.assertIn("Conflito de agenda", str(ctx.exception))
        self.horario(time(20), time(21))  # encostado: permitido
        self.horario(time(19), time(20), quadra=self.outra_quadra)  # outra quadra: permitido
        self.horario(time(10), time(11), status=StatusHorario.CANCELADO)
        with self.assertRaises(ValidationError):  # cancelado também ocupa a agenda
            self.horario(time(10), time(11))

    def test_meia_noite_como_fim_do_dia(self):
        self.horario(time(23), MEIA_NOITE)
        with self.assertRaises(ValidationError):
            self.horario(time(23, 30), MEIA_NOITE)
        with self.assertRaises(ValidationError):
            self.horario(time(22, 30), time(23, 30))
        self.horario(MEIA_NOITE, time(1))  # madrugada do mesmo dia: permitido
        self.horario(time(22), time(23))

    def test_editar_o_proprio_horario(self):
        horario = self.horario(time(19), time(20))
        horario.hora_fim = time(20, 30)
        horario.save()
        self.assertEqual(horario.intervalo, "19:00–20:30")


class OpenMatchTest(TestCase):
    def test_exige_horario_livre_e_protege_o_horario(self):
        horario = criar_horario(status=StatusHorario.CONFIRMADO)
        with self.assertRaises(ValidationError):
            criar_partida(horario=horario, vagas=14)
        horario.status = StatusHorario.OCIOSO
        horario.save()
        partida = criar_partida(horario=horario, vagas=14)
        self.assertEqual((partida.vagas_disponiveis, partida.status), (14, StatusPartida.ABERTA))
        with self.assertRaises(ValidationError):  # uma partida por horário
            criar_partida(horario=horario)
        horario.status = StatusHorario.CONFIRMADO
        with self.assertRaises(ValidationError):  # horário com partida ativa
            horario.save()
        partida.status = StatusPartida.CANCELADA
        partida.save()
        horario.save()  # com a partida cancelada, o horário pode ser confirmado

    def test_horario_cancelado_tambem_serve(self):
        criar_partida(horario=criar_horario(status=StatusHorario.CANCELADO))

    def test_horario_que_ja_comecou(self):
        ontem = timezone.localdate() - timedelta(days=1)
        with self.assertRaises(ValidationError) as ctx:
            criar_partida(horario=criar_horario(data=ontem, status=StatusHorario.OCIOSO))
        self.assertIn("já começou", str(ctx.exception))

    def test_vagas_totais_minimo(self):
        with self.assertRaises(ValidationError):
            criar_partida(vagas=0)

    def test_propriedades_de_exibicao(self):
        partida = criar_partida(vagas=4)
        Booking.objects.create(open_match=partida, player=criar_jogador())
        partida.refresh_from_db()
        self.assertEqual((partida.vagas_ocupadas, partida.percentual_ocupado), (1, 25))
        self.assertTrue(partida.aceita_inscricoes)
        self.assertEqual(partida.get_absolute_url(), f"/app/partidas/{partida.pk}/")

    def test_queryset_vitrine_e_filtros(self):
        quadra = criar_quadra()
        depois = criar_partida(horario=criar_horario(quadra, time(21), time(22), status=StatusHorario.OCIOSO))
        antes = criar_partida(
            horario=criar_horario(quadra, time(19), time(20), status=StatusHorario.OCIOSO),
            nivel_competitividade=NivelCompetitividade.AVANCADO,
        )
        cancelada = criar_partida(horario=criar_horario(quadra, time(9), time(10), status=StatusHorario.OCIOSO))
        cancelada.status = StatusPartida.CANCELADA
        cancelada.save()
        passada = criar_partida(horario=criar_horario(quadra, time(7), time(8), status=StatusHorario.OCIOSO))
        TimeSlot.objects.filter(pk=passada.time_slot_id).update(data=timezone.localdate() - timedelta(days=2))

        self.assertEqual(list(OpenMatch.objects.vitrine()), [antes, depois])
        self.assertEqual(list(OpenMatch.objects.vitrine().filtrar(nivel="avancado")), [antes])
        self.assertEqual(
            list(OpenMatch.objects.vitrine().filtrar(arena=quadra.arena.slug, de=amanha(), ate=amanha())),
            [antes, depois],
        )
        self.assertFalse(OpenMatch.objects.vitrine().filtrar(piso="areia").exists())


class BookingTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.jogadores = [criar_jogador() for _ in range(3)]

    def setUp(self):
        self.partida = criar_partida(vagas=2)

    def estado(self):
        self.partida.refresh_from_db()
        return self.partida.vagas_disponiveis, self.partida.status

    def test_reserva_ocupa_a_vaga_ate_vencer(self):
        j1, j2, j3 = self.jogadores
        reserva = Booking.objects.create(open_match=self.partida, player=j1)
        self.assertEqual(reserva.status, StatusInscricao.AGUARDANDO_PAGAMENTO)
        self.assertEqual(self.estado(), (1, StatusPartida.ABERTA))
        inscrever(self.partida, j2)
        self.assertEqual(self.estado(), (0, StatusPartida.LOTADA))
        with self.assertRaisesMessage(ValidationError, "lotada"):
            inscrever(self.partida, j3)
        Booking.objects.filter(pk=reserva.pk).update(reservada_ate=timezone.now() - timedelta(minutes=1))
        inscrever(self.partida, j3)  # a reserva vencida não conta mais
        self.assertEqual(self.estado(), (0, StatusPartida.LOTADA))

    def test_uma_inscricao_ativa_por_jogador(self):
        j1 = self.jogadores[0]
        inscricao = inscrever(self.partida, j1)
        with self.assertRaisesMessage(ValidationError, "inscrição ativa"):
            inscrever(self.partida, j1)
        inscricao.status = StatusInscricao.CANCELADA
        inscricao.save()
        self.assertEqual(self.estado(), (2, StatusPartida.ABERTA))
        inscrever(self.partida, j1)  # nova inscrição depois do cancelamento

    def test_transicoes_de_status(self):
        inscricao = inscrever(self.partida, self.jogadores[0])
        inscricao.status = StatusInscricao.AGUARDANDO_PAGAMENTO
        with self.assertRaisesMessage(ValidationError, "Não é possível passar"):
            inscricao.save()
        inscricao.status = StatusInscricao.REEMBOLSADA
        inscricao.save()
        inscricao.status = StatusInscricao.CONFIRMADA
        with self.assertRaises(ValidationError):
            inscricao.save()

    def test_expirada_so_volta_se_houver_vaga(self):
        j1, j2, j3 = self.jogadores
        reserva = Booking.objects.create(open_match=self.partida, player=j1)
        reserva.status = StatusInscricao.EXPIRADA
        reserva.save()
        inscrever(self.partida, j2)
        inscrever(self.partida, j3)
        reserva.status = StatusInscricao.CONFIRMADA
        with self.assertRaisesMessage(ValidationError, "lotada"):
            reserva.save()

    def test_vagas_de_goleiro_sao_separadas(self):
        partida = criar_partida(vagas=3, vagas_goleiro=1)
        inscrever(partida, posicao=Posicao.GOLEIRO)
        with self.assertRaisesMessage(ValidationError, "goleiro"):
            inscrever(partida, posicao=Posicao.GOLEIRO)
        inscrever(partida)
        inscrever(partida)
        partida.refresh_from_db()
        self.assertEqual(partida.status, StatusPartida.LOTADA)

    def test_vagas_travadas_apos_inscricao(self):
        j1, j2, _ = self.jogadores
        inscrever(self.partida, j1)
        inscrever(self.partida, j2)
        for vagas in (1, 5):
            self.partida.refresh_from_db()
            self.partida.vagas_totais = vagas
            with self.assertRaises(ValidationError) as ctx:
                self.partida.save()
            self.assertIn("ficam travados", str(ctx.exception))
        self.assertEqual(self.estado(), (0, StatusPartida.LOTADA))

    def test_jogador_sem_flag(self):
        with self.assertRaises(ValidationError) as ctx:
            inscrever(self.partida, criar_gestor())
        self.assertIn("player", ctx.exception.message_dict)

    def test_partida_cancelada(self):
        inscrever(self.partida, self.jogadores[0])
        self.partida.refresh_from_db()
        self.partida.status = StatusPartida.CANCELADA
        self.partida.save()
        with self.assertRaisesMessage(ValidationError, "cancelada"):
            inscrever(self.partida, self.jogadores[1])

    def test_partida_ja_comecou(self):
        ontem = timezone.localdate() - timedelta(days=1)
        TimeSlot.objects.filter(pk=self.partida.time_slot_id).update(data=ontem)
        with self.assertRaisesMessage(ValidationError, "já começou"):
            inscrever(self.partida, self.jogadores[0])

    def test_trocar_partida_ou_jogador(self):
        j1, j2, _ = self.jogadores
        outra = criar_partida(vagas=5)
        inscricao = inscrever(self.partida, j1)
        inscricao.open_match = outra
        with self.assertRaisesMessage(ValidationError, "trocar a partida"):
            inscricao.save()
        inscricao = Booking.objects.get(pk=inscricao.pk)
        inscricao.player = j2
        with self.assertRaises(ValidationError):
            inscricao.save()
        self.assertEqual(self.estado(), (1, StatusPartida.ABERTA))

    def test_prazos_de_cancelamento_e_repasse(self):
        j1, j2, _ = self.jogadores
        paga = inscrever(self.partida, j1)
        reserva = Booking.objects.create(open_match=self.partida, player=j2)
        mover_partida(self.partida, timezone.now() + timedelta(days=2))
        paga = Booking.objects.get(pk=paga.pk)
        self.assertTrue(paga.pode_cancelar)
        self.assertFalse(paga.pode_repassar)
        mover_partida(self.partida, timezone.now() + timedelta(hours=5))
        paga = Booking.objects.get(pk=paga.pk)
        self.assertFalse(paga.pode_cancelar)
        self.assertTrue(paga.pode_repassar)
        self.assertTrue(Booking.objects.get(pk=reserva.pk).pode_cancelar)

    def test_protect_preserva_historico(self):
        inscrever(self.partida, self.jogadores[0])
        with self.assertRaises(ProtectedError):
            self.partida.delete()
        with self.assertRaises(ProtectedError):
            self.partida.time_slot.delete()

    def test_lancamento_do_razao_e_imutavel(self):
        lancamento = razao.lancar(
            razao.carteira_da_plataforma(), TipoLancamento.TAXA_SERVICO, Decimal("1.00"), "teste"
        )
        lancamento.valor = Decimal("2.00")
        with self.assertRaises(ValidationError):
            lancamento.save()
        with self.assertRaises(ValidationError):
            lancamento.delete()


class FormulariosDeModeloTest(TestCase):
    """Simula o fluxo do Django Admin (ModelForm): erros viram mensagens, não exceções."""

    def form_inscricao(self, partida, jogador):
        return modelform_factory(Booking, fields="__all__")(
            data={
                "open_match": partida.pk,
                "player": jogador.pk,
                "posicao": "linha",
                "status": "confirmada",
                "metodo_pagamento": "pix",
                "data_inscricao": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    def test_formularios_vazios_nao_quebram(self):
        for modelo in (Arena, Court, TimeSlot, OpenMatch, Booking):
            with self.subTest(modelo=modelo.__name__):
                self.assertFalse(modelform_factory(modelo, fields="__all__")(data={}).is_valid())

    def test_conflito_de_agenda(self):
        horario = criar_horario()
        form = modelform_factory(TimeSlot, fields="__all__")(
            data={
                "court": horario.court_id,
                "data": horario.data.isoformat(),
                "hora_inicio": "19:30",
                "hora_fim": "20:30",
                "tipo_reserva": "avulso",
                "status": "confirmado",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Conflito de agenda", str(form.non_field_errors()))

    def test_partida_lotada_e_inscricao_duplicada(self):
        jogador, outro = criar_jogador(), criar_jogador()
        lotada = criar_partida(vagas=1)
        Booking.objects.create(open_match=lotada, player=jogador)
        form = self.form_inscricao(lotada, outro)
        self.assertFalse(form.is_valid())
        self.assertIn("lotada", str(form.non_field_errors()))

        aberta = criar_partida(vagas=3)
        Booking.objects.create(open_match=aberta, player=jogador)
        form = self.form_inscricao(aberta, jogador)
        self.assertFalse(form.is_valid())
        self.assertIn("inscrição ativa", str(form.errors))
