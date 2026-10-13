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
fica como back-office interno da equipe da plataforma. O pagamento é registrado
manualmente (o gestor confirma no Financeiro), e a integração com um gateway fica
para uma etapa futura.

## Stack

| Camada | Tecnologia |
| --- | --- |
| Linguagem | Python 3.15 |
| Framework web | Django 5.2 LTS |
| APIs B2C | Django REST Framework 3.18 (token e sessão) |
| Vitrine web | Templates Django + Tailwind CSS 4 (via CDN) |
| Banco de dados | SQLite (MVP) |
| Configuração | Variáveis de ambiente via `python-dotenv` |

## Como rodar localmente

**Pré-requisitos:** Python 3.15 e Git.

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

# 5. Crie o banco e carregue os dados de demonstração
python manage.py migrate
python manage.py populate_db       # opcional: APAGA tudo e recria os dados de teste

# 6. Suba o servidor de desenvolvimento
python manage.py runserver
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

## API REST

Autenticação por token (`Authorization: Token <chave>`) ou sessão. Listas são
paginadas (`?page=`), com 20 itens por página.

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/api/partidas/` | Partidas abertas que ainda não começaram. Filtros: `nivel`, `piso`, `arena` (slug), `data`, `de`, `ate` |
| GET | `/api/partidas/{id}/` | Detalhes, com os jogadores inscritos |
| POST | `/api/partidas/{id}/inscricoes/` | Inscreve o jogador autenticado |
| GET | `/api/minhas-inscricoes/` | Inscrições do jogador autenticado |
| GET, DELETE | `/api/minhas-inscricoes/{id}/` | Detalha ou cancela (só se o pagamento estiver pendente) |
| GET | `/api/arenas/` | Arenas e quadras |
| POST | `/api/auth/cadastro/` | Cria uma conta de jogador e devolve o token |
| POST | `/api/auth/token/` | Troca usuário e senha por um token |
| GET | `/api/me/` | Perfil do usuário autenticado |

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
│   ├── management/         # Comando populate_db (dados de demonstração)
│   ├── migrations/
│   ├── templates/          # Vitrine e portal (arena/) e customizações do back-office (admin/)
│   ├── templatetags/       # Filtros de apresentação, ícones e indicadores
│   ├── tests/              # Testes de modelos, portal, admin, API, vitrine e populate_db
│   ├── admin.py            # Back-office da plataforma (Django Admin)
│   ├── gestao.py           # Cálculos do portal: KPIs, grade da agenda, financeiro
│   ├── models.py           # Entidades e regras de negócio
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

1. **Pagamentos:** integração com gateway (Pix) e confirmação automática.
2. **Agenda recorrente:** gerar horários de mensalistas e ociosos em lote.
3. **Notificações:** e-mail e WhatsApp na inscrição e no cancelamento de partidas.
4. **Produção:** PostgreSQL, build do Tailwind (sem CDN), arquivos estáticos e deploy.

## Convenções

- Commits seguem o padrão [Conventional Commits](https://www.conventionalcommits.org/pt-br/)
  (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`).
- Código em conformidade com a PEP 8, com type hints e docstrings.
- Interface "Clean SaaS" com Tailwind: fundo `slate-50`, cartões brancos com borda
  sutil e `shadow-sm`, destaque `emerald-600` e texto `slate-800`/`slate-900`, sem gradientes.
- Regras de negócio ficam nos modelos (`clean()`), e `save()` sempre valida.
- Segredos (`.env`) e o banco local (`db.sqlite3`) **nunca** são versionados.
