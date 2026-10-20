# Pivô de UX, app Flutter e toolkit · relatório

**Data:** 20/10/2026 · **Commit:** "refactor: design pivot ultra-minimalista, setup flutter e expansao de toolkit"

Resumo em quatro linhas:

1. **Toolkit (Fase 1):** nenhum MCP foi instalado. Todos precisam de segredo (token do GitHub, senha do banco) ou do Node.js, que a máquina não tem. Os comandos exatos estão na seção 1.
2. **Design (Fase 2):** o dark/neon saiu. Site, app do jogador e portal da arena agora são claros, com uma cor forte só nos botões de ação: o verde bandeira `#00873A`.
3. **Flutter (Fase 3):** o app está em `mobile_app/`, com três abas (Jogos, Minhas Peladas e Perfil). A API ganhou o que faltava para alimentá-lo: login pelo celular, pelada de grupo, carteira, chave Pix e saque.
4. **Produção:** continua com a versão anterior. Este pacote só vai ao ar com um novo `railway up`, que não foi feito.

---

## 1. Fase 1 · MCPs e toolkit

### O que foi decidido

| Ferramenta | Situação | Por quê |
| --- | --- | --- |
| **GitHub** | Não instalado | O MCP oficial precisa de um token pessoal, e esse token fica gravado em texto puro na configuração do Claude Code. O `gh` (GitHub CLI) já está instalado e autenticado e faz o mesmo papel. |
| **PostgreSQL** | Não instalado | O servidor recomendado (DBHub) roda com `npx`, e a máquina não tem Node.js. O MCP também deve usar um usuário **só de leitura** do banco, que precisa ser criado com senha. O **Postgres MCP Pro** (crystaldba) foi descartado: ele tem a CVE-2026-85620, uma falha que permite escrever no banco mesmo no "modo restrito". |
| **Web Fetch / Search** | Já existe | O Claude Code já tem `WebFetch` e `WebSearch` nativos. Instalar um MCP para isso duplicaria a ferramenta. |
| **Railway** | Opcional | A CLI do Railway instala o próprio MCP com `railway setup agent`. |

Um MCP novo só aparece depois que o Claude Code é reiniciado. Para conferir, use `claude mcp list` no terminal ou `/mcp` dentro da sessão.

### Comandos exatos (rodar no terminal, fora do Claude Code)

**GitHub** (escopo do usuário; usa o token do `gh` que já está logado):

```powershell
claude mcp add --scope user --transport http github https://api.githubcopilot.com/mcp/ --header "Authorization: Bearer $(gh auth token)"
```

> O token vai para `~/.claude.json`. Prefira um *fine-grained token* só com leitura do repositório `ArenaMatch`, criado em github.com → Settings → Developer settings, e cole-o no lugar de `$(gh auth token)`.

**PostgreSQL** (DBHub, só leitura):

```powershell
# 1. Node.js (traz o npx)
winget install OpenJS.NodeJS.LTS

# 2. Usuário só de leitura no banco local (troque a senha)
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -d arenamatch -c "CREATE ROLE arenamatch_leitura LOGIN PASSWORD 'troque-esta-senha'; GRANT CONNECT ON DATABASE arenamatch TO arenamatch_leitura; GRANT USAGE ON SCHEMA public TO arenamatch_leitura; GRANT SELECT ON ALL TABLES IN SCHEMA public TO arenamatch_leitura; ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO arenamatch_leitura;"

# 3. O MCP (escopo local: só neste projeto, fora do Git)
claude mcp add --scope local --transport stdio db -- npx -y @bytebase/dbhub --dsn "postgresql://arenamatch_leitura:troque-esta-senha@localhost:5432/arenamatch"
```

> Nunca aponte o MCP para o banco de produção com o usuário dono das tabelas. Para produção, crie no Railway um usuário só de leitura do mesmo jeito.

**Railway:**

```powershell
& "$env:LOCALAPPDATA\arenamatch\railway-v5.63.4\railway.exe" setup agent
```

