"""Comando ``populate_db``: recria o banco com dados de demonstração realistas.

Uso: ``python manage.py populate_db``. ATENÇÃO: apaga TODOS os dados antes. Só roda
com ``DEBUG=True`` (ou ``--force``), porque cria contas com senhas fracas e conhecidas.

Tudo passa pelas mesmas regras e serviços do sistema: agenda sem conflitos,
checkout com o gateway simulado, cancelamentos com crédito, mínimo de jogadores,
encerramento das partidas e repasses. Para gerar um histórico verdadeiro (jogos
finalizados, saldo liberado e repasses), os últimos dias são simulados com um
relógio controlado que avança e roda as rotinas como o agendador faria.
"""

import random
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import F
from django.db.models.signals import post_delete
from django.test.utils import override_settings
from django.utils import timezone
from django.utils.text import slugify

from arena import checkout, jogadores, partidas, razao
from arena.gestao import vagas_goleiro_sugeridas
from arena.models import (
    FAIXAS_DE_NIVEL,
    MEIA_NOITE,
    STATUS_HORARIO_LIVRE,
    Arena,
    AvaliacaoPartida,
    Booking,
    DirecaoNivel,
    Elogio,
    Court,
    CustomUser,
    LedgerAccount,
    LedgerEntry,
    MetodoPagamento,
    MotivoCancelamento,
    NivelCompetitividade,
    OpenMatch,
    Payment,
    Payout,
    PercepcaoNivel,
    PlayerProfile,
    Posicao,
    PosicaoJogador,
    SinalNivel,
    StatusHorario,
    StatusInscricao,
    StatusPartida,
    TimeSlot,
    TipoPiso,
    TipoElogio,
    TipoReserva,
    WaitlistEntry,
    devolver_vaga_apos_exclusao,
)
from arena.validators import digitos_verificadores_cnpj, digitos_verificadores_cpf

SENHA_ADMIN = "admin123"
SENHA_GESTOR = "gestor123"
SENHA_JOGADOR = "jogador123"
TELEFONE_DEMO = "(11) 90000-0001"
NOME_GRUPO_GESTORES = "Gestores"

DIAS_DE_AGENDA = 7
DIAS_DE_HISTORICO = 6
PARTIDAS_POR_ARENA = 6
PARTIDAS_PASSADAS_POR_DIA = 2
PARTIDAS_LOTADAS = 3
FAIXAS_DIA_UTIL = ((18, 19), (19, 20), (20, 21), (21, 22), (22, 23))
FAIXAS_FIM_DE_SEMANA = ((9, 10), (10, 11), (11, 12), (16, 17), (17, 18), (18, 19), (19, 20))

ARENAS: list[dict[str, Any]] = [
    {
        "nome": "Arena Gol de Placa",
        "endereco_completo": "Rua Harmonia, 850 – Vila Madalena, São Paulo – SP",
        "coordenadas": (Decimal("-23.553600"), Decimal("-46.691400")),
        "telefone_contato": "(11) 3000-0101",
        "hora_abertura": time(7),
        "hora_fechamento": MEIA_NOITE,
        "cnpj_alfanumerico": False,
        "gestor": ("carlos.andrade", "Carlos", "Andrade"),
        "quadras": [
            ("Quadra 1", TipoPiso.SINTETICO, 14),
            ("Quadra 2", TipoPiso.SINTETICO, 14),
            ("Quadra de Futsal", TipoPiso.SALAO, 10),
        ],
    },
    {
        "nome": "Complexo Esportivo Tabelinha",
        "endereco_completo": "Avenida do Contorno, 6120 – Savassi, Belo Horizonte – MG",
        "coordenadas": (Decimal("-19.938600"), Decimal("-43.933600")),
        "telefone_contato": "(31) 3000-0202",
        "hora_abertura": time(8),
        "hora_fechamento": time(23),
        "cnpj_alfanumerico": False,
        "gestor": ("fernanda.lima", "Fernanda", "Lima"),
        "quadras": [
            ("Campo Principal", TipoPiso.CAMPO, 22),
            ("Society A", TipoPiso.SINTETICO, 14),
        ],
    },
    {
        "nome": "Arena Pé na Areia",
        "endereco_completo": "Rua Barata Ribeiro, 520 – Copacabana, Rio de Janeiro – RJ",
        "coordenadas": (Decimal("-22.968900"), Decimal("-43.185600")),
        "telefone_contato": "(21) 3000-0303",
        "hora_abertura": time(6),
        "hora_fechamento": time(23),
        "cnpj_alfanumerico": True,
        "gestor": ("rafael.souza", "Rafael", "Souza"),
        "quadras": [
            ("Areia 1", TipoPiso.AREIA, 10),
            ("Areia 2", TipoPiso.AREIA, 10),
            ("Society Coberto", TipoPiso.SINTETICO, 12),
        ],
    },
]

