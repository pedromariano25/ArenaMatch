# Relatório da madrugada · ArenaMatch

**Data:** madrugada de 16/10/2026 · **Modo:** operação autônoma (Night Shift)

## Resumo

O roteiro desta noite repetia as Fases −1 a 3, que **já tinham sido feitas na
madrugada de 14/10** (relatório arquivado em
[`docs/RELATORIO_2026-10-14.md`](docs/RELATORIO_2026-10-14.md)): PostgreSQL,
agendador, checkout in-app com reserva de 10 minutos, MockGateway, níveis,
goleiro, site em `/` e app em `/app/`. Não refiz o que já estava pronto e testado.
Conferi e trabalhei no que era novo:

- **Portal da arena (`/manager/`) no visual escuro e neon do app.** O Início foi
  simplificado: 3 cards grandes e a agenda do dia, em que **um toque num horário
  livre publica a partida**. Os termos técnicos sumiram ("razão", "estorno",
  "repasse", "em pagamento").
- **Tailwind fora do CDN.** O CSS agora é compilado (58 KB, ou 10 KB comprimido),
  e os botões repetidos viraram componentes.
- **Fase 4 · Deploy no Render:** `render.yaml`, `build.sh`, `start.sh`, gunicorn,
  WhiteNoise e configurações de segurança. O deploy foi simulado do zero aqui:
  banco vazio, build e população automática.
- **Dados de demonstração:** 3 arenas, 8 quadras, 60 partidas (**20 abertas** no
  futuro, 3 lotadas, 35 já jogadas) e 45 usuários.
- **Qualidade:** 169 testes passando (eram 157), revisão visual em 390 px, 1024 px e 1280 px.

**Amanhã:** o deploy é **New > Blueprint** no Render, escolhendo o repositório.
O passo a passo está mais abaixo.

---

## Como começar

O **servidor** (agora recarrega sozinho quando o código muda) e o **agendador**
ficaram rodando em segundo plano:

| Endereço | O que é |
| --- | --- |
| <http://127.0.0.1:8000/> | Site de apresentação |
| <http://127.0.0.1:8000/app/> | App do jogador |
| <http://127.0.0.1:8000/manager/> | Portal da arena (redesenhado) |
| <http://127.0.0.1:8000/admin/> | Back-office da plataforma |

| Perfil | Onde entrar | Login | Senha |
| --- | --- | --- | --- |
| Gestor da Arena Gol de Placa | `/manager/` | `carlos.andrade` | `gestor123` |
| Gestora do Complexo Esportivo Tabelinha | `/manager/` | `fernanda.lima` | `gestor123` |
| Gestor da Arena Pé na Areia | `/manager/` | `rafael.souza` | `gestor123` |
| Jogador demo, pelo celular | `/app/entrar/` | `(11) 90000-0001` | o código aparece na tela |
| Jogador demo, com senha | `/app/entrar/senha/` | `jogador` | `jogador123` |
| Superusuário | qualquer um | `admin` | `admin123` |

> Essas senhas valem **só no seu computador**. No Render, todas as contas usam
> uma senha gerada pelo próprio Render (veja o deploy abaixo).

### Roteiro sugerido (5 minutos)

1. Entre em `/manager/` como `carlos.andrade`.
2. **Início:** veja os 3 números e, na agenda, escolha um dia nas abas.
3. Toque em **Publicar** num horário livre. A partida entra à venda na hora,
   e o horário passa a mostrar "À venda 0/14" com o botão **Desfazer**.
4. Abra `/app/` em outra aba: a partida já está no feed.
5. **Agenda:** a semana completa, com o formulário detalhado (aluguel, vagas,
   goleiros e nível) e o **Cancelar partida** com reembolso automático.

---

## Deploy no Render (amanhã)

Tudo está no repositório. Não precisa de linha de comando nem de login pelo terminal.

1. Entre em <https://dashboard.render.com/> (pode ser com a conta do GitHub).
2. Clique em **New > Blueprint**.
3. Conecte o GitHub e escolha o repositório **ArenaMatch** (branch `main`).
4. O Render lê o `render.yaml` e mostra o que vai criar:
   - `arenamatch-db` (PostgreSQL, gratuito);
   - `arenamatch` (serviço web, gratuito).

   Clique em **Apply**.
