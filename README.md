# ArenaMatch

**SaaS B2B2C para gestão de complexos esportivos e matchmaking de jogadores avulsos.**

O ArenaMatch conecta duas pontas do futebol amador. Os donos de quadras têm um
software de gestão para a operação do dia a dia. Os jogadores sem time fixo
encontram partidas abertas para completar.

---

## Modelo de negócio

| Frente | Público | O que entrega |
| --- | --- | --- |
| **B2B** | Gestores de complexos esportivos | Painel de gestão com agenda de quadras, reservas avulsas, mensalistas e bloqueios. Com um clique, transforma **horários ociosos** em **partidas abertas** para a comunidade. |
| **B2C** | Jogadores avulsos | Vitrine (app mobile/web) para encontrar partidas abertas por nível e preço e comprar vagas individuais. |

As duas frentes compartilham o mesmo banco de dados. A receita da arena cresce
porque horários que ficariam vazios são vendidos vaga a vaga.

No MVP, o painel B2B é o **Django Admin customizado**. A frente B2C consome
**APIs REST**. O pagamento é registrado manualmente (status de pagamento), e a
integração com um gateway fica para uma etapa futura.

## Stack

| Camada | Tecnologia |
| --- | --- |
| Linguagem | Python 3.15 |
| Framework web | Django 5.2 LTS |
| APIs B2C | Django REST Framework (Fase 3) |
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

# 5. Crie o banco de dados e um usuário administrador
python manage.py migrate
python manage.py createsuperuser

# 6. Suba o servidor de desenvolvimento
python manage.py runserver
```

Depois, acesse o painel em <http://127.0.0.1:8000/admin/>.

> **Windows:** se o PowerShell bloquear o `Activate.ps1`, libere scripts locais
> para o seu usuário com `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### Variáveis de ambiente

| Variável | Obrigatória | Padrão | Descrição |
| --- | --- | --- | --- |
| `DJANGO_SECRET_KEY` | Sim | — | Chave criptográfica do Django. O projeto não sobe sem ela. |
| `DJANGO_DEBUG` | Não | `False` | Ative (`True`) apenas em desenvolvimento. |
| `DJANGO_ALLOWED_HOSTS` | Não | vazio | Hosts aceitos, separados por vírgula. |

## Estrutura do projeto

```text
.
├── arena/              # App de domínio: arenas, quadras, horários, partidas e inscrições
├── config/             # Configuração do projeto Django (settings, urls, wsgi/asgi)
├── .env.example        # Modelo de variáveis de ambiente (o .env real não é versionado)
├── manage.py
└── requirements.txt
```

## Roadmap do MVP

1. **Configuração base e modelagem:** usuário customizado, entidades do
   domínio e regras de negócio.
2. **Painel de gestão B2B:** Django Admin customizado, com inlines e uma action
   que converte horários ociosos em partidas abertas.
3. **APIs B2C:** serializers e views do DRF para listar partidas abertas e
   registrar inscrições.

## Convenções

- Commits seguem o padrão [Conventional Commits](https://www.conventionalcommits.org/pt-br/)
  (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`).
- Código em conformidade com a PEP 8, com type hints e docstrings.
- Segredos (`.env`) e o banco local (`db.sqlite3`) **nunca** são versionados.