JOGADORES = [
    ("Lucas", "Oliveira"),
    ("Gabriel", "Santos"),
    ("Matheus", "Costa"),
    ("Rafaela", "Mendes"),
    ("João Victor", "Lima"),
    ("Bruno", "Ferreira"),
    ("Thiago", "Ribeiro"),
    ("Camila", "Rocha"),
    ("Felipe", "Martins"),
    ("Gustavo", "Carvalho"),
    ("Ana Beatriz", "Souza"),
    ("Diego", "Araújo"),
    ("Leonardo", "Barbosa"),
    ("Juliana", "Pereira"),
    ("Vinícius", "Gomes"),
    ("Eduardo", "Nascimento"),
    ("Marcos", "Almeida"),
    ("Larissa", "Teixeira"),
    ("Rodrigo", "Moreira"),
    ("Beatriz", "Cardoso"),
    ("Pedro Henrique", "Dias"),
    ("Igor", "Monteiro"),
    ("Caio", "Freitas"),
    ("Renan", "Castro"),
    ("Mariana", "Lopes"),
    ("André", "Vieira"),
    ("Paulo", "Rezende"),
    ("Fernando", "Cunha"),
    ("Letícia", "Prado"),
    ("Otávio", "Brandão"),
    ("Samuel", "Antunes"),
    ("Hugo", "Siqueira"),
    ("Tiago", "Peixoto"),
    ("Daniel", "Fonseca"),
    ("Natália", "Ramos"),
    ("Murilo", "Assis"),
    ("Henrique", "Coelho"),
    ("Arthur", "Batista"),
    ("Sofia", "Campos"),
    ("Enzo", "Moura"),
]

# Distribuição de níveis (1 a 5) dos jogadores de demonstração.
NIVEIS_DOS_JOGADORES = [1] * 6 + [2] * 9 + [3] * 13 + [4] * 10 + [5] * 6
GOLEIROS_DE_OFICIO = 5
TOPAM_O_GOL = 6
CHECK_IN_NAS_PARTIDAS = 0.75  # parte das arenas que faz check-in pelo QR
FALTA_POR_JOGADOR = 0.04

# Permissões do grupo Gestores. O escopo (só as próprias arenas) é aplicado pelo admin.
PERMISSOES_GESTOR = {
    "arena": ("view", "change"),
    "court": ("view", "add", "change", "delete"),
    "timeslot": ("view", "add", "change", "delete"),
    "openmatch": ("view", "add", "change"),
    "booking": ("view",),
}

# Aluguel por hora da quadra inteira, por tipo de piso.
ALUGUEIS_POR_PISO = {
    TipoPiso.SINTETICO: (220, 250, 280),
    TipoPiso.SALAO: (150, 180),
    TipoPiso.AREIA: (160, 200),
    TipoPiso.CAMPO: (450, 520),
}

# (tipo de reserva, status, peso) dos horários futuros da agenda.
DISTRIBUICAO_AGENDA = (
    (TipoReserva.MENSALISTA, StatusHorario.CONFIRMADO, 28),
    (TipoReserva.AVULSO, StatusHorario.CONFIRMADO, 18),
    (TipoReserva.BLOQUEADO, StatusHorario.CONFIRMADO, 4),
    (TipoReserva.MENSALISTA, StatusHorario.CANCELADO, 5),
    (TipoReserva.AVULSO, StatusHorario.OCIOSO, 45),
)

