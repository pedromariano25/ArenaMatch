# Relatório da madrugada · ArenaMatch

**Data:** 14/10/2026, das 00h20 às 07h · **Modo:** operação autônoma (Night Shift), Fases −1 a 3

## Resumo

Todas as fases do roadmap foram executadas, testadas e publicadas no GitHub
(<https://github.com/pedromariano25/ArenaMatch>):

- **Fase −1 · Base:** commit inicial e repositório público criado com o GitHub CLI.
- **Fase 0 · Infraestrutura:** PostgreSQL 18 no lugar do SQLite e um agendador de rotinas automáticas.
- **Fase 1 · Dinheiro:** pagamento 100% no app (Pix, cartão ou crédito) com razão contábil, reserva de 10 minutos, cancelamento com crédito, repasse de vaga, mínimo de jogadores e repasse às arenas. O gateway é **simulado**: nenhum dinheiro real se move.
- **Fase 2 · Jogadores:** perfil com nível de 1 a 5, trava de nível nas partidas, vaga grátis de goleiro, check-in por QR, confiabilidade, avaliação pós-jogo e sugestão de times.
- **Fase 3 · Produto:** site em `/`, app do jogador em `/app/` com tema escuro, feed com os rostos de quem vai, checkout rápido, login pelo celular e filtro "perto de mim".
- **Dados de demonstração:** 3 arenas, 54 partidas (35 já jogadas), 585 inscrições, 477 pagamentos, 1.601 lançamentos contábeis e 45 usuários, com 6 dias de histórico.
- **Qualidade:** 157 testes automatizados passando, conferência do razão sem divergências e revisão visual no celular e no desktop.

---

## Como começar

O **servidor** e o **agendador** ficaram rodando em segundo plano. É só abrir:

| Endereço | O que é |
| --- | --- |
| <http://127.0.0.1:8000/> | Site de apresentação |
| <http://127.0.0.1:8000/app/> | App do jogador |
| <http://127.0.0.1:8000/manager/> | Portal do Gestor (ArenaManager) |
| <http://127.0.0.1:8000/admin/> | Back-office da plataforma |
| <http://127.0.0.1:8000/api/> | API REST navegável |

| Perfil | Onde entrar | Login | Senha |
| --- | --- | --- | --- |
| Jogador demo, pelo celular | `/app/entrar/` | `(11) 90000-0001` | o código aparece na tela |
| Jogador demo, com senha | `/app/entrar/senha/` | `jogador` | `jogador123` |
| Demais jogadores (ex.: `lucas.oliveira`) | `/app/entrar/senha/` | — | `jogador123` |
| Gestor da Arena Gol de Placa | `/manager/` | `carlos.andrade` | `gestor123` |
| Gestora do Complexo Esportivo Tabelinha | `/manager/` | `fernanda.lima` | `gestor123` |
| Gestor da Arena Pé na Areia | `/manager/` | `rafael.souza` | `gestor123` |
| Superusuário | qualquer um | `admin` | `admin123` |

As senhas do PostgreSQL (usuário `postgres` e usuário `arenamatch`) estão só no
seu `.env`, que não vai para o GitHub.

### Roteiro sugerido (15 minutos)

1. **Site:** abra `/` e clique em **"Achar um jogo"**.
2. **Feed sem login:** use os filtros de um toque (dia, piso) e **"Perto de mim"**. O navegador pede permissão de localização e os jogos passam a vir ordenados por distância.
3. **Login pelo celular:** em **Entrar**, digite `(11) 90000-0001`. Em modo de demonstração o código aparece na própria tela (e no log do servidor). Você entra como o Jogador Demo.
4. **Garantir vaga:** no feed, toque em **"Garantir vaga"**. O checkout rápido abre por cima da lista:
   - **Cartão:** aprovado na hora, você vai direto para o comprovante.
   - **Pix:** aparece um "copia e cola" de mentira; clique em **"Simular pagamento aprovado"**.
5. **Comprovante:** tem o QR de check-in, "Adicionar à agenda" e "Como chegar".
6. **Minhas partidas:** o demo tem R$ 22,64 de crédito (de um cancelamento) e 2 jogos para **avaliar**. Avalie um: nível da partida e elogios aos colegas.
7. **Perfil:** nível, jogos, confiabilidade, crédito e elogios recebidos.
8. **Portal como `carlos.andrade`:**
   - **Financeiro:** valores a liberar, disponíveis, extrato e repasses.
   - **Check-in:** a lista de presença dos jogos de hoje, com os times sugeridos. O QR do comprovante, lido com a câmera do celular, abre direto a ficha do jogador.
   - **Agenda:** "Transformar em partida aberta", agora com vagas de goleiro e prévia do preço.
   - **Configurações:** mínimo de jogadores, prazo e localização da arena.

### Comandos úteis

```powershell
.\venv\Scripts\python.exe manage.py populate_db   # APAGA tudo e recria a demonstração (~50 s)
.\venv\Scripts\python.exe manage.py test arena    # 157 testes (~1 min)
.\venv\Scripts\python.exe manage.py agendador     # rotinas automáticas (deixe 1 rodando)
```

> **Sobre os processos em segundo plano:** o servidor foi iniciado com
> `--noreload`, então **não recarrega quando o código muda**. Para trabalhar no
> código, encerre os dois e suba de novo no terminal:
>
> ```powershell
> Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "manage.py (runserver|agendador)" } | ForEach-Object { Stop-Process -Id $_.ProcessId }
> .\venv\Scripts\python.exe manage.py runserver
> ```
>
> O log do agendador está em `agendador.log` (ignorado pelo Git).

---

## O que foi feito, fase a fase

### Fase −1 · Base e GitHub

- Commit `feat: base do motor financeiro e estruturacao inicial`.
- GitHub CLI instalado (winget). Você autorizou o login pelo navegador.
- Repositório criado e enviado com `gh repo create ArenaMatch --public --source=. --remote=origin --push`.

### Fase 0 · Infraestrutura

- **PostgreSQL 18.6** instalado como serviço do Windows (`postgresql-x64-18`, porta 5432), com o usuário `arenamatch` (com permissão para criar o banco de testes) e o banco `arenamatch` em UTF-8.
- **Configuração por `DATABASE_URL`** (`dj-database-url`), com conexões persistentes e verificação de saúde. Sem a variável, ou com outro banco que não o PostgreSQL, o projeto se recusa a subir.
- **Agendador** (`python manage.py agendador`, APScheduler) num processo separado do site. As rotinas ficam em `arena/rotinas.py`:

  | Rotina | Intervalo | O que faz |
  | --- | --- | --- |
  | `expirar_reservas` | 1 min | Devolve à partida as vagas reservadas e não pagas em 10 min |
  | `conferir_quorum` | 5 min | No prazo, cancela e reembolsa partidas sem o mínimo de jogadores |
  | `finalizar_partidas` | 15 min | Encerra partidas, registra faltas e fecha as contas |
  | `gerar_repasses` | 60 min | Transfere às arenas o saldo já liberado |
  | `limpar_sessoes_expiradas` | 1 dia | Apaga logins expirados |

  Todas são idempotentes: rodar atrasado ou duas vezes não duplica dinheiro.

### Fase 1 · Pagamento in-app e razão contábil

- **Checkout:** ao clicar em "Garantir vaga", a vaga fica reservada por 10 minutos e o pagamento é criado. O cartão é aprovado na hora, o Pix espera a confirmação, o goleiro entra de graça e o crédito é descontado na hora.
- **Preço:** parte da quadra (aluguel ÷ vagas de linha) + taxa de 15% sobre ela, com mínimo de R$ 2,00. O cartão custa 5% a mais. Os valores ficam **congelados na inscrição**, e o preço da partida trava assim que alguém se inscreve.
- **Contrato por arena:** taxa, taxa mínima, mínimo de jogadores e prazo ficam na arena. Cada partida guarda uma cópia do contrato vigente quando foi aberta.
- **Razão contábil:** cada centavo vira um lançamento **imutável** (não dá para editar nem apagar, nem pelo admin). Há três tipos de carteira (arena, plataforma e crédito do jogador), e os repasses ficam registrados à parte. O saldo é sempre a soma dos lançamentos.
- **Cancelamento pelo jogador:** até 24h antes, crédito integral. Depois disso, o jogador pode **repassar a vaga** para a lista de espera; se alguém assumir, ele recebe crédito.
- **Mínimo de jogadores:** sem o mínimo no prazo, a partida é cancelada. Pix e cartão são estornados pelo meio original, e quem pagou com crédito recebe crédito de volta.
- **Pagamento atrasado:** se o Pix chega depois de a reserva expirar, o sistema confirma se ainda houver vaga e estorna automaticamente se não houver.
- **Liberação e repasse:** a parte da arena fica "a liberar" até 24h depois do fim do jogo, vira "disponível" e é repassada pela rotina horária.
- **Gateway:** interface `Gateway` em `arena/pagamentos.py`, com o `MockGateway` para desenvolvimento e um webhook em `/pagamentos/webhook/`. O `MockGateway` se recusa a rodar fora do modo de desenvolvimento.
- **E-mails:** inscrição confirmada, vaga aberta na lista de espera, partida cancelada, vaga repassada e pagamento devolvido. São enviados só depois que a transação é gravada (em desenvolvimento, aparecem no console).
- **Portal:** Financeiro com saldo a liberar e disponível, extrato filtrável e histórico de repasses, além de cancelamento de partida com reembolso.
- **Migração dos dados antigos:** as inscrições existentes foram convertidas para os novos status (pago → confirmada, pendente → aguardando pagamento, reembolsado → reembolsada) sem perder histórico.

### Fase 2 · Jogadores, níveis e partidas equilibradas

- **Perfil:** 3 perguntas (autoavaliação, frequência e experiência), posição e "topo jogar no gol". O nível de 1 a 5 é calculado pelas respostas e é pedido antes da primeira partida.
- **Trava de nível:** Iniciante aceita níveis 1–2, Intermediário 2–4, Avançado 4–5 e Aberta a todos 1–5. A trava cai 1h antes do prazo do mínimo de jogadores, se ainda houver vaga.
- **Goleiro:** vaga própria e grátis, com o aluguel dividido entre os jogadores de linha. Goleiro que falta sem avisar perde a vaga grátis por 14 dias.
- **Check-in:** a recepção lê o QR do comprovante. Se a arena fez check-in em alguém da partida, quem não apareceu leva falta.
- **Confiabilidade:** percentual de presença, exibido no perfil.
- **Avaliação pós-jogo** (até 7 dias depois): nível da partida, elogios (só positivos) e, em partidas com faixa, sinal de que um colega joga acima ou abaixo dela. Três colegas diferentes sinalizando a mesma coisa ajustam o nível em um ponto.
- **Times:** sugestão de dois times de força parecida, com um goleiro em cada.

### Fase 3 · Site, app e acesso

- **Site em `/`:** apresentação, jogos em destaque e chamada para arenas.
- **App em `/app/`:** os endereços antigos (`/partidas/...` e outros) redirecionam para o app.
- **Tema escuro:** fundo `zinc-950`, neon verde-limão (ação) e ciano (informação), superfícies de vidro e títulos em Archivo extra-negrito. Barra de navegação inferior no celular.
- **Feed:**
  - Cada partida mostra os rostos de quem vai, as vagas restantes, a faixa de nível e o preço.
  - Filtros de um toque: dia, "Meu nível", piso e "Perto de mim".
  - O checkout rápido abre por cima da lista.
- **Login pelo celular:** código de 6 dígitos que vale 10 minutos, com 5 tentativas por código e até 3 códigos a cada 15 minutos por número. Só o hash do código fica no banco. A conta de jogador é criada no primeiro acesso, e o login por senha continua disponível.
- **Localização:** latitude e longitude da arena configuráveis no Portal. A distância é calculada na hora; a localização do jogador **não é gravada**.
- **Telas novas ou refeitas:** partida, checkout, Pix, comprovante, minhas partidas, perfil, configurar perfil, avaliação, entrar e cadastro.
- **O Portal do Gestor mantém o visual claro "Clean SaaS"**, e o check-in entrou no menu.

### Dados de demonstração (`populate_db`)

O comando "volta no tempo" para criar 6 dias de histórico real. Todas as
operações passam pelas mesmas regras do sistema:

- Checkouts, cancelamentos com crédito, uma partida cancelada por falta de quórum e outra pela arena.
- Check-ins com faltas, avaliações, um ajuste de nível pela comunidade e repasses já pagos.
- Para o futuro: partidas lotadas com lista de espera, reservas aguardando pagamento e as partidas do Jogador Demo.

---

## Decisões que tomei sozinho (vale revisar)

As regras que você escolheu nos pop-ups foram seguidas à risca. Nos pontos
abaixo, que você não tinha definido, fiz a escolha que me pareceu mais segura.
Todas são fáceis de mudar (a maioria é uma constante no topo de `arena/models.py`).

| Tema | O que fiz | Por quê |
| --- | --- | --- |
| Arredondamento | A parte da quadra é truncada no centavo (R$ 200 ÷ 14 = R$ 14,28). Quando todas as vagas de linha são pagas, a arena recebe os centavos que faltam, pagos pela plataforma no fechamento | A arena nunca recebe menos que o aluguel, e o preço anunciado fica "redondo" |
| **Tarifa do gateway** | **100% custo da plataforma**, inclusive sobre a parte da arena, e não volta em estornos | É o modelo mais simples para a arena. **Na demonstração, as tarifas consumiram ~14% da receita bruta da plataforma** (R$ 237 de R$ 1.714). Com split, dá para dividir a tarifa proporcionalmente. É uma decisão comercial sua |
| Acréscimo do cartão | 5% sobre o total (parte da quadra + taxa), receita da plataforma | Cobre a tarifa típica de cartão |
| "Libera no dia seguinte" | 24h depois do **fim** do jogo | Dá tempo de tratar reclamações antes do repasse |
| Repasse de vaga | Quem repassa recebe **crédito** (não dinheiro) quando alguém da lista de espera paga | Coerente com a regra de cancelamento com crédito |
| Fórmula do nível | (2 × autoavaliação + frequência + experiência) ÷ 4, arredondado | A autoavaliação pesa mais, e as outras duas corrigem exageros |
| Ajuste pela comunidade | 3 colegas diferentes com o mesmo sinal = ±1 nível; sinais em partidas "Aberta a todos" não contam | Evita que uma pessoa sozinha (ou uma partida sem faixa) mude o nível de alguém |
| Goleiros | O portal sugere 2 vagas de goleiro em partidas com 8 ou mais jogadores | Um por time |
| Falta | Só conta se a arena fez check-in de alguém naquela partida | Se a arena não usa o check-in, ninguém é punido por isso |
| Janelas | Check-in de 1h antes até o fim do jogo; avaliação até 7 dias depois | Valores comuns no mercado, ajustáveis |

---

## Bibliotecas e ferramentas instaladas

| O quê | Versão | Para quê | Onde |
| --- | --- | --- | --- |
| `psycopg[binary]` | 3.3.6 | Driver do PostgreSQL (sucessor do psycopg2, recomendado pelo Django) | `requirements.txt` |
| `dj-database-url` | 3.1.2 | Lê a `DATABASE_URL` | `requirements.txt` |
| `APScheduler` | 3.11.3 (+ `tzlocal` 5.4.4) | Agendador de rotinas | `requirements.txt` |
| `ruff` | 0.17.0 | Verificação de código | só no `venv` (ferramenta de desenvolvimento) |
| `websocket-client` | 1.9.2 | Usado só pelas minhas capturas de tela; pode remover com `pip uninstall websocket-client` | só no `venv` |
| PostgreSQL | 18.6 | Banco de dados | serviço do Windows |
| GitHub CLI | 2.102.0 | Criar o repositório e enviar os commits | Windows (winget) |
| Tailwind (browser) 4.3.3, qrcodejs 1.0.0, fontes Archivo e Inter | — | Visual do app e QR do comprovante | carregados por CDN, sem instalação |

Escolhi o **APScheduler** em vez de **Celery + Redis** porque as rotinas são
poucas e periódicas. O Celery exigiria um Redis rodando (sem versão oficial
para Windows) e mais um processo para manter. Se um dia houver filas pesadas
(ex.: milhares de notificações), a troca é localizada em `arena/agendador.py`.

---

## Problemas encontrados e resolvidos

| Problema | Causa | Solução |
| --- | --- | --- |
| A migração gerada apagaria o status de pagamento das inscrições antigas | O Django removeria o campo antigo antes de converter os valores | Dividi em três migrações: cria o campo novo, converte os dados e só então remove o antigo |
| Erro do PostgreSQL ao gerar repasses | `SELECT ... FOR UPDATE` não pode travar o lado opcional de um *join* | A consulta travada deixou de carregar relações junto |
| A rotina do agendador derrubava a conexão nos testes | Fechar conexões "velhas" dentro de uma transação aberta | As conexões só são recicladas fora de transações |
| **Login pelo celular: as tentativas erradas não eram contadas** | O erro desfazia a transação, inclusive o contador; daria para tentar códigos sem limite | O erro passou a ser lançado depois de gravar a tentativa, e um teste cobre o caso |
| O `populate_db` colocava jogadores fora da faixa de nível em listas de espera | Os dados eram sorteados sem checar elegibilidade | A demonstração passou a usar a mesma regra de elegibilidade do app |
| Telas do celular | Botão "Criar conta" quebrava em duas linhas; espaçamento torto no checkout; nome da arena espremido no histórico; crédito vazando do cartão no perfil; avaliação longa demais | Ajustes de layout, conferidos com capturas em 390px (celular) e 1280px (desktop) |
| Extrato do crédito confuso | O texto do lançamento era o da arena (com o nome do próprio jogador) | O extrato do jogador mostra "Crédito recebido · Arena" e a data do jogo |

---

## Verificação feita

- **157 testes automatizados** passando no PostgreSQL (~1 minuto), em 11 arquivos: modelos, checkout, partidas, jogadores, API, portal, admin, app, site, agendador e `populate_db`.
- `makemigrations --check` e `manage.py check` sem pendências.
- `ruff` sem erros nas regras padrão. Há um `ruff` global na sua máquina que liga regras extras de estilo e aponta 110 itens de estilo, nenhum bug; não as adotei porque o projeto não as define.
- **Conferência do razão** nos dados finais:
  - Em cada arena, as vendas batem com as inscrições confirmadas, mais os ajustes de centavos.
  - As partidas canceladas têm saldo zero.
  - Nenhum jogador tem crédito negativo.
- **Teste de fumaça** no servidor real:
  - Todas as páginas respondem para o visitante, o jogador, o gestor e o admin.
  - Os endereços antigos redirecionam para o app.
  - O login pelo celular funciona de ponta a ponta com o número de demonstração.
- **Revisão visual** com capturas no celular (390px) e no desktop (1280px), sem rolagem horizontal.

## Commits da madrugada

```text
c5d1411 feat: base do motor financeiro e estruturacao inicial
7887b54 feat(infra): PostgreSQL via DATABASE_URL e agendador de rotinas (Fase 0)
4ef54ce feat(financeiro): checkout in-app, razão contábil e regras automáticas (Fase 1)
6544c7d feat(jogadores): perfis, níveis, goleiro, check-in e avaliações (Fase 2)
bb57de4 feat(app): site em /, app do jogador em /app/, login pelo celular e perto de mim (Fase 3)
        docs: relatório da madrugada
```

---

## O que ficou de fora (e por quê)

- **Login com Google:** precisa de credenciais OAuth criadas por você no Google Cloud Console. O login pelo celular já cobre o acesso sem senha.
- **Gateway real com split e SMS real:** dependem de contrato e chaves com os provedores. A estrutura está pronta: `Gateway` em `arena/pagamentos.py` e `ARENAMATCH_SMS_BACKEND` em `arena/acesso.py`.
- **Visual "Plei":** usei a referência de experiência (escuro, neon, rostos no feed, compra em um toque) com identidade própria, sem copiar a marca.

## Pontos de atenção antes de ir para produção

1. **Nenhum dinheiro real se move hoje.** O `MockGateway` só funciona em desenvolvimento e o webhook dele não valida assinatura. A implementação do gateway real precisa validar a assinatura de cada notificação.
2. **Validar com advogado e contador antes de cobrar de verdade:**
   - O **crédito não sacável** no cancelamento pode esbarrar no direito de arrependimento do CDC em compras pela internet.
   - **Guardar o dinheiro das arenas** na conta do ArenaMatch pode ser tratado como atividade regulada de pagamentos. Com o split do gateway, a parte da arena vai direto para a conta dela, e o razão passa a só espelhar isso.
   - **Notas fiscais:** quem emite a nota de cada parte (taxa e aluguel)?
3. **SMS:** hoje o limite é por número de telefone. Antes de ligar um provedor pago, inclua limite por IP e um captcha. Sem isso, um robô pode disparar SMS para milhares de números e gerar custo.
4. **LGPD:** telefone e CPF são dados pessoais. Faltam política de privacidade e termos de uso. A localização não é gravada no banco: só vai na URL da busca.
5. **Tailwind via CDN** não é para produção. Antes do deploy, gere o CSS com o build do Tailwind.
6. **Python 3.15 com Django 5.2:** o Django declara suporte oficial até o Python 3.14. Tudo passou nos testes, mas é a primeira suspeita se algo estranho aparecer.
7. **Repositório público:** o código e as regras de negócio estão visíveis. Os segredos (`.env`) não vão para o GitHub.
8. **`db.sqlite3`:** é o banco antigo, que não é mais usado e nem vai para o GitHub. Pode apagar quando quiser.

## Próximos passos sugeridos

1. **Escolher o gateway com split** (Mercado Pago, Pagar.me ou Asaas). Compare a tarifa e quem paga a tarifa no split; isso mexe direto na sua margem.
2. **Conversa com advogado e contador** sobre crédito, split e notas fiscais, com este relatório em mãos.
3. **SMS real** (com limite por IP) e **login com Google**.
4. **Deploy:**
   - PostgreSQL gerenciado.
   - Agendador como *worker*, com uma instância só.
   - Build do Tailwind, `DEBUG=False` e HTTPS.
5. **Piloto com uma arena**, para medir conversão de horários vagos e a taxa de faltas.