5. O primeiro build leva alguns minutos (aqui, o ensaio levou 1 minuto; o plano
   gratuito é mais lento): instala tudo, compila o CSS, cria as tabelas e
   **popula a demonstração** (só porque o banco está vazio).
6. Quando aparecer **Live**, o endereço fica no topo da página do serviço
   (algo como `https://arenamatch.onrender.com`).
7. **Senha das contas de demonstração:** em **arenamatch > Environment**, copie o
   valor de `ARENAMATCH_SENHA_DEMO`. Ela vale para `admin`, para os 3 gestores e
   para os jogadores.

Para atualizar depois: cada `git push` na `main` gera um deploy novo, e o banco
**não** é apagado nem repopulado.

### Limites do plano gratuito

| Limite | Efeito |
| --- | --- |
| O site "dorme" após 15 min sem acesso | O primeiro acesso depois disso leva cerca de 1 minuto. Bom para mostrar a um piloto; ruim para uso real |
| O PostgreSQL gratuito expira em 30 dias | Antes disso, mude o banco para um plano pago no painel do Render |
| Não há *background worker* | O agendador roda junto do site (`start.sh`). Enquanto o site dorme, as rotinas param, e elas rodam todas assim que o site acorda |

---

## O que foi feito, fase a fase

### Fase −1 · Backup

A árvore de trabalho já estava limpa e sincronizada com o GitHub (último commit:
`797f480`). Não havia o que salvar; o commit de backup pedido ficaria vazio.

### Fase 0 · Infraestrutura (já existia)

PostgreSQL 18 via `DATABASE_URL` e agendador com APScheduler, feitos em 14/10 e
conferidos agora: o agendador rodou todas as rotinas sem erro.

### Fase 1 · Motor financeiro e portal B2B

O motor (taxa, reserva de 10 min, MockGateway) já existia. O que mudou foi o **portal**:

- **Início com 3 cards grandes:**

  | Card | O que mostra |
  | --- | --- |
  | **Saldo a receber** (verde-limão) | Valor liberado + a liberar, e quanto já caiu na conta no mês |
  | **Vagas vendidas** | Vagas pagas nos jogos do mês e o que elas rendem para a quadra |
  | **Horários ociosos** | Horários livres nos próximos 7 dias e quanto valeriam como partidas lotadas |

- **Agenda do dia com publicação em um toque:**
  - Abas para os próximos 7 dias, cada uma com o número de horários livres.
  - Uma linha do tempo por quadra.
  - Um toque num horário livre publica a partida com o último aluguel praticado
    na quadra, a capacidade dela, 2 goleiros grátis (a partir de 8 vagas) e o
    nível "Aberta a todos".
  - O preço por jogador aparece antes, na linha da quadra.
  - Enquanto ninguém comprou, o horário mostra **Desfazer**.
- **Linguagem do dono da quadra:** "Vaga vendida", "Devolução ao jogador",
  "Transferência para a sua conta" e "Centavos do rateio". A referência técnica
  do repasse (`mock_tr_…`) saiu do extrato.
- **Saiu do Início:** a tabela de próximas partidas (com "em pagamento"), a lista
  "hoje na arena" e o card de mensalistas. O **cancelamento com reembolso** foi
  para a Agenda, em cada partida.

### Fase 2 · Gamificação (já existia)

Perfis com nível de 1 a 5, posição, trava de nível e vaga de goleiro grátis,
feitos em 14/10. O check-in do portal ganhou o visual novo, com avatares e times
sugeridos.

### Fase 3 · Visual (Dark/Neon)

- **Portal no mesmo visual do app:**
  - fundo `zinc-950`, verde-limão para ação e dinheiro, ciano para informação;
  - vidro, Archivo extra-negrito;
  - menu lateral no computador e barra inferior no celular.
- **Todas as telas do portal foram refeitas:** início, agenda, check-in,
  check-in pelo QR, financeiro, ajustes (antes "Configurações"), login e acesso restrito.
