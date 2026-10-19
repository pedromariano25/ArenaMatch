# ArenaMatch

**SaaS B2B2C para gestão de complexos esportivos e matchmaking de jogadores avulsos.**

O ArenaMatch conecta duas pontas do futebol amador. Os donos de quadras têm um
software de gestão para a operação do dia a dia. Os jogadores sem time fixo
encontram partidas abertas para completar.

---

## Modelo de negócio

| Frente | Público | O que entrega |
| --- | --- | --- |
| **B2B** | Gestores de complexos esportivos | **ArenaManager**, o portal do gestor: painel com saldo a receber, vagas vendidas e horários ociosos, agenda das quadras (mensalistas, avulsos e bloqueios), check-in, financeiro e ajustes. Com um toque, transforma **horários vagos** em **partidas abertas** para a comunidade. |
| **B2C** | Jogadores avulsos | App web mobile-first para achar partidas por dia, nível, piso, arena ou distância, ver quem vai e garantir a vaga pagando pelo app. |
| **C2C** | Organizadores de peladas (mensalistas) | O grupo já tem o horário com a arena e vende pelo app as vagas que faltam. O valor da vaga vai para a carteira do organizador (saque via Pix), e o ArenaMatch fica com a taxa. |

As duas frentes compartilham o mesmo banco de dados. A receita da arena cresce
porque horários que ficariam vazios são vendidos vaga a vaga.

A frente B2B é o **Portal do Gestor (ArenaManager)**, em `/manager/`. A frente
B2C tem o **site** em `/`, o **app do jogador** em `/app/` e **APIs REST** para o
app mobile nativo. O **Django Admin** fica como back-office interno da equipe da
plataforma.

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

## App do jogador

| Tela | O que faz |
| --- | --- |
| Site (`/`) | Página de apresentação com os jogos em destaque e a proposta para arenas |
| Feed (`/app/`) | Partidas com os rostos de quem já vai, vagas restantes e preço. Filtros de um toque: dia (hoje, amanhã, fim de semana), "meu nível", piso e "perto de mim" (usa a localização do aparelho e ordena por distância) |
| Garantir vaga | O botão do feed abre o checkout rápido (Pix, cartão ou crédito; goleiro grátis) sem sair da lista |
| Entrar | Pelo celular, com código de 6 dígitos por SMS. A conta de jogador é criada no primeiro acesso. Entrar com usuário e senha continua disponível em `/app/entrar/senha/` |
| Comprovante | QR de check-in, "Adicionar à agenda" e "Como chegar" |

O código de acesso vale 10 minutos, aceita 5 tentativas e o mesmo número pode
pedir 3 códigos a cada 15 minutos; só o hash do código fica no banco. Em
desenvolvimento, o SMS sai no log do servidor e o código aparece na própria tela.

Os endereços antigos da vitrine (`/partidas/...`, `/minhas-inscricoes/` etc.)
redirecionam para os equivalentes em `/app/`.

## Pelada de grupo (C2C)

O mensalista que organiza uma pelada fechada vende pelo app as vagas que faltam
para fechar os times. Fica em `/app/organizar/` (botão **Organizar**).

| Regra | Como funciona |
| --- | --- |
| Horário | É o horário de mensalista do grupo numa quadra parceira (o cadastrado pela arena ou um novo, declarado pelo organizador). Aparece na agenda da arena como "Pelada de grupo" |
| Preço | O organizador define quanto recebe por vaga. A taxa C2C vai por cima: 20%, com mínimo de R$ 5 por vaga de linha. Ex.: R$ 15 para o organizador + R$ 5 = R$ 20 para o jogador |
| Goleiro de aluguel | Vagas só para o gol, com preço próprio (taxa só percentual) ou grátis. Vale também nas partidas das arenas, que seguem com goleiro grátis por padrão |
| Quórum | Não há: o grupo joga mesmo sem vender as vagas |
| Dinheiro | A parte da vaga vai para o saldo do organizador (carteira `ORGANIZADOR` no razão, não para a arena), liberada no dia seguinte ao jogo. Saque via Pix de todo o disponível, mínimo de R$ 10 (`Wallet` guarda a chave Pix; `Saque` registra cada transferência) |
| Cancelamento | O organizador (ou a arena, na sua quadra) cancela e todos recebem o dinheiro de volta. Para o jogador, valem as regras de sempre (crédito até 24h antes) |

No feed, partidas de arena trazem o selo **Arena parceira**; peladas de grupo têm
destaque magenta, o nome da pelada e o organizador. O filtro "Peladas de grupo"
mostra só elas.

