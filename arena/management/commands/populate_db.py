"""Comando ``populate_db``: recria o banco com dados de demonstração realistas.

Uso: ``python manage.py populate_db``. ATENÇÃO: apaga TODOS os dados antes. Só roda
com ``DEBUG=True`` (ou ``--force``), porque cria contas com senhas fracas e conhecidas.
Todos os registros passam por ``save()``, ou seja, pelas mesmas regras de negócio
do sistema (agenda sem conflitos, vagas, lotação etc.).
"""

import random
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models.signals import post_delete
from django.utils import timezone
from django.utils.text import slugify

from arena.models import (
    MEIA_NOITE,
    STATUS_HORARIO_LIVRE,
    Arena,
    Booking,
    Court,
    CustomUser,
    NivelCompetitividade,
    OpenMatch,
    StatusHorario,
    StatusPagamento,
    StatusPartida,
    TimeSlot,
    TipoPiso,
    TipoReserva,
    devolver_vaga_apos_exclusao,
)
from arena.validators import digitos_verificadores_cnpj, digitos_verificadores_cpf

SENHA_ADMIN = "admin123"
SENHA_GESTOR = "gestor123"
SENHA_JOGADOR = "jogador123"
NOME_GRUPO_GESTORES = "Gestores"

PARTIDAS_POR_ARENA = 6
PARTIDAS_LOTADAS = 3
DIAS_DE_AGENDA = 7
FAIXAS_DIA_UTIL = ((18, 19), (19, 20), (20, 21), (21, 22), (22, 23))
FAIXAS_FIM_DE_SEMANA = ((9, 10), (10, 11), (11, 12), (16, 17), (17, 18), (18, 19), (19, 20))