Fontes: documentação de MCP do Claude Code (<https://code.claude.com/docs/en/mcp>), CVE-2026-85620 (<https://osv.dev/vulnerability/CVE-2026-85620>) e o comparativo de servidores MCP para Postgres (<https://dev.to/bytebase/top-3-open-source-postgres-mcp-servers-in-2026-43g4>).

---

## 2. Fase 2 · Design ultra-minimalista

### Design system

| Token | Antes (dark/neon) | Agora |
| --- | --- | --- |
| Fundo | `zinc-950` com brilhos | `gray-50` (`bg-white` no topo e nos cartões) |
| Texto | `zinc-100` | `gray-900`, e `gray-500` no secundário |
| Ação | `lime-400` com sombra neon | **Verde bandeira** `#00873A` (`bandeira-600`; contraste AA com texto branco). É a única cor forte da tela |
| Informação | `cyan-400` | Cinza. Cor só nos selos de status (verde, âmbar, azul) |
| Superfícies | Vidro (`vidro`) | Cartão branco com borda `gray-200` (`cartao`) |
| Fonte | Archivo + Inter | Só Inter. Títulos em peso 800 com tracking negativo (`titulo`) |
| Botão principal | `botao-neon` | `botao`: `py-4 px-6 text-lg font-bold rounded-2xl` |
| Botão secundário | `botao-vidro` | `botao-secundario`: contorno `gray-300`, mesmo tamanho |
| Seleção | Verde-limão | `gray-900` (chips `chip-ativo`, opções `opcao`) |

Componentes em `arena/estilos/entrada.css`: `botao`, `botao-secundario`, `cartao`, `campo`, `campo-erro`, `selo`, `opcao`, `chip` e `chip-ativo`. Os filtros de template escuros (`estilizar_escuro`, `nivel_escuro`, `inscricao_escuro`) deram lugar a `estilizar`, `classes_nivel` e `classes_status`.

### Regra de carga cognitiva

Cada tela tem **uma ação principal** em verde. O resto fica em contorno ou recolhido num `<details>`.

| Tela | À vista | Recolhido |
| --- | --- | --- |
| **Feed B2C** (`/app/`) | Cartões estilo Uber: origem, **hora e preço grandes**, nome, local, vagas e **"Garantir vaga" na largura toda** no celular. Chips de dia e "Perto de mim" | "Mais filtros" (nível, origem e piso) |
| Partida | Preço "por pessoa no Pix" e a ação | "Quem vai" e "Regras" |
| Checkout | Posição e forma de pagamento | "Ver detalhes do valor" |
| **C2C** (`/app/organizar/nova/`) | **Passo único:** quadra, dia, horário, vagas (−/+), valor por vaga, prévia "Cada jogador paga" e **Confirmar** | "Mais opções": nome (padrão "Pelada do Fulano"), término (padrão: 1h depois), nível e goleiro de aluguel |
| Organizar | "Completar uma pelada", saldo e "Sacar via Pix" | Chave Pix, peladas já jogadas e saques |
| **B2B Início** (`/manager/`) | **Só os números do dinheiro** (saldo a receber e vendido no mês) e o **botão gigante "Abrir quadra"** | Nenhum outro elemento na tela |
| **B2B Abrir quadra** (`/manager/abrir-quadra/`, nova) | Abas de dia e os horários livres de cada quadra: um toque publica a partida | — |
| Agenda | Grade semanal; o horário livre abre "Abrir para o app" com o aluguel e o preço por jogador | "Mais opções" (vagas, goleiros e nível) e a legenda |
| Financeiro | Liberado e a liberar | Mês atual e transferências |
| Ajustes | Quadras e dados da arena | Localização, mínimo de jogadores e contrato |

A publicação em um toque saiu do Início e foi para a página **Abrir quadra** (`GestorAbrirQuadraView`). O Início ficou só com o dinheiro e o botão, como foi pedido.

### Verificação

- CSS recompilado (`manage.py compilar_css`, 35 KB).
- Capturas em 390 px e 1280 px das telas do jogador, do organizador, do portal e do site, sem rolagem horizontal. A home pública tinha 42 px de rolagem no celular, por causa do cartão do jogo dentro da grade, e já foi corrigida (`min-w-0`).
- Testes ajustados ao novo layout:
  - o Início verifica "Saldo a receber" e "Abrir quadra";
  - a publicação em um toque é testada na página nova;
  - foram trocadas as classes da agenda e os componentes do CSS.

---

## 3. Fase 3 · App Flutter e API

### API (Django) para o app

Rotas novas em `/api/`, testadas em `arena/tests/test_api_app.py` (9 testes):

| Método | Rota | Uso no app |
| --- | --- | --- |
| POST | `auth/celular/` | Login, passo 1: envia o código por SMS (em `DEBUG`, devolve o código para facilitar o teste) |
| POST | `auth/celular/verificar/` | Passo 2: código → token; cria o jogador no primeiro acesso e devolve `precisa_de_perfil` |
| GET, POST | `peladas/` | Minhas peladas (vendidas, `arrecadado`, `pode_cancelar`) e publicar vagas com só 5 campos |
| POST | `peladas/{id}/cancelar/` | Cancelar vagas com reembolso |
| GET | `organizador/carteira/` | Disponível, a liberar, sacado, mínimo de saque, chave Pix, saques e movimentações |
| PUT | `organizador/chave-pix/` | Cadastrar a chave Pix (reaproveita o `ChavePixForm` do site, com a mesma validação) |
| POST | `organizador/saques/` | Sacar todo o disponível |
| GET | `partidas/?origem=pelada` | Filtro novo por origem |

Os padrões da pelada (término 1h depois e título "Pelada do Fulano") passaram para `peladas.termino_padrao` e `peladas.titulo_padrao`, usados tanto pelo site quanto pela API.

### Arquitetura do `mobile_app/`

```
lib/
  main.dart                  abre a sessão salva e sobe o app
  app.dart                   MaterialApp (tema claro, pt-BR) + BottomNavigationBar com 3 abas
  tema.dart                  design system: mesmas cores do site, botões de 56 px, cartões e campos
  config.dart                API_URL via --dart-define (padrão: produção no Railway)
  formato.dart               R$ 1.234,50, "Hoje"/"Amanhã", prévia do preço da pelada
  api/cliente_api.dart       HTTP (pacote http), token no cabeçalho, ApiErro com as mensagens do DRF
  api/arenamatch_api.dart    um método por endpoint (feed, checkout, login, perfil, peladas, carteira, saque)
  api/sessao.dart            token salvo no aparelho (shared_preferences) + InheritedNotifier
  modelos/                   Partida, PeladaDoOrganizador, Inscricao, CarteiraOrganizador, Usuario, Quadra
  telas/                     jogos, garantir vaga, entrar, questionário, minhas peladas, nova pelada, perfil
  widgets/                   cartão de partida e peças comuns
test/                        14 testes: modelos, cliente HTTP (MockClient), formatação e telas
```

| Aba | Fluxo |
| --- | --- |
| **Jogos** | Feed por dia com filtros (Todos, Hoje, Amanhã e Peladas de grupo). "Garantir vaga" pede login (se preciso) e o questionário (no primeiro acesso), gera o Pix e mostra o código copia e cola |
| **Minhas Peladas** | "Completar uma pelada" em passo único, saldo, cadastro da chave Pix, saque e cancelamento de vagas |
| **Perfil** | Nível (ou o questionário), próximos jogos e "Sair" |

Decisões:

- **Sem gerenciador de estado externo:** `InheritedNotifier` + `FutureBuilder` dão conta das três abas.
- **Duas dependências só:** `http` e `shared_preferences` (mais `flutter_localizations`, que vem do SDK, para o calendário em português).
- **Mesmos nomes do backend:** os modelos e campos seguem os nomes em português da API.

### Verificação

- `flutter analyze`: sem avisos.
- `flutter test`: 14 testes passando.
- Django: 203 testes passando, `ruff` sem erros e `manage.py check` sem avisos.
- **Não verificado:** o app não rodou num aparelho nem num emulador. A máquina não tem o Android SDK, e o iOS exige um Mac. O próximo passo é instalar o Android Studio e rodar `flutter run`.

---

## 4. O que ficou para você decidir ou fazer

1. **Publicar na nuvem:** rode `railway up` (ou peça para eu rodar). Até lá, a produção segue com o tema escuro e sem as rotas novas da API, e o app, que aponta para a produção por padrão, vai receber 404 nelas.
2. **Dados de produção:** o comando `populate_db --force` no Railway ainda precisa ser rodado por você (ficou bloqueado na sessão anterior).
3. **Android:** instale o Android Studio e rode `flutter doctor`. Depois, `flutter run --dart-define=API_URL=http://10.0.2.2:8000/api/` contra o Django local, com `10.0.2.2` em `DJANGO_ALLOWED_HOSTS`.
4. **MCPs:** se quiser, use os comandos da seção 1. O de banco deve usar sempre o usuário só de leitura.
5. **App no navegador:** só funciona contra a API com CORS liberado (pacote `django-cors-headers`), que não foi adicionado. No celular, CORS não se aplica.
