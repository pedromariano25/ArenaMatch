# ArenaMatch

**SaaS B2B2C para gestão de complexos esportivos e matchmaking de jogadores avulsos.**

O ArenaMatch conecta duas pontas do futebol amador. Os donos de quadras têm um
software de gestão para a operação do dia a dia. Os jogadores sem time fixo
encontram partidas abertas para completar.

---

## Modelo de negócio

| Frente | Público | O que entrega |
| --- | --- | --- |
| **B2B** | Gestores de complexos esportivos | **ArenaManager**, o portal do gestor: dashboard financeiro, agenda semanal das quadras (mensalistas, avulsos e bloqueios), financeiro e configurações. Com um clique, transforma **horários vagos** em **partidas abertas** para a comunidade. |
| **B2C** | Jogadores avulsos | Vitrine (web e app mobile) para encontrar partidas abertas por dia, nível, piso e arena, e reservar vagas individuais. |

As duas frentes compartilham o mesmo banco de dados. A receita da arena cresce
porque horários que ficariam vazios são vendidos vaga a vaga.

A frente B2B é o **Portal do Gestor (ArenaManager)**, em `/manager/`. A frente
B2C tem uma **vitrine web** e **APIs REST** para o app mobile. O **Django Admin**
fica como back-office interno da equipe da plataforma.

O pagamento acontece **100% dentro do app** (modelo de take rate): o jogador paga a
vaga com Pix, cartão ou crédito, o ArenaMatch fica com a taxa de serviço e a parte
da quadra vai para a carteira da arena, liberada no dia seguinte ao jogo.

## Motor financeiro

| Regra | Como funciona |
| --- | --- |
| Preço da vaga | Aluguel total ÷ vagas de linha (goleiro não paga) + taxa de serviço de 15% sobre a parte da quadra, com mínimo de R$ 2,00 (contrato de cada arena) |
| Cartão | 5% a mais que o Pix, para cobrir a tarifa da operadora |
| Reserva | Ao iniciar o checkout, a vaga fica segura por 10 minutos; sem pagamento, ela volta para a partida |
| Cancelamento | Até 24h antes do jogo, crédito integral na carteira do jogador; depois disso, o jogador pode repassar a vaga para a lista de espera e recebe crédito se alguém assumir |
| Mínimo de jogadores | Cada arena define o percentual (padrão 70%) e o prazo (padrão 3h antes); sem o mínimo, a partida é cancelada e todos são reembolsados |
| Razão contábil | Toda movimentação vira um lançamento imutável; o saldo é a soma dos lançamentos. A arena vê o saldo disponível, a liberar e os repasses |
| Repasse | O valor da quadra fica retido até o dia seguinte à partida e então é transferido à arena |

O provedor de pagamentos fica atrás da interface `Gateway` (`arena/pagamentos.py`).
Em desenvolvimento roda o `MockGateway`: o cartão é aprovado na hora e o Pix fica
pendente até o jogador clicar em "Simular pagamento aprovado". Ele se recusa a rodar
fora do ambiente de desenvolvimento. Para usar um gateway real (Mercado Pago,
Pagar.me, Asaas...), implemente a interface e aponte `ARENAMATCH_GATEWAY_PAGAMENTO`
para a classe. As notificações (webhooks) chegam em `/pagamentos/webhook/`.

## Jogadores, níveis e partidas equilibradas

| Regra | Como funciona |
| --- | --- |
| Perfil | Antes da primeira partida, o jogador responde 3 perguntas (autoavaliação, frequência e experiência) e informa a posição. O nível (1 Iniciante a 5 Elite) sai das respostas |
| Faixa da partida | Iniciante aceita níveis 1–2, Intermediário 2–4, Avançado 4–5 e Aberta a todos 1–5. As faixas se sobrepõem de propósito |
| Trava de nível | Quem está fora da faixa não entra. Se ainda houver vaga, a trava cai 1h antes do prazo do mínimo de jogadores (padrão: 4h antes do jogo) |
| Goleiro | Vaga própria e grátis, só para quem joga no gol (posição ou "topo jogar no gol"). Goleiro que falta sem avisar perde a vaga grátis por 14 dias |
| Check-in | O comprovante tem um QR; a recepção lê pelo celular (Portal do Gestor → Check-in). Se a arena fez check-in no jogo, quem não apareceu leva falta |
| Confiabilidade | Percentual de presença nos jogos com check-in, exibido no perfil |
| Avaliação pós-jogo | Até 7 dias depois do jogo: nível da partida, elogios (só positivos) e, em partidas com faixa, sinal de que um colega joga acima/abaixo dela. Três colegas diferentes sinalizando a mesma coisa ajustam o nível em um ponto |
| Times | O sistema sugere dois times de força parecida (nível e posição), com um goleiro em cada |

## Stack