ARENAS: list[dict[str, Any]] = [
    {
        "nome": "Arena Gol de Placa",
        "endereco_completo": "Rua Harmonia, 850 – Vila Madalena, São Paulo – SP",
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
]

# Permissões do grupo Gestores. O escopo (só as próprias arenas) é aplicado pelo admin.
PERMISSOES_GESTOR = {
    "arena": ("view", "change"),
    "court": ("view", "add", "change", "delete"),
    "timeslot": ("view", "add", "change", "delete"),
    "openmatch": ("view", "add", "change", "delete"),
    "booking": ("view", "add", "change", "delete"),
}

PRECOS_POR_PISO = {
    TipoPiso.SINTETICO: (20, 25, 30),
    TipoPiso.SALAO: (15, 18, 20),
    TipoPiso.AREIA: (20, 25),
    TipoPiso.CAMPO: (30, 35, 40),
}

# (tipo de reserva, status, peso) dos horários futuros da agenda.
DISTRIBUICAO_AGENDA = (
    (TipoReserva.MENSALISTA, StatusHorario.CONFIRMADO, 28),
    (TipoReserva.AVULSO, StatusHorario.CONFIRMADO, 18),
    (TipoReserva.BLOQUEADO, StatusHorario.CONFIRMADO, 4),
    (TipoReserva.MENSALISTA, StatusHorario.CANCELADO, 5),
    (TipoReserva.AVULSO, StatusHorario.OCIOSO, 45),
)


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


class Command(BaseCommand):
    help = (
        "Apaga TODOS os dados e popula o banco com arenas, agenda, partidas abertas "
        "e inscrições de demonstração."
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

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "populate_db apaga todos os dados e cria senhas de teste. "
                "Rode apenas com DEBUG=True (ou --force, nunca em produção)."
            )
        self.rng = random.Random(options["seed"])
        self.agora = timezone.localtime()
        self.cpfs: set[str] = set()

        with transaction.atomic():
            self._limpar_banco()
            grupo = self._criar_grupo_gestores()
            self._criar_superusuario()
            demo, jogadores = self._criar_jogadores()
            arenas = self._criar_arenas(grupo)
            horarios_livres = self._criar_agenda(arenas)
            partidas = self._criar_partidas(horarios_livres)
            self._criar_inscricoes(partidas, jogadores, demo)

        self._imprimir_resumo()

    # --- Limpeza e contas ---------------------------------------------------

    def _limpar_banco(self) -> None:
        """Apaga os dados na ordem exigida pelas FKs ``PROTECT`` (inscrições primeiro)."""
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

    # --- Arenas, agenda e partidas -----------------------------------------

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

    def _criar_agenda(self, arenas: list[Arena]) -> dict[Arena, list[TimeSlot]]:
        """Cria a agenda dos próximos dias e devolve os horários livres e futuros por arena."""
        livres: dict[Arena, list[TimeSlot]] = defaultdict(list)
        hoje = self.agora.date()
        for arena in arenas:
            for quadra in arena.quadras.all():
                for deslocamento in range(DIAS_DE_AGENDA):
                    dia = hoje + timedelta(days=deslocamento)
                    for inicio, fim in self._faixas_do_dia(arena, dia):
                        horario = self._criar_horario(quadra, dia, inicio, fim)
                        if horario.status in STATUS_HORARIO_LIVRE and not horario.ja_comecou:
                            livres[arena].append(horario)
        return livres

    def _criar_horario(self, quadra: Court, dia: date, inicio: time, fim: time) -> TimeSlot:
        comeca = timezone.make_aware(datetime.combine(dia, inicio))
        if comeca <= self.agora + timedelta(minutes=30):
            # Horários que já passaram ficam como reservas confirmadas (já jogadas).
            tipo, status = self.rng.choice(
                [(TipoReserva.MENSALISTA, StatusHorario.CONFIRMADO), (TipoReserva.AVULSO, StatusHorario.CONFIRMADO)]
            )
        else:
            opcoes = [(tipo, status) for tipo, status, _ in DISTRIBUICAO_AGENDA]
            pesos = [peso for *_, peso in DISTRIBUICAO_AGENDA]
            tipo, status = self.rng.choices(opcoes, weights=pesos)[0]
        return TimeSlot.objects.create(
            court=quadra, data=dia, hora_inicio=inicio, hora_fim=fim, tipo_reserva=tipo, status=status
        )

    def _criar_partidas(self, livres: dict[Arena, list[TimeSlot]]) -> list[OpenMatch]:
        """Converte horários livres em partidas abertas, como faria a action do admin."""
        niveis = list(NivelCompetitividade)
        partidas = []
        for horarios in livres.values():
            escolhidos = self.rng.sample(horarios, min(PARTIDAS_POR_ARENA, len(horarios)))
            for horario in sorted(escolhidos, key=lambda h: (h.data, h.hora_inicio)):
                quadra = horario.court
                # Às vezes um grupo já tem parte dos jogadores e abre só as vagas restantes.
                vagas = quadra.capacidade_padrao - self.rng.choice((0, 0, 0, 2, 4))
                partidas.append(
                    OpenMatch.objects.create(
                        time_slot=horario,
                        vagas_totais=vagas,
                        preco_por_vaga=Decimal(self.rng.choice(PRECOS_POR_PISO[quadra.tipo_piso])),
                        nivel_competitividade=self.rng.choices(niveis, weights=(45, 25, 30))[0],
                    )
                )
        return partidas

    # --- Inscrições ----------------------------------------------------------

    def _criar_inscricoes(
        self, partidas: list[OpenMatch], jogadores: list[CustomUser], demo: CustomUser
    ) -> None:
        candidatas = [p for p in partidas if p.vagas_totais <= len(jogadores)]
        lotadas = set(self.rng.sample(candidatas, min(PARTIDAS_LOTADAS, len(candidatas))))
        for partida in partidas:
            if partida in lotadas:
                quantidade = partida.vagas_totais
            else:
                maximo = min(partida.vagas_totais - 2, len(jogadores), round(partida.vagas_totais * 0.85))
                quantidade = self.rng.randint(1, max(1, maximo))
            for jogador in self.rng.sample(jogadores, quantidade):
                self._inscrever(partida, jogador, self.rng.choices(
                    (StatusPagamento.PAGO, StatusPagamento.PENDENTE), weights=(60, 40)
                )[0])

        abertas = [p for p in partidas if p not in lotadas]
        # Desistências já reembolsadas: ficam no histórico e não ocupam vaga.
        for partida in self.rng.sample(abertas, min(3, len(abertas))):
            inscritos = set(partida.inscricoes.values_list("player_id", flat=True))
            desistente = next(j for j in jogadores if j.pk not in inscritos)
            self._inscrever(partida, desistente, StatusPagamento.REEMBOLSADO)

        # A conta de demonstração já começa com duas partidas marcadas.
        for partida, status in zip(abertas[:2], (StatusPagamento.PENDENTE, StatusPagamento.PAGO)):
            self._inscrever(partida, demo, status)

    def _inscrever(self, partida: OpenMatch, jogador: CustomUser, status: str) -> Booking:
        return Booking.objects.create(
            open_match=partida,
            player=jogador,
            status_pagamento=status,
            data_inscricao=self.agora - timedelta(minutes=self.rng.randint(30, 72 * 60)),
        )

    # --- Saída ---------------------------------------------------------------

    def _imprimir_resumo(self) -> None:
        self.stdout.write(self.style.SUCCESS("\nBanco populado com sucesso!\n"))
        contagens = (
            ("Arenas", Arena.objects.count()),
            ("Quadras", Court.objects.count()),
            ("Horários na agenda", TimeSlot.objects.count()),
            ("Partidas abertas", OpenMatch.objects.count()),
            ("  - lotadas", OpenMatch.objects.filter(status=StatusPartida.LOTADA).count()),
            ("Inscrições", Booking.objects.count()),
            ("Usuários", CustomUser.objects.count()),
        )
        for rotulo, total in contagens:
            self.stdout.write(f"  {rotulo:<22}{total:>5}")

        self.stdout.write(self.style.MIGRATE_HEADING("\nAcessos de teste (login / senha)"))
        acessos = [
            ("Superusuário", "admin", SENHA_ADMIN),
            *[(f"Gestor - {a['nome']}", a["gestor"][0], SENHA_GESTOR) for a in ARENAS],
            ("Jogador de demonstração", "jogador", SENHA_JOGADOR),
            ("Outros jogadores", "lucas.oliveira (etc.)", SENHA_JOGADOR),
        ]
        for papel, login, senha in acessos:
            self.stdout.write(f"  {papel:<42}{login:<24}{senha}")
        self.stdout.write(
            "\n  Vitrine: http://127.0.0.1:8000/  |  Painel: http://127.0.0.1:8000/admin/"
            "  |  API: http://127.0.0.1:8000/api/\n"
        )