_AGORA_REAL = timezone.now


class Relogio:
    """Relógio controlável: durante a simulação do passado, ``timezone.now()`` vem daqui."""

    def __init__(self) -> None:
        self.momento: datetime | None = None

    def agora(self) -> datetime:
        return self.momento or _AGORA_REAL()

    @contextmanager
    def no_passado(self) -> Iterator["Relogio"]:
        with mock.patch("django.utils.timezone.now", side_effect=self.agora):
            try:
                yield self
            finally:
                self.momento = None

    def ir_para(self, momento: datetime) -> None:
        self.momento = momento


@contextmanager
def _sem_recalculo_de_vagas() -> Iterator[None]:
    """Desliga o recálculo de vagas na limpeza: as partidas são apagadas logo depois."""
    post_delete.disconnect(sender=Booking, dispatch_uid="arena_booking_devolver_vaga")
    try:
        yield
    finally:
        post_delete.connect(
            devolver_vaga_apos_exclusao, sender=Booking, dispatch_uid="arena_booking_devolver_vaga"
        )


def _momento(dia: date, hora: int, minuto: int = 0) -> datetime:
    return timezone.make_aware(datetime.combine(dia, time(hora, minuto)))


class Command(BaseCommand):
    help = (
        "Apaga TODOS os dados e popula o banco com arenas, agenda, partidas, pagamentos "
        "e histórico de demonstração."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Permite rodar com DEBUG=False. Nunca use em produção.",
        )
        parser.add_argument(
            "--seed", type=int, default=2026, help="Semente aleatória (dados reproduzíveis)."
        )
        parser.add_argument(
            "--dias-de-historico",
            type=int,
            default=DIAS_DE_HISTORICO,
            help="Quantos dias passados simular (jogos finalizados, repasses).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "populate_db apaga todos os dados e cria senhas de teste. "
                "Rode apenas com DEBUG=True (ou --force, nunca em produção)."
            )
        self.rng = random.Random(options["seed"])
        self.cpfs: set[str] = set()
        self.relogio = Relogio()
        self.dias_de_historico = options["dias_de_historico"]

        # Sempre o gateway simulado (nunca cobra ninguém) e e-mails descartados.
        with override_settings(
            ARENAMATCH_GATEWAY_PAGAMENTO="arena.pagamentos.MockGateway",
            ARENAMATCH_PERMITIR_GATEWAY_SIMULADO=True,
            EMAIL_BACKEND="django.core.mail.backends.dummy.EmailBackend",
        ), transaction.atomic():
            self._limpar_banco()
            grupo = self._criar_grupo_gestores()
            self._criar_superusuario()
            self.demo, self.jogadores = self._criar_jogadores()
            arenas = self._criar_arenas(grupo)
            if self.dias_de_historico > 0:
                with self.relogio.no_passado():
                    self._simular_historico(arenas)
            self._criar_presente(arenas)
            # A data de inscrição acompanha o momento (simulado) em que a vaga foi comprada.
            Booking.objects.update(data_inscricao=F("created_at"))

        self._imprimir_resumo()

    # --- Limpeza e contas ---------------------------------------------------

    def _limpar_banco(self) -> None:
        """Apaga os dados na ordem exigida pelas FKs ``PROTECT`` (razão e inscrições primeiro)."""
        for modelo in (AvaliacaoPartida, Elogio, SinalNivel, PlayerProfile):
            modelo.objects.all().delete()
        LedgerEntry.objects.all().delete()
        Payout.objects.all().delete()
        LedgerAccount.objects.all().delete()
        Payment.objects.all().delete()
        WaitlistEntry.objects.all().delete()
        with _sem_recalculo_de_vagas():
            Booking.objects.all().delete()
        OpenMatch.objects.all().delete()
        TimeSlot.objects.all().delete()
        Court.objects.all().delete()
        Arena.objects.all().delete()
        CustomUser.objects.all().delete()
        Group.objects.filter(name=NOME_GRUPO_GESTORES).delete()

    def _criar_grupo_gestores(self) -> Group:
        grupo = Group.objects.create(name=NOME_GRUPO_GESTORES)
        codenames = [f"{acao}_{modelo}" for modelo, acoes in PERMISSOES_GESTOR.items() for acao in acoes]
        grupo.permissions.set(
            Permission.objects.filter(content_type__app_label="arena", codename__in=codenames)
        )
        return grupo

    def _criar_superusuario(self) -> CustomUser:
        # Também é jogador, para testar a reserva de vagas pela vitrine.
        return CustomUser.objects.create_superuser(
            "admin",
            "admin@example.com",
            SENHA_ADMIN,
            first_name="Admin",
            last_name="ArenaMatch",
            is_player=True,
        )

    def _criar_jogadores(self) -> tuple[CustomUser, list[CustomUser]]:
        jogadores = [
            self._criar_usuario(
                f"{slugify(nome).replace('-', '')}.{slugify(sobrenome)}",
                nome,
                sobrenome,
                SENHA_JOGADOR,
                is_player=True,
            )
            for nome, sobrenome in JOGADORES
        ]
        demo = self._criar_usuario("jogador", "Jogador", "Demo", SENHA_JOGADOR, is_player=True)
        # Celular fixo para testar o login por código (o código aparece na tela em DEBUG).
        demo.telefone = TELEFONE_DEMO
        demo.save(update_fields=["telefone"])
        niveis = list(NIVEIS_DOS_JOGADORES)
        self.rng.shuffle(niveis)
        ordem = list(range(len(jogadores)))
        self.rng.shuffle(ordem)
        goleiros = set(ordem[:GOLEIROS_DE_OFICIO])
        topam_o_gol = set(ordem[GOLEIROS_DE_OFICIO : GOLEIROS_DE_OFICIO + TOPAM_O_GOL])
        linha = (PosicaoJogador.DEFESA, PosicaoJogador.MEIO, PosicaoJogador.ATAQUE)
        regioes = ("Pinheiros", "Vila Mariana", "Centro", "Savassi", "Copacabana", "Tijuca", "Moema")
        for indice, jogador in enumerate(jogadores):
            PlayerProfile.objects.create(
                jogador=jogador,
                nivel=niveis[indice % len(niveis)],
                posicao=PosicaoJogador.GOLEIRO if indice in goleiros else self.rng.choice(linha),
                joga_no_gol=indice in topam_o_gol,
                regiao=self.rng.choice(regioes),
            )
        PlayerProfile.objects.create(
            jogador=demo, nivel=3, posicao=PosicaoJogador.MEIO, joga_no_gol=True, apelido="Demo", regiao="Pinheiros"
        )
        return demo, jogadores

    def _criar_usuario(
        self, username: str, nome: str, sobrenome: str, senha: str, **papeis: bool
    ) -> CustomUser:
        usuario = CustomUser(
            username=username,
            first_name=nome,
            last_name=sobrenome,
            email=f"{username}@example.com",
            telefone=f"(11) 9{self.rng.randint(1000, 9999)}-{self.rng.randint(1000, 9999)}",
            cpf=self._cpf_unico(),
            **papeis,
        )
        usuario.set_password(senha)
        usuario.full_clean()
        usuario.save()
        return usuario

    def _cpf_unico(self) -> str:
        while True:
            base = "".join(str(self.rng.randint(0, 9)) for _ in range(9))
            cpf = base + digitos_verificadores_cpf(base)
            if len(set(cpf)) > 1 and cpf not in self.cpfs:
                self.cpfs.add(cpf)
                return cpf

    def _cnpj(self, alfanumerico: bool) -> str:
        """CNPJ fictício válido; o alfanumérico segue o formato emitido desde 2026."""
        alfabeto = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" if alfanumerico else "0123456789"
        base = "".join(self.rng.choice(alfabeto) for _ in range(8)) + "0001"
        return base + digitos_verificadores_cnpj(base)

    # --- Arenas e agenda ----------------------------------------------------

    def _criar_arenas(self, grupo: Group) -> list[Arena]:
        arenas = []
        for dados in ARENAS:
            login, nome, sobrenome = dados["gestor"]
            gestor = self._criar_usuario(
                login, nome, sobrenome, SENHA_GESTOR, is_manager=True, is_staff=True
            )
            gestor.groups.add(grupo)
            arena = Arena.objects.create(
                manager=gestor,
                nome=dados["nome"],
                cnpj=self._cnpj(dados["cnpj_alfanumerico"]),
                endereco_completo=dados["endereco_completo"],
                telefone_contato=dados["telefone_contato"],
                hora_abertura=dados["hora_abertura"],
                hora_fechamento=dados["hora_fechamento"],
                latitude=dados["coordenadas"][0],
                longitude=dados["coordenadas"][1],
            )
            for nome_quadra, piso, capacidade in dados["quadras"]:
                Court.objects.create(
                    arena=arena, nome_ou_numero=nome_quadra, tipo_piso=piso, capacidade_padrao=capacidade
                )
            arenas.append(arena)
        return arenas

    def _faixas_do_dia(self, arena: Arena, dia: date) -> list[tuple[time, time]]:
        """Faixas de 1h do dia; arenas que fecham à meia-noite ganham o horário 23h-00h."""
        if dia.weekday() >= 5:
            return [(time(inicio), time(fim)) for inicio, fim in FAIXAS_FIM_DE_SEMANA]
        faixas = [(time(inicio), time(fim)) for inicio, fim in FAIXAS_DIA_UTIL]
        if arena.hora_fechamento == MEIA_NOITE:
            faixas.append((time(23), MEIA_NOITE))
        return faixas

    def _criar_agenda(self, arena: Arena, dias: list[date]) -> list[TimeSlot]:
        """Cria a agenda da arena nos dias e devolve os horários livres e futuros."""
        livres = []
        agora = timezone.now()
        for quadra in arena.quadras.all():
            for dia in dias:
                for inicio, fim in self._faixas_do_dia(arena, dia):
                    comeca = timezone.make_aware(datetime.combine(dia, inicio))
                    if comeca <= agora + timedelta(minutes=30):
                        # Horários que já passaram ficam como reservas confirmadas (já jogadas).
                        tipo, status = TipoReserva.MENSALISTA, StatusHorario.CONFIRMADO
                    else:
                        opcoes = [(tipo, status) for tipo, status, _ in DISTRIBUICAO_AGENDA]
                        pesos = [peso for *_, peso in DISTRIBUICAO_AGENDA]
                        tipo, status = self.rng.choices(opcoes, weights=pesos)[0]
                    horario = TimeSlot.objects.create(
                        court=quadra, data=dia, hora_inicio=inicio, hora_fim=fim, tipo_reserva=tipo, status=status
                    )
                    if status in STATUS_HORARIO_LIVRE and comeca > agora:
                        livres.append(horario)
        return livres

    def _abrir_partida(self, horario: TimeSlot) -> OpenMatch:
        """Converte um horário livre em partida aberta, como faria o gestor na agenda.

        O nível da partida só restringe a faixa se houver jogadores suficientes nela.
        """
        quadra = horario.court
        vagas = quadra.capacidade_padrao
        nivel = self.rng.choices(list(NivelCompetitividade), weights=(40, 20, 25, 15))[0]
        minimo, maximo = FAIXAS_DE_NIVEL[nivel]
        na_faixa = sum(1 for nivel_jogador in NIVEIS_DOS_JOGADORES if minimo <= nivel_jogador <= maximo)
        if na_faixa < vagas + 2:
            nivel = NivelCompetitividade.ABERTA
        return OpenMatch.objects.create(
            time_slot=horario,
            vagas_totais=vagas,
            vagas_goleiro=vagas_goleiro_sugeridas(vagas),
            valor_total_aluguel=Decimal(self.rng.choice(ALUGUEIS_POR_PISO[quadra.tipo_piso])),
            nivel_competitividade=nivel,
        )

    # --- Inscrições ----------------------------------------------------------

    def _metodo(self) -> str:
        return self.rng.choices((MetodoPagamento.PIX, MetodoPagamento.CARTAO), weights=(75, 25))[0]

    def _comprar(self, partida: OpenMatch, jogador: CustomUser, posicao: str = Posicao.LINHA, metodo: str | None = None, pagar: bool = True) -> Booking | None:
        """Faz o checkout como o jogador faria; com ``pagar``, aprova o Pix na hora."""
        try:
            inscricao = checkout.iniciar_checkout(partida, jogador, posicao=posicao, metodo=metodo or self._metodo())
            if pagar and inscricao.status == StatusInscricao.AGUARDANDO_PAGAMENTO:
                inscricao = checkout.simular_pagamento(inscricao)
        except ValidationError:
            return None
        return inscricao

    def _preencher(self, partida: OpenMatch, quantidade: int, excluir: set | None = None) -> list[Booking]:
        """Vende ``quantidade`` vagas de linha e as vagas de goleiro da partida."""
        candidatos = [j for j in self.jogadores if not excluir or j.pk not in excluir]
        self.rng.shuffle(candidatos)
        compradas = []
        goleiros = [
            j for j in candidatos if jogadores.motivo_inelegivel(partida, j, Posicao.GOLEIRO) is None
        ][: partida.vagas_goleiro]
        for jogador in goleiros:
            if inscricao := self._comprar(partida, jogador, Posicao.GOLEIRO):
                compradas.append(inscricao)
        linha = [j for j in candidatos if j not in goleiros and jogadores.motivo_inelegivel(partida, j) is None]
        for jogador in linha[:quantidade]:
            if inscricao := self._comprar(partida, jogador):
                compradas.append(inscricao)
        return compradas

    def _fazer_check_in(self, partida: OpenMatch) -> None:
        """A recepção lê o QR de quem chegou; alguns jogadores faltam."""
        if partida.status not in ("aberta", "lotada") or self.rng.random() > CHECK_IN_NAS_PARTIDAS:
            return
        for inscricao in partida.inscricoes.filter(status=StatusInscricao.CONFIRMADA):
            # O jogador de demonstração sempre aparece (para poder avaliar o jogo).
            if inscricao.player_id == self.demo.pk or self.rng.random() > FALTA_POR_JOGADOR:
                jogadores.registrar_check_in(inscricao)

    def _avaliar(self, partida: OpenMatch, alvo_de_sinais: CustomUser | None) -> None:
        """Parte de quem jogou avalia a partida, elogia colegas e, às vezes, sinaliza o nível."""
        partida.refresh_from_db()
        jogaram = list(partida.inscricoes.filter(status=StatusInscricao.CONFIRMADA, faltou=False).select_related("player"))
        avaliadores = [i.player for i in jogaram if i.player != self.demo and i.player != alvo_de_sinais]
        self.rng.shuffle(avaliadores)
        alvo_jogou = alvo_de_sinais is not None and any(i.player == alvo_de_sinais for i in jogaram)
        for posicao, autor in enumerate(avaliadores[: max(1, len(avaliadores) // 2)]):
            colegas = [i.player for i in jogaram if i.player != autor]
            elogios = {
                str(colega.pk): self.rng.choice(TipoElogio.values)
                for colega in self.rng.sample(colegas, min(2, len(colegas)))
            }
            sinais = {str(alvo_de_sinais.pk): DirecaoNivel.ACIMA} if alvo_jogou and posicao < 2 else {}
            percepcao = self.rng.choices(PercepcaoNivel.values, weights=(15, 70, 15))[0]
            jogadores.registrar_avaliacao(partida, autor, percepcao, elogios, sinais)

    # --- Histórico (passado simulado) ---------------------------------------

    def _simular_historico(self, arenas: list[Arena]) -> None:
        """Simula os últimos dias: vendas, cancelamentos, quórum, encerramento e repasses."""
        hoje = timezone.localdate()
        dias = [hoje - timedelta(days=n) for n in range(self.dias_de_historico, 0, -1)]
        self.relogio.ir_para(_momento(dias[0] - timedelta(days=3), 9))

        partidas_passadas: list[OpenMatch] = []
        for arena in arenas:
            livres = self._criar_agenda(arena, dias)
            por_dia: dict[date, list[TimeSlot]] = defaultdict(list)
            for horario in livres:
                por_dia[horario.data].append(horario)
            for dia in dias:
                for horario in self.rng.sample(por_dia[dia], min(PARTIDAS_PASSADAS_POR_DIA, len(por_dia[dia]))):
                    partidas_passadas.append(self._abrir_partida(horario))

        sem_quorum = self.rng.choice(partidas_passadas)
        # O jogador de demonstração já jogou (antes de as partidas lotarem) e também
        # desistiu de uma partida, o que lhe rendeu crédito.
        elegiveis = [
            p for p in partidas_passadas if p is not sem_quorum and jogadores.motivo_inelegivel(p, self.demo) is None
        ]
        for partida in elegiveis[-3:-1]:
            self._comprar(partida, self.demo, metodo=MetodoPagamento.PIX)
        if elegiveis and (desistencia := self._comprar(elegiveis[0], self.demo, metodo=MetodoPagamento.CARTAO)):
            checkout.cancelar_inscricao(desistencia)

        for partida in partidas_passadas:
            if partida is sem_quorum:
                self._preencher(partida, 2)
                continue
            vendidas = self._preencher(partida, self.rng.randint(partida.minimo_jogadores, partida.vagas_linha))
            pagas = [i for i in vendidas if not i.gratuita]
            # Desistências com mais de 24h de antecedência viram crédito.
            if pagas and self.rng.random() < 0.3:
                checkout.cancelar_inscricao(self.rng.choice(pagas))

        # Um jogador que se declarou abaixo do que joga recebe sinais dos colegas.
        alvo_de_sinais = next(
            (j for j in self.jogadores if j.perfil.nivel == 2 and j.perfil.posicao != PosicaoJogador.GOLEIRO), None
        )

        # O tempo passa: prazos do mínimo, check-in, fim dos jogos, avaliações e repasses.
        por_id = {p.pk: p for p in partidas_passadas}
        eventos = sorted(
            [(p.prazo_quorum, "quorum", p.pk) for p in partidas_passadas]
            + [(p.time_slot.inicio + timedelta(minutes=10), "check_in", p.pk) for p in partidas_passadas]
            + [(p.time_slot.fim + timedelta(minutes=5), "fim", p.pk) for p in partidas_passadas]
            + [(p.time_slot.fim + timedelta(hours=2), "avaliacao", p.pk) for p in partidas_passadas]
            + [(_momento(dia, 6), "repasse", None) for dia in dias + [hoje]],
            key=lambda evento: evento[0],
        )
        for momento, evento, partida_id in eventos:
            if momento >= _AGORA_REAL():
                continue
            self.relogio.ir_para(momento)
            partida = por_id.get(partida_id)
            if partida is not None:
                partida.refresh_from_db()
            if evento == "quorum":
                partidas.conferir_quorum()
            elif evento == "check_in":
                self._fazer_check_in(partida)
            elif evento == "fim":
                partidas.finalizar_partidas()
            elif evento == "avaliacao":
                if partida.status == StatusPartida.FINALIZADA:
                    self._avaliar(partida, alvo_de_sinais)
            else:
                razao.gerar_repasses()

    # --- Presente ------------------------------------------------------------

    def _criar_presente(self, arenas: list[Arena]) -> None:
        """Agenda dos próximos dias com partidas em vários estágios de venda."""
        hoje = timezone.localdate()
        dias = [hoje + timedelta(days=n) for n in range(DIAS_DE_AGENDA)]
        partidas_futuras: list[OpenMatch] = []
        for arena in arenas:
            livres = self._criar_agenda(arena, dias)
            escolhidos = self.rng.sample(livres, min(PARTIDAS_POR_ARENA, len(livres)))
            partidas_futuras += [self._abrir_partida(h) for h in sorted(escolhidos, key=lambda h: (h.data, h.hora_inicio))]

        candidatas = [p for p in partidas_futuras if p.vagas_linha <= len(self.jogadores) - p.vagas_goleiro]
        lotadas = set(self.rng.sample(candidatas, min(PARTIDAS_LOTADAS, len(candidatas))))
        for partida in partidas_futuras:
            if partida in lotadas:
                inscritos = self._preencher(partida, partida.vagas_linha)
                inscritos_ids = {i.player_id for i in inscritos}
                fila = [
                    j for j in self.jogadores
                    if j.pk not in inscritos_ids and jogadores.motivo_inelegivel(partida, j) is None
                ]
                for jogador in self.rng.sample(fila, min(2, len(fila))):
                    checkout.entrar_na_lista_de_espera(partida, jogador)
            else:
                maximo = max(1, min(partida.vagas_linha - 2, round(partida.vagas_linha * 0.85)))
                self._preencher(partida, self.rng.randint(1, maximo))

        abertas = [p for p in partidas_futuras if p not in lotadas and p.status == StatusPartida.ABERTA]
        # Alguns jogadores estão no meio do Pix (vaga reservada por 10 minutos).
        for partida in self.rng.sample(abertas, min(3, len(abertas))):
            inscritos = set(partida.inscricoes.values_list("player_id", flat=True))
            if livre := next((j for j in self.jogadores if j.pk not in inscritos), None):
                self._comprar(partida, livre, metodo=MetodoPagamento.PIX, pagar=False)

        # A conta de demonstração começa com duas partidas marcadas, uma paga com o crédito.
        distantes = [
            p for p in abertas
            if p.time_slot.inicio > timezone.now() + timedelta(days=1)
            and jogadores.motivo_inelegivel(p, self.demo) is None
        ]
        for partida, metodo in zip(distantes[:2], (MetodoPagamento.PIX, MetodoPagamento.CREDITO)):
            if self._comprar(partida, self.demo, metodo=metodo) is None:
                self._comprar(partida, self.demo, metodo=MetodoPagamento.PIX)

        # Uma partida cancelada pela arena, com todos reembolsados.
        if len(distantes) > 2:
            partidas.cancelar_partida(distantes[-1], MotivoCancelamento.ARENA)

    # --- Saída ---------------------------------------------------------------

    def _imprimir_resumo(self) -> None:
        self.stdout.write(self.style.SUCCESS("\nBanco populado com sucesso!\n"))
        contagens = (
            ("Arenas", Arena.objects.count()),
            ("Quadras", Court.objects.count()),
            ("Horários na agenda", TimeSlot.objects.count()),
            ("Partidas", OpenMatch.objects.count()),
            ("  - lotadas", OpenMatch.objects.filter(status=StatusPartida.LOTADA).count()),
            ("  - finalizadas", OpenMatch.objects.filter(status=StatusPartida.FINALIZADA).count()),
            ("  - canceladas", OpenMatch.objects.filter(status=StatusPartida.CANCELADA).count()),
            ("Inscrições", Booking.objects.count()),
            ("Pagamentos", Payment.objects.count()),
            ("Lançamentos no razão", LedgerEntry.objects.count()),
            ("Repasses", Payout.objects.count()),
            ("Usuários", CustomUser.objects.count()),
        )
        for rotulo, total in contagens:
            self.stdout.write(f"  {rotulo:<22}{total:>5}")

        self.stdout.write(self.style.MIGRATE_HEADING("\nAcessos de teste (login / senha)"))
        acessos = [
            ("Superusuário", "admin", SENHA_ADMIN),
            *[(f"Gestor - {a['nome']}", a["gestor"][0], SENHA_GESTOR) for a in ARENAS],
            ("Jogador de demonstração", "jogador", SENHA_JOGADOR),
            ("Jogador demo pelo celular (código na tela)", TELEFONE_DEMO, "—"),
            ("Outros jogadores", "lucas.oliveira (etc.)", SENHA_JOGADOR),
        ]
        for papel, login, senha in acessos:
            self.stdout.write(f"  {papel:<42}{login:<24}{senha}")
        self.stdout.write(
            "\n  Site: http://127.0.0.1:8000/  |  App: http://127.0.0.1:8000/app/"
            "  |  Portal: http://127.0.0.1:8000/manager/  |  Admin: http://127.0.0.1:8000/admin/\n"
        )