| Camada | Tecnologia |
| --- | --- |
| Linguagem | Python 3.15 |
| Framework web | Django 5.2 LTS |
| APIs B2C | Django REST Framework 3.18 (token e sessão) |
| Vitrine web | Templates Django + Tailwind CSS 4 (via CDN) |
| Banco de dados | PostgreSQL 18 (driver psycopg 3), configurado por `DATABASE_URL` |
| Rotinas automáticas | APScheduler, num processo próprio (`manage.py agendador`) |
| Configuração | Variáveis de ambiente via `python-dotenv` |

## Como rodar localmente

**Pré-requisitos:** Python 3.15, PostgreSQL 14 ou superior e Git.

```powershell
# 1. Clone o repositório
git clone <url-do-repositorio> arenamatch
cd arenamatch

# 2. Crie e ative o ambiente virtual
python -m venv venv
.\venv\Scripts\Activate.ps1        # Linux/macOS: source venv/bin/activate

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Configure as variáveis de ambiente
Copy-Item .env.example .env        # Linux/macOS: cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(50))"
# Cole o valor gerado em DJANGO_SECRET_KEY, dentro do arquivo .env

# 5. Crie o usuário e o banco no PostgreSQL (uma vez só) e ajuste DATABASE_URL no .env
psql -U postgres -c "CREATE ROLE arenamatch LOGIN CREATEDB PASSWORD 'sua-senha';"
psql -U postgres -c "CREATE DATABASE arenamatch OWNER arenamatch ENCODING 'UTF8' TEMPLATE template0;"

# 6. Crie as tabelas e carregue os dados de demonstração
python manage.py migrate
python manage.py populate_db       # opcional: APAGA tudo e recria os dados de teste

# 7. Suba o servidor de desenvolvimento
python manage.py runserver

# 8. Em outro terminal, suba o agendador de rotinas automáticas
python manage.py agendador
```

| Endereço | O que é |
| --- | --- |
| <http://127.0.0.1:8000/> | Vitrine para os jogadores (B2C) |
| <http://127.0.0.1:8000/manager/> | Portal do Gestor, o ArenaManager (B2B) |
| <http://127.0.0.1:8000/api/> | API REST navegável |
| <http://127.0.0.1:8000/admin/> | Back-office da plataforma (Django Admin) |

> **Windows:** se o PowerShell bloquear o `Activate.ps1`, libere scripts locais
> para o seu usuário com `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### Acessos de demonstração

Criados pelo `populate_db`, que só roda com `DEBUG=True`. As senhas são
fracas de propósito: **não use esses acessos fora do ambiente local**.

| Perfil | Onde entrar | Login | Senha |
| --- | --- | --- | --- |
| Gestor da Arena Gol de Placa | `/manager/` | `carlos.andrade` | `gestor123` |
| Gestora do Complexo Esportivo Tabelinha | `/manager/` | `fernanda.lima` | `gestor123` |
| Gestor da Arena Pé na Areia | `/manager/` | `rafael.souza` | `gestor123` |
| Jogador de demonstração | `/` | `jogador` | `jogador123` |
| Demais jogadores (ex.: `lucas.oliveira`) | `/` | — | `jogador123` |
| Superusuário (portal com todas as arenas, back-office e vitrine) | qualquer um | `admin` | `admin123` |

Sem os dados de demonstração, crie um administrador com `python manage.py createsuperuser`.

### Variáveis de ambiente

| Variável | Obrigatória | Padrão | Descrição |
| --- | --- | --- | --- |
| `DJANGO_SECRET_KEY` | Sim | — | Chave criptográfica do Django. O projeto não sobe sem ela. |
| `DJANGO_DEBUG` | Não | `False` | Ative (`True`) apenas em desenvolvimento. |
| `DJANGO_ALLOWED_HOSTS` | Não | vazio | Hosts aceitos, separados por vírgula. |
| `DATABASE_URL` | Sim | — | Conexão com o PostgreSQL (`postgres://usuario:senha@host:porta/banco`). O usuário precisa de `CREATEDB` para os testes. |
| `ARENAMATCH_GATEWAY_PAGAMENTO` | Não | `arena.pagamentos.MockGateway` | Classe do gateway de pagamentos. |
| `ARENAMATCH_PERMITIR_GATEWAY_SIMULADO` | Não | igual a `DJANGO_DEBUG` | Libera o gateway simulado (desenvolvimento, testes e CI). |
| `ARENAMATCH_URL_BASE` | Não | `http://127.0.0.1:8000` | Endereço público usado nos links dos e-mails. |
| `DJANGO_EMAIL_BACKEND` | Não | console | Backend de e-mail (em produção, SMTP). |

### Rotinas automáticas

O agendador roda num processo separado do servidor web e executa cada rotina
registrada em `arena/rotinas.py` no seu intervalo. As rotinas são idempotentes:
rodar com atraso ou duas vezes não duplica efeitos. Mantenha **um único**
agendador por ambiente.

```powershell
python manage.py agendador            # roda até Ctrl+C
python manage.py agendador --uma-vez  # executa cada rotina uma vez (cron, conferência)
```

## API REST