## Portal da arena

O Portal do Gestor (`/manager/`) segue o mesmo visual escuro do app, com menu
lateral no computador e barra inferior no celular.

| Tela | O que faz |
| --- | --- |
| Início | Três números (saldo a receber, vagas vendidas no mês e horários ociosos nos próximos 7 dias) e a agenda do dia por quadra. **Um toque num horário livre publica a partida** com os valores sugeridos (último aluguel da quadra, capacidade, goleiros e nível aberto); o preço por jogador aparece antes. Enquanto ninguém comprou, o horário mostra "Desfazer" |
| Agenda | Grade semanal por quadra. O horário livre abre o formulário completo (aluguel, vagas, goleiros e nível, com prévia do preço); a partida publicada pode ser cancelada com reembolso automático |
| Check-in | Lista de presença dos jogos de hoje e times sugeridos; o QR do comprovante abre a ficha do jogador |
| Financeiro | Liberado, a liberar, transferido e vendido no mês, extrato e transferências |
| Ajustes | Dados da arena, localização, mínimo de jogadores e quadras |

O "saldo a receber" soma o valor liberado e o a liberar: o liberado é
transferido à arena a cada hora pela rotina `gerar_repasses`, então quase nunca
fica parado.

## Stack

| Camada | Tecnologia |
| --- | --- |
| Linguagem | Python 3.15 |
| Framework web | Django 5.2 LTS |
| APIs B2C | Django REST Framework 3.18 (token e sessão) |
| Site, app e portal | Templates Django + Tailwind CSS 4 (compilado pelo executável oficial, sem Node.js), fontes Archivo e Inter |
| Banco de dados | PostgreSQL 18 (driver psycopg 3), configurado por `DATABASE_URL` |
| Rotinas automáticas | APScheduler, num processo próprio (`manage.py agendador`) |
| Configuração | Variáveis de ambiente via `python-dotenv` |
| Produção | gunicorn, WhiteNoise (arquivos estáticos comprimidos e com hash). No ar no Railway (`Dockerfile`); Blueprint do Render (`render.yaml`) como alternativa |

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

**CSS:** o arquivo final (`arena/static/arena/css/arena.css`) está no
repositório, então o projeto roda sem compilar nada. Ao mexer em classes dos
templates, deixe o Tailwind recompilando em outro terminal:

```powershell
python manage.py compilar_css --watch
```

Na primeira vez, o comando baixa o executável oficial do Tailwind (~110 MB) para
o cache do usuário (fora do projeto) e confere o SHA-256 publicado no release.

| Endereço | O que é |
| --- | --- |
| <http://127.0.0.1:8000/> | Site de apresentação |
| <http://127.0.0.1:8000/app/> | App do jogador (B2C) |
| <http://127.0.0.1:8000/manager/> | Portal do Gestor, o ArenaManager (B2B) |
| <http://127.0.0.1:8000/api/> | API REST navegável |
| <http://127.0.0.1:8000/admin/> | Back-office da plataforma (Django Admin) |

