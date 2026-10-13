# Changelog noturno · ArenaMatch

**Data:** 13/10/2026 · **Modo:** operação autônoma (Night Shift)

> **Atualização posterior:** a interface B2B passou a ser o **Portal do Gestor
> (ArenaManager)**, em `/manager/`, e a vitrine ganhou a identidade "Clean SaaS".
> O Django Admin virou back-office interno. Os acessos e endereços atuais estão no README.

## Resumo

O MVP está pronto e com dados:

- **Painel do gestor (B2B):** Django Admin customizado, com indicadores, agenda, partidas e inscrições.
- **Vitrine dos jogadores (B2C):** feita com Tailwind, do feed de partidas até o comprovante da reserva.
- **API REST** completa para o app mobile.
- **Banco populado** com 3 arenas, 8 quadras, 327 horários, 18 partidas abertas (3 lotadas), 120 inscrições e 25 usuários.
- **Testes:** 68 testes automatizados passando.
- **Validação:** fluxo ponta a ponta no servidor real e revisão visual em desktop e mobile.

---

## Como começar ao acordar

1. Abra o terminal do VS Code na pasta do projeto (`` Ctrl+` ``).
2. Suba o servidor:

   ```powershell
   .\venv\Scripts\python.exe manage.py runserver
   ```

   Se aparecer "porta já em uso", o servidor que deixei rodando ainda está no ar. É só abrir os endereços abaixo.

3. Acesse:

   | Endereço | O que é |
   | --- | --- |
   | <http://127.0.0.1:8000/> | Vitrine para os jogadores |
   | <http://127.0.0.1:8000/admin/> | Painel do gestor |
   | <http://127.0.0.1:8000/api/> | API REST navegável |

4. Use os acessos de demonstração:

   | Perfil | Login | Senha |
   | --- | --- | --- |
   | Superusuário (também é jogador) | `admin` | `admin123` |
   | Gestor da Arena Gol de Placa | `carlos.andrade` | `gestor123` |
   | Gestora do Complexo Esportivo Tabelinha | `fernanda.lima` | `gestor123` |
   | Gestor da Arena Pé na Areia | `rafael.souza` | `gestor123` |
   | Jogador de demonstração | `jogador` | `jogador123` |
   | Demais jogadores (ex.: `lucas.oliveira`) | — | `jogador123` |

> A senha do `admin` agora é **`admin123`**. A senha aleatória criada antes foi
> substituída quando o `populate_db` recriou os usuários.

**Roteiro sugerido para conhecer o sistema (10 minutos):**

1. **Vitrine sem login:** veja o feed agrupado por dia, use os filtros e abra uma partida.
2. **Reserva:** clique em "Reservar minha vaga", entre como `jogador` / `jogador123`, confirme a reserva e veja o comprovante. Ele tem botões de Google Agenda e de rota no Maps. Depois abra "Minhas inscrições".
3. **Painel como `admin`:** veja os indicadores da página inicial. Em **Horários**, filtre por "Ocioso" e "De hoje em diante", selecione alguns horários e rode a action **"Converter em partida aberta"**. Uma tela intermediária pede preço e nível. As partidas criadas aparecem na vitrine na hora.
4. **Painel como `carlos.andrade`:** repare que um gestor só enxerga a própria arena.

**Outros comandos úteis:**

```powershell
.\venv\Scripts\python.exe manage.py populate_db   # APAGA tudo e recria os dados de demonstração
.\venv\Scripts\python.exe manage.py test arena    # roda os 68 testes
```

---

## O que foi construído

### 1. Backend: modelos e regras de negócio

A modelagem da Fase 1 foi mantida e ganhou:

- **Consultas reutilizáveis:** `OpenMatchQuerySet`, com `vitrine()`, `futuras()`, `filtrar()` e `com_relacionados()`. A vitrine, a API e o painel usam a mesma lógica, sem consultas N+1.
- **Propriedades de exibição:**
  - `vagas_ocupadas`, `percentual_ocupado` e `aceita_inscricoes` (partida).
  - `intervalo` e `fim` (horário).
  - `nome_publico` e `iniciais` (usuário).
- **Cancelamento:** `Booking.cancelar()` e `pode_cancelar`. Só inscrições pendentes, antes do início da partida, podem ser canceladas. A vaga volta automaticamente.
- **Link da partida:** `OpenMatch.get_absolute_url()`. O botão "Ver no site" do admin leva direto à página pública.

### 2. Painel do gestor (Django Admin)

- **Página inicial com indicadores dos próximos 7 dias:**
  - Partidas de hoje.
  - Ocupação, com barra de progresso.
  - Receita confirmada e valor a receber.
  - Horários ociosos, com atalho para converter em partidas.
  - Tabela das próximas partidas.
- **Arenas:** CNPJ formatado, horário de funcionamento, total de quadras e quadras editáveis na própria página (inline). O slug é preenchido automaticamente.
- **Horários (agenda):** filtro por período (hoje, amanhã, próximos 7 dias, futuros, passados), status, tipo, arena e quadra; navegação por data; selos coloridos de status; link para a partida vinculada. Actions:
  - **`converter_para_partida_aberta`:** abre uma tela intermediária que separa os horários elegíveis dos ignorados (com o motivo de cada um) e pede preço, nível e vagas. Se as vagas ficarem em branco, vale a capacidade da quadra.
  - **Marcar como ocioso:** libera horários para virarem partidas.
- **Partidas abertas:** barra de ocupação e preço em R$. As inscrições aparecem em linha, e o gestor pode registrar ali o jogador que chegou no balcão. Actions de finalizar e cancelar; o cancelamento avisa quando há inscrições pagas a reembolsar. Na criação de uma partida, só aparecem horários livres e futuros.
- **Inscrições:** actions "Marcar como pago" e "Marcar como reembolsado". A reembolsada libera a vaga. Partida e jogador ficam somente leitura depois de criados.
- **Usuários:** campos do ArenaMatch (gestor, jogador, telefone e CPF formatado) e busca por CPF.
- **Isolamento entre arenas (multi-tenant):** um gestor (`is_manager`, sem superusuário) só vê e edita os dados das próprias arenas, inclusive nas listas de opções dos formulários. Não pode trocar o responsável pela arena e não acessa a lista de usuários. As permissões ficam no grupo **Gestores**.

### 3. APIs REST (Django REST Framework)

As rotas estão documentadas no README:

- Feed com filtros.
- Detalhes da partida com os jogadores.
- Inscrição, consulta e cancelamento.
- Minhas inscrições.
- Arenas.
- Cadastro com token, login por token e perfil.

Detalhes de implementação:

- **Autenticação:** token para o app mobile e sessão para a web. Um cliente anônimo recebe **401** com o cabeçalho `WWW-Authenticate`.
- **Erros de regra de negócio:** um *exception handler* converte as validações do modelo em **HTTP 400** com mensagens legíveis. Exemplo: `{"non_field_errors": ["Esta partida está lotada."]}`.
- **Permissões:** só contas de jogador se inscrevem (`IsJogador`). Cada jogador só vê e cancela as próprias inscrições.

### 4. Vitrine web (Tailwind CSS)

Todas as páginas são responsivas e foram validadas em desktop (1440px) e celular (390px):

- **Feed (`/`):**
  - Hero com as linhas de um campo de futebol e contadores de partidas, vagas e arenas.
  - Barra de filtros por dia, nível, piso e arena.
  - Cards agrupados por dia ("Hoje", "Amanhã", dias da semana). Cada card tem cor por tipo de piso, horário, arena, nível, barra de vagas, preço e selos "Lotada" e "Últimas vagas".
  - Seções "Como funciona" e um convite para donos de arena.
- **Partida (`/partidas/<id>/`):** jogadores confirmados (avatar com iniciais e nome público, como "Lucas O.") e vagas livres; detalhes da partida; local com Google Maps e WhatsApp da arena. Um card fixo com preço, ocupação e botão de reserva se adapta ao estado: sem login, já inscrito, lotada ou encerrada.
- **Confirmação (`/partidas/<id>/reservar/`):** resumo e política de pagamento antes de confirmar.
- **Comprovante (`/inscricoes/<id>/`):** visual de ingresso com código da reserva, status do pagamento, "Adicionar à agenda" (Google Agenda), "Como chegar" e cancelamento.
- **Minhas inscrições:** próximas partidas e histórico.
- **Conta:** login e cadastro de jogador. Quem se cadastra já entra logado. O parâmetro `next` só aceita endereços internos, o que evita redirecionamento para sites externos.

### 5. Dados de demonstração (`populate_db`)

O management command fica em `arena/management/commands/populate_db.py`. Fiz como comando, e não com `manage.py shell < populate_db.py`, porque o PowerShell não aceita o redirecionamento `<`. Ele cria:

- **Contas:** superusuário, 3 gestores (no grupo Gestores, com permissões) e 21 jogadores com CPF válido.
- **Arenas:** Arena Gol de Placa (São Paulo), Complexo Esportivo Tabelinha (Belo Horizonte) e Arena Pé na Areia (Rio de Janeiro). Esta última usa o novo **CNPJ alfanumérico**.
- **Quadras:** 8, de sintético, salão, areia e campo.
- **Agenda:** 7 dias, com mensalistas, avulsos, bloqueios e cancelamentos, além do horário de 23h às 00h.
- **Partidas e inscrições:** 18 partidas abertas com níveis e preços variados, 3 delas lotadas. As inscrições misturam pagas, pendentes e reembolsadas. O jogador de demonstração já começa com 2 partidas marcadas.

Todo registro passa pelo `save()` dos modelos, ou seja, pelas mesmas regras de negócio do sistema. Os dados são reproduzíveis (`--seed`). O comando **só roda com `DEBUG=True`** (ou `--force`), porque apaga tudo e cria senhas fracas.

### 6. Testes automatizados

São 68 testes em `arena/tests/`, que rodam em cerca de 6 segundos:

- **Modelos e validadores:** CPF e CNPJ (inclusive alfanumérico), agenda (conflitos, meia-noite), vagas e lotação, reembolso, cancelamento, histórico preservado, formulários no estilo do admin.
- **Admin:** todas as páginas carregam, o painel inicial, a action de conversão (tela intermediária e criação), as actions de pagamento e o isolamento entre gestores.
- **API:** filtros, permissões (401, 403), inscrição, regras de negócio retornando 400, cancelamento, cadastro com token.
- **Vitrine:** feed, detalhe, login obrigatório, confirmação, partida lotada, comprovante de outro jogador (404), cancelamento, cadastro e proteção contra redirecionamento externo.
- **`populate_db`:** volume e qualidade dos dados, possibilidade de rodar de novo e bloqueio sem `DEBUG`.

---

## Decisões de arquitetura

1. **Regras de negócio no modelo.** Ficam em `clean()`, e `save()` sempre valida dentro de uma transação. O admin, a API, a vitrine e o `populate_db` usam as mesmas regras, sem duplicação.
2. **Uma única fonte para as consultas.** O `OpenMatchQuerySet` define o que é "partida da vitrine" para a web, a API e o painel.
3. **Isolamento por arena no admin.** Uma classe base (`EscopoGestorAdmin`) aplica o filtro do gestor nas listas e nas opções dos formulários.
4. **Tailwind via CDN, com versão fixa (4.3.3).** É ideal para o MVP. Para produção, o recomendado é gerar o CSS num build.
5. **Comando de demonstração com trava de segurança.** Ele se recusa a rodar fora do modo de desenvolvimento.

---

## Problemas encontrados e resolvidos

| Problema | Causa | Solução |
| --- | --- | --- |
| `/cadastro/` retornava erro 500 | No template, um argumento de filtro (`request.POST.next`) não existia em requisições GET | O valor de `next` passou a vir da view |
| No detalhe da partida, o card "Quem já confirmou" ficava escondido atrás do hero | Empilhamento: o hero tem posicionamento e era pintado por cima do grid, que sobe com margem negativa | O grid passou a ter `relative z-10` |
| A agenda do admin cortava as colunas de status e partida | Coluna "Quadra" repetia o nome da arena, e a data por extenso alargava a tabela | Coluna só com o nome da quadra e data curta ("Qua, 14/10/2026") |
| Meses com inicial maiúscula ("13 de Outubro") | Formato padrão do Django em pt-BR | Filtro `lower` nas datas por extenso |
| "R$" quebrava de linha separado do valor | Espaço comum | Espaço não separável na formatação de moeda |
| API devolvia 403 em vez de 401 para anônimos | O DRF usa a primeira classe de autenticação para montar a resposta | Token passou a vir antes da sessão |
| Capturas de tela do mobile pareciam cortadas | O Chrome headless impõe largura mínima de janela (falso alarme) | Validei com viewport real de 390px dentro de um iframe: o layout está correto |
| Limpeza do `populate_db` recalculava as vagas inscrição por inscrição | O sinal `post_delete` dispara para cada exclusão | O sinal é desligado durante a limpeza e religado em seguida; há um teste que garante a religação |

---

## Verificação feita

- `manage.py check` e `makemigrations --check` sem pendências.
- 68 testes automatizados passando.
- Fluxo ponta a ponta no servidor real: login do jogador, confirmação, reserva com comprovante, cancelamento e login do admin no painel.
- Revisão visual com mais de 20 capturas de tela (vitrine, partida, reserva, comprovante, inscrições, login, cadastro e painel), em desktop e mobile.

## Commits da noite

```text
3c70ae4 feat(arena): modelagem de dados e regras de negócio
cd08b5d feat(admin): painel do gestor B2B com escopo por arena
a3aaa37 feat(api): APIs REST B2C com Django REST Framework
95eb334 feat(web): vitrine B2C com Tailwind CSS
16342ff feat(seed): comando populate_db com dados de demonstração
34823f9 test: suíte de testes de modelos, admin, API, vitrine e populate_db
        docs: README atualizado e changelog noturno
```

---

## Pontos de atenção

- **Senhas de demonstração** (`admin123`, `gestor123`, `jogador123`): use só localmente. Antes de qualquer deploy, troque-as e não rode o `populate_db`.
- **Dados fictícios:** endereços, CNPJs e CPFs são inventados (válidos apenas pelo cálculo). Os telefones das arenas são marcadores (`3000-0101`...), então o botão de WhatsApp abre conversas para números fictícios.
- **Valor da inscrição:** hoje a inscrição usa o preço atual da partida. Se o gestor mudar o preço, as inscrições antigas passam a mostrar o valor novo. O ideal é gravar o valor pago na própria inscrição. Recomendo fazer isso junto com a integração de pagamento.
- **Python 3.15 e Django 5.2:** o Django 5.2 declara suporte oficial até o Python 3.14. Tudo funcionou nos testes, mas, se surgir algo estranho, essa é a primeira suspeita.
- **OneDrive:** o projeto está numa pasta sincronizada. Se aparecerem erros de arquivo travado no `db.sqlite3` ou no `.git`, mova a pasta para fora do OneDrive (ex.: `C:\dev`).

## Próximos passos sugeridos

1. Pagamento via Pix com confirmação automática, gravando o valor pago na inscrição.
2. Geração de agenda em lote (mensalistas recorrentes e horários ociosos a partir do horário de funcionamento).
3. Notificações por e-mail e WhatsApp (inscrição confirmada, partida cancelada).
4. Preparação para produção: PostgreSQL, build do Tailwind, `collectstatic`, `DEBUG=False` e deploy.