- **Páginas de erro 404 ("Bola fora") e 500** no visual da marca. Antes aparecia
  o "Not Found" cru do Django.
- **Tailwind extraído e limpo:**
  - o CDN saiu e o CSS é compilado pelo executável oficial do Tailwind 4.3.3, sem Node.js;
  - o executável só roda depois de conferido o SHA-256 publicado no GitHub;
  - fonte em `arena/estilos/entrada.css` e comando `python manage.py compilar_css` (`--watch` enquanto edita);
  - componentes `botao-neon` (18 botões unificados), `botao-vidro`, `campo` e `selo`;
  - saíram os filtros e as cores do tema claro antigo;
  - antes de trocar, comparei capturas do app com o CDN e com o CSS compilado: ficaram idênticas.

### Fase 4 · Deploy (Render)

| Item | O que foi feito |
| --- | --- |
| `requirements.txt` | + `gunicorn` 26.2 e `whitenoise` 6.12 (o `dj-database-url` já estava) |
| `settings.py` | WhiteNoise com arquivos comprimidos e com hash (cache de 10 anos no navegador), `STATIC_ROOT`, `ALLOWED_HOSTS = ['*']` por padrão, domínio do Render no CSRF, cookies seguros, HSTS, cabeçalho do proxy HTTPS e log de erros no console |
| `build.sh` (executável) | `pip install`, `compilar_css`, `collectstatic`, `migrate` e a demonstração se o banco estiver vazio |
| `start.sh` (executável) | Agendador em segundo plano + gunicorn |
| `render.yaml` | Web + PostgreSQL gratuitos, região Virginia, chave secreta e senha da demonstração geradas pelo Render |
| `.python-version` | Python 3.14 no Render |
| `.gitattributes` | Scripts `.sh` sempre com fim de linha do Linux (senão quebrariam no Render) |

### Fase final · Dados

- **`populate_db`:**
  - 8 partidas futuras por arena (eram 6), o que dá 20 abertas;
  - nova opção `--se-vazio`, que só popula um banco sem arenas e nunca apaga nada;
  - fora do modo de desenvolvimento, exige `ARENAMATCH_SENHA_DEMO` com pelo menos 12 caracteres.
- Rodei o comando no banco local. Os acessos estão na tabela acima.

---

## Decisões que tomei sozinho (vale revisar)

| Tema | O que fiz | Por quê |
| --- | --- | --- |
| **"Saldo Disponível"** | O card virou **"Saldo a receber"** (liberado + a liberar) | A rotina horária transfere o saldo liberado para a arena, então o "disponível" fica quase sempre em R$ 0,00. Na demonstração, mostrava R$ 0,00 com R$ 1.079,87 a caminho. O Financeiro continua mostrando o "Liberado" separado |
| **"1 clique"** | O toque publica direto, com os valores sugeridos, e oferece **Desfazer** enquanto ninguém comprou | É o "1 clique" literal. Quem quiser ajustar aluguel, vagas ou nível usa a Agenda, que tem o formulário completo |
| **psycopg2-binary** | Mantive o **psycopg 3** | É o sucessor do psycopg2 e o driver recomendado pelo Django 5. Funciona igual no Render |
| **Celery + Redis** | Mantive o **APScheduler** | Decidido em 14/10: são poucas rotinas periódicas. O Redis seria mais um serviço pago no Render |
| **Agendador no Render** | Roda **no mesmo contêiner do site** | O plano gratuito não tem *worker*. O `render.yaml` traz o worker pronto (comentado) para quando houver plano pago |
| **`ALLOWED_HOSTS = ['*']`** | Feito como pedido, mas pela variável `DJANGO_ALLOWED_HOSTS` | Depois do primeiro deploy, troque para `arenamatch.onrender.com` no painel (Environment). Não exige mudar código |
| **Senhas no Render** | Todas as contas de demonstração usam uma senha gerada pelo Render | **O repositório é público.** Com `admin123`, qualquer pessoa entraria como superusuário no site publicado |
| **Login pelo celular no Render** | O código **não** aparece na tela em produção | Mostrar o código na tela deixaria qualquer pessoa entrar na conta de qualquer telefone. No Render, use o login com senha |
| **Gateway no Render** | **Simulado** (`ARENAMATCH_PERMITIR_GATEWAY_SIMULADO=True`) | Ainda não há gateway real. O "Simular pagamento aprovado" funciona no site publicado, e nenhum dinheiro se move |
| Região | Virginia (EUA) | É a região do Render mais próxima do Brasil |
| CSS no repositório | O CSS compilado é versionado, e o build recompila | Se o download do Tailwind falhar no Render, o deploy segue com o arquivo versionado |
| Nomes no portal | "Ajustes", "Transferências", "Devoluções", "Livre" | Linguagem do dono da quadra, sem termos contábeis |
| HTTPS | Sem redirecionamento no Django; HSTS de 1 hora | O Render já redireciona para HTTPS. O HSTS pode crescer quando houver domínio próprio |