Autenticação por token (`Authorization: Token <chave>`) ou sessão. Listas são
paginadas (`?page=`), com 20 itens por página.

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/api/partidas/` | Partidas abertas que ainda não começaram. Filtros: `nivel`, `piso`, `arena` (slug), `data`, `de`, `ate` |
| GET | `/api/partidas/{id}/` | Detalhes, com os jogadores inscritos |
| POST | `/api/partidas/{id}/inscricoes/` | Checkout: `posicao` (`linha`/`goleiro`) e `metodo_pagamento` (`pix`/`cartao`/`credito`) |
| POST, DELETE | `/api/partidas/{id}/lista-de-espera/` | Entra ou sai da lista de espera |
| GET | `/api/minhas-inscricoes/` | Inscrições do jogador autenticado |
| GET, DELETE | `/api/minhas-inscricoes/{id}/` | Detalha ou cancela (reserva, ou vaga paga até 24h antes, com crédito) |
| POST | `/api/minhas-inscricoes/{id}/repassar/` | Repassa a vaga para a lista de espera (a menos de 24h) |
| POST | `/api/minhas-inscricoes/{id}/simular-pagamento/` | Aprova o Pix pendente (só com o gateway simulado) |
| GET | `/api/carteira/` | Crédito do jogador e movimentações |
| GET | `/api/arenas/` | Arenas e quadras |
| POST | `/api/auth/cadastro/` | Cria uma conta de jogador e devolve o token |
| POST | `/api/auth/token/` | Troca usuário e senha por um token |
| GET | `/api/me/` | Usuário autenticado (com o perfil de jogador) |
| GET, PUT | `/api/perfil-jogador/` | Perfil esportivo; o PUT com o questionário define o nível |

As regras de negócio (partida lotada, inscrição duplicada, partida já iniciada
etc.) retornam **HTTP 400** com a mensagem em `non_field_errors`.

## Testes

```powershell
python manage.py test arena
```

## Estrutura do projeto

```text
.
├── arena/
│   ├── api/                # Serializers, views, permissões e rotas da API REST
│   ├── management/         # Comandos populate_db (dados de demonstração) e agendador
│   ├── migrations/
│   ├── templates/          # Vitrine e portal (arena/) e customizações do back-office (admin/)
│   ├── templatetags/       # Filtros de apresentação, ícones e indicadores
│   ├── tests/              # Testes de modelos, portal, admin, API, vitrine e populate_db
│   ├── admin.py            # Back-office da plataforma (Django Admin)
│   ├── agendador.py        # Monta o agendador (APScheduler) com as rotinas registradas
│   ├── checkout.py         # Inscrição: reserva, pagamento, expiração, cancelamento, repasse, lista de espera
│   ├── gestao.py           # Cálculos do portal: KPIs, grade da agenda, financeiro
│   ├── jogadores.py        # Perfil e nível, elegibilidade, check-in, avaliações e times
│   ├── models.py           # Entidades e regras de negócio
│   ├── notificacoes.py     # E-mails aos jogadores (enviados depois do commit)
│   ├── pagamentos.py       # Interface Gateway e o MockGateway de desenvolvimento
│   ├── partidas.py         # Partida: cancelamento com reembolso, mínimo de jogadores, encerramento
│   ├── razao.py            # Razão contábil: carteiras, lançamentos, saldos e repasses
│   ├── rotinas.py          # Rotinas automáticas (@rotina) executadas pelo agendador
│   ├── urls_gestor.py      # Rotas do Portal do Gestor (/manager/)
│   ├── validators.py       # CPF, CNPJ (inclusive alfanumérico) e telefone
│   └── views.py            # Vitrine (B2C) e Portal do Gestor (B2B)
├── config/                 # settings, urls, wsgi/asgi
├── .env.example            # Modelo de variáveis de ambiente (o .env real não é versionado)
├── manage.py
└── requirements.txt
```

## Roadmap

O MVP (modelagem, painel B2B, APIs e vitrine) está implementado. Próximos passos:

1. **Pagamentos:** trocar o `MockGateway` por um gateway real com split (Mercado Pago, Pagar.me ou Asaas).
2. **Agenda recorrente:** gerar horários de mensalistas e ociosos em lote.
3. **Notificações:** e-mail e WhatsApp na inscrição e no cancelamento de partidas.
4. **Produção:** build do Tailwind (sem CDN), arquivos estáticos e deploy.

## Convenções

- Commits seguem o padrão [Conventional Commits](https://www.conventionalcommits.org/pt-br/)
  (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`).
- Código em conformidade com a PEP 8, com type hints e docstrings.
- Interface "Clean SaaS" com Tailwind: fundo `slate-50`, cartões brancos com borda
  sutil e `shadow-sm`, destaque `emerald-600` e texto `slate-800`/`slate-900`, sem gradientes.
- Regras de negócio ficam nos modelos (`clean()`), e `save()` sempre valida.
- Segredos (`.env`) **nunca** são versionados.