> **Windows:** se o PowerShell bloquear o `Activate.ps1`, libere scripts locais
> para o seu usuário com `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### Acessos de demonstração

Criados pelo `populate_db`, que só roda com `DEBUG=True`. As senhas são
fracas de propósito: **não use esses acessos fora do ambiente local**. Num
servidor público (Render), todas as contas usam a senha de `ARENAMATCH_SENHA_DEMO`.

| Perfil | Onde entrar | Login | Senha |
| --- | --- | --- | --- |
| Gestor da Arena Gol de Placa | `/manager/` | `carlos.andrade` | `gestor123` |
| Gestora do Complexo Esportivo Tabelinha | `/manager/` | `fernanda.lima` | `gestor123` |
| Gestor da Arena Pé na Areia | `/manager/` | `rafael.souza` | `gestor123` |
| Jogador de demonstração | `/app/entrar/senha/` | `jogador` | `jogador123` |
| Mesmo jogador, pelo celular | `/app/entrar/` | `(11) 90000-0001` | código exibido na tela |
| Demais jogadores (ex.: `lucas.oliveira`) | `/app/entrar/senha/` | — | `jogador123` |
| Superusuário (portal com todas as arenas, back-office e app) | qualquer um | `admin` | `admin123` |

Sem os dados de demonstração, crie um administrador com `python manage.py createsuperuser`.

### Variáveis de ambiente

| Variável | Obrigatória | Padrão | Descrição |
| --- | --- | --- | --- |
| `DJANGO_SECRET_KEY` | Sim | — | Chave criptográfica do Django. O projeto não sobe sem ela. |
| `DJANGO_DEBUG` | Não | `False` | Ative (`True`) apenas em desenvolvimento. |
| `DJANGO_ALLOWED_HOSTS` | Não | `*` | Hosts aceitos, separados por vírgula. Restrinja ao domínio depois do primeiro deploy. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Não | vazio | Origens extras para formulários (ex.: `https://www.arenamatch.com.br`). O domínio do Render entra sozinho. |
| `DATABASE_URL` | Sim | — | Conexão com o PostgreSQL (`postgres://usuario:senha@host:porta/banco`). O usuário precisa de `CREATEDB` para os testes. |
| `ARENAMATCH_GATEWAY_PAGAMENTO` | Não | `arena.pagamentos.MockGateway` | Classe do gateway de pagamentos. |
| `ARENAMATCH_PERMITIR_GATEWAY_SIMULADO` | Não | igual a `DJANGO_DEBUG` | Libera o gateway simulado (desenvolvimento, testes e CI). |
| `ARENAMATCH_SMS_BACKEND` | Não | `arena.acesso.SmsConsole` | Classe que envia o código de acesso por SMS. A padrão só registra no log; em produção, um provedor real. |
| `ARENAMATCH_URL_BASE` | Não | `RENDER_EXTERNAL_URL` ou `http://127.0.0.1:8000` | Endereço público usado nos links dos e-mails. |
| `ARENAMATCH_POPULAR_DEMO` | Não | `False` | No `build.sh`, popula o banco **vazio** com a demonstração (`populate_db --se-vazio`). |
| `ARENAMATCH_SENHA_DEMO` | Com `DEBUG=False` | — | Senha de todas as contas de demonstração num servidor público (mínimo de 12 caracteres). |
| `ARENAMATCH_AGENDADOR_NO_WEB` | Não | `True` | O `start.sh` sobe o agendador junto do site (plano gratuito do Render). |
| `DJANGO_SECURE_HSTS_SECONDS` | Não | `3600` | Duração do HSTS em produção. |
| `DJANGO_LOG_LEVEL` | Não | `INFO` | Nível do log do Django no console (erros 500 sempre saem com o traceback). |
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

## Deploy no Railway (em produção)

O ArenaMatch está no ar em <https://arenamatch-production.up.railway.app>
(projeto `arenamatch` no Railway: serviço web + PostgreSQL 18).

- O Railway constrói pelo `Dockerfile` (Python 3.14, `collectstatic` no build, usuário sem root).
- Ao subir, o `start.sh` roda `migrate`, cria a demonstração se o banco estiver vazio
  (`ARENAMATCH_POPULAR_DEMO`), sobe o agendador e o gunicorn.
- Publicar uma versão nova: `railway up --service arenamatch` na pasta do projeto.
- Recriar a demonstração (APAGA os dados): `railway ssh --service arenamatch -- python manage.py populate_db --force`.
- As contas de demonstração usam a senha da variável `ARENAMATCH_SENHA_DEMO` do serviço.

## Deploy no Render

O repositório já tem tudo para um deploy sem linha de comando:

| Arquivo | Papel |
| --- | --- |
| `render.yaml` | Blueprint: serviço web e PostgreSQL, ambos no plano gratuito, na região de Virginia, com as variáveis de ambiente (chave secreta e senha da demonstração geradas pelo Render) |
| `build.sh` | Instala as dependências, recompila o CSS, roda `collectstatic`, `migrate` e, se o banco estiver vazio, a demonstração |
| `start.sh` | Sobe o agendador em segundo plano e o gunicorn |
| `.python-version` | Python 3.14 no Render (o Django 5.2 suporta até a 3.14) |

Passo a passo:

1. No [painel do Render](https://dashboard.render.com/), clique em **New > Blueprint**.
2. Conecte a conta do GitHub e escolha o repositório `ArenaMatch` (branch `main`).
3. Confirme a criação. O primeiro build leva alguns minutos (a demonstração é criada nele).
4. A senha das contas de demonstração está em **arenamatch > Environment > `ARENAMATCH_SENHA_DEMO`**.

Limites do plano gratuito: o site "dorme" depois de 15 minutos sem acesso (o
primeiro acesso seguinte leva cerca de 1 minuto), o PostgreSQL gratuito expira
30 dias depois de criado e não há *background worker* (por isso o agendador roda
junto do site). O deploy usa o **gateway simulado**: nenhum dinheiro real se move.

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

Os testes de checkout usam o gateway simulado: rode com `DJANGO_DEBUG=True` (como
no `.env` de desenvolvimento) ou com `ARENAMATCH_PERMITIR_GATEWAY_SIMULADO=True`.

## Estrutura do projeto

```text
.
├── arena/
│   ├── api/                # Serializers, views, permissões e rotas da API REST
│   ├── estilos/            # Fonte do CSS (Tailwind): tema, utilidades e componentes
│   ├── management/         # Comandos populate_db, agendador e compilar_css
│   ├── static/arena/css/   # CSS compilado (versionado; o deploy recompila)
│   ├── migrations/
│   ├── templates/          # App e portal (arena/), site (site/) e customizações do back-office (admin/)
│   ├── templatetags/       # Filtros de apresentação, ícones e indicadores
│   ├── tests/              # Testes de modelos, portal, admin, API, app, site e populate_db
│   ├── acesso.py           # Entrar pelo celular: código de uso único por SMS
│   ├── admin.py            # Back-office da plataforma (Django Admin)
│   ├── agendador.py        # Monta o agendador (APScheduler) com as rotinas registradas
│   ├── checkout.py         # Inscrição: reserva, pagamento, expiração, cancelamento, repasse, lista de espera
│   ├── gestao.py           # Cálculos do portal: números do painel, agenda (semana e dia), financeiro
│   ├── jogadores.py        # Perfil e nível, elegibilidade, check-in, avaliações e times
│   ├── localizacao.py      # Distância até as arenas ("perto de mim")
│   ├── models.py           # Entidades e regras de negócio
│   ├── notificacoes.py     # E-mails aos jogadores (enviados depois do commit)
│   ├── pagamentos.py       # Interface Gateway e o MockGateway de desenvolvimento
│   ├── partidas.py         # Partida: cancelamento com reembolso, mínimo de jogadores, encerramento
│   ├── peladas.py          # Pelada de grupo (C2C): criar, cancelar e o resumo do organizador
│   ├── razao.py            # Razão contábil: carteiras, lançamentos, saldos e repasses
│   ├── rotinas.py          # Rotinas automáticas (@rotina) executadas pelo agendador
│   ├── urls_gestor.py      # Rotas do Portal do Gestor (/manager/)
│   ├── validators.py       # CPF, CNPJ (inclusive alfanumérico) e telefone
│   └── views.py            # Site, app do jogador (B2C) e Portal do Gestor (B2B)
├── config/                 # settings, urls, wsgi/asgi
├── .env.example            # Modelo de variáveis de ambiente (o .env real não é versionado)
├── Dockerfile              # Imagem de produção (Railway)
├── build.sh                # Build de produção (Render)
├── manage.py
├── render.yaml             # Blueprint do Render (web + PostgreSQL)
├── requirements.txt
└── start.sh                # Início em produção: agendador + gunicorn
```

## Roadmap

Implementado: portal B2B, pagamento in-app com razão contábil, perfis e níveis,
check-in, avaliações, site, app do jogador, login pelo celular, CSS compilado e
deploy no Render. Próximos passos:

1. **Pagamentos:** trocar o `MockGateway` por um gateway real com split (Mercado Pago, Pagar.me ou Asaas).
2. **SMS e login social:** provedor real de SMS para o código de acesso e entrar com Google (precisa de credenciais OAuth).
3. **Agenda recorrente:** gerar horários de mensalistas e ociosos em lote.
4. **Notificações:** WhatsApp, além do e-mail, na inscrição e no cancelamento de partidas.
5. **Produção de verdade:** domínio próprio, `DJANGO_ALLOWED_HOSTS` restrito, banco pago (o gratuito expira) e o agendador num worker.

## Convenções

- Commits seguem o padrão [Conventional Commits](https://www.conventionalcommits.org/pt-br/)
  (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`).
- Código em conformidade com a PEP 8, com type hints e docstrings.
- Site, app do jogador e portal no mesmo tema escuro: fundo `zinc-950`, destaques
  neon `lime-400` (ação e dinheiro) e `cyan-400` (informação), superfícies de vidro
  (`vidro`) e títulos em Archivo extra-negrito (`titulo`).
- Utilidades e componentes (`botao-neon`, `botao-vidro`, `campo`, `selo`) ficam em
  `arena/estilos/entrada.css`. Crie um componente só quando o padrão se repetir em
  várias telas; o resto fica em classes utilitárias nos templates.
- Regras de negócio ficam nos modelos (`clean()`), e `save()` sempre valida.
- Segredos (`.env`) **nunca** são versionados.