---

## Verificação feita

- **169 testes automatizados** passando (eram 157). Os 12 novos cobrem:
  - os 3 números do painel e a agenda do dia;
  - a publicação em um toque, usando o formulário exatamente como aparece na tela;
  - o "Desfazer";
  - o dia inválido na URL;
  - `--se-vazio` e a senha da demonstração;
  - as 15+ partidas abertas;
  - o CSS compilado;
  - a rejeição de um executável do Tailwind adulterado;
  - a página 404.
- A suíte também passa com `DEBUG=False`, como em produção.
- `manage.py check --deploy`: restam 3 avisos esperados (HSTS de subdomínios,
  pré-carregamento do HSTS e redirecionamento HTTPS, que o Render já faz).
- **Ensaio do deploy:**
  - Num **banco PostgreSQL novo e vazio**, o `build.sh` completo rodou com
    `DEBUG=False`: instalação, CSS, collectstatic, migrate e demonstração, em 58 s.
  - Rodado de novo, não alterou nada.
- **Modo produção local:**
  - as páginas respondem;
  - o WhiteNoise entrega o CSS com hash, comprimido e com cache longo;
  - o login do gestor passa pelo CSRF atrás do proxy HTTPS simulado (o erro mais comum de Django no Render);
  - o HSTS aparece só em HTTPS.
- **Capturas** de todas as telas do portal em 390 px, 1024 px e 1280 px, sem rolagem horizontal.

**O que não pude testar aqui:** o gunicorn e o `start.sh`, porque não rodam no
Windows e não há WSL nem Docker nesta máquina. São comandos padrão, mas o
primeiro deploy é a prova real. Se algo falhar, o log do Render
(**arenamatch > Logs**) mostra o erro completo.

## Pontos de atenção

1. **Nenhum dinheiro real se move**, nem no Render. Antes de cobrar, troque o
   gateway e desligue `ARENAMATCH_PERMITIR_GATEWAY_SIMULADO`. O webhook do
   gateway simulado não valida assinatura.
2. **Banco gratuito expira em 30 dias.** Se o piloto passar disso, migre o banco antes.
3. Continuam valendo os pontos jurídicos e contábeis do relatório de 14/10:
   crédito não sacável e CDC, custódia e split, notas fiscais e LGPD.

## Arquivos novos e alterados

- **Novos:**
  - `render.yaml`, `build.sh`, `start.sh`, `.python-version`, `.gitattributes`;
  - `arena/estilos/entrada.css` e `arena/static/arena/css/arena.css`;
  - `arena/management/commands/compilar_css.py`;
  - `arena/templates/404.html`, `500.html` e `arena/_manager_horario.html`;
  - `arena/tests/test_deploy.py`.
- **Refeitos:** todos os templates `manager_*` e `_manager_*`.
- **Alterados:**
  - `gestao.py`, `views.py`, `arena_extras.py`, `populate_db.py` e `settings.py`;
  - `requirements.txt`, README e `.env.example`;
  - 13 templates do app e do site (CSS compilado no lugar do CDN e componente `botao-neon`, sem mudança visual).
- **Removidos:** `_manager_campo.html` (o portal usa o mesmo campo do app) e o
  código do painel antigo (`proximas_partidas`, `agenda_de_hoje`, filtros do tema claro).
