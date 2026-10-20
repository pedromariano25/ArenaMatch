# ArenaMatch · Tudo o que existe hoje no software

**Retrato de:** 20/10/2026 · **Versão no GitHub:** `main`, depois do commit
"refactor: design pivot ultra-minimalista, setup flutter e expansao de toolkit" ·
**No ar:** <https://arenamatch-production.up.railway.app> (ainda com a versão
anterior ao pivô, até o próximo `railway up`)

Este documento lista o que o sistema faz hoje, regra por regra, tela por tela. O
que ainda **não** existe está no fim, em "O que não existe (ainda)".

---

## Sumário

1. [Visão geral](#1-visão-geral)
2. [Quem usa e onde entra](#2-quem-usa-e-onde-entra)
3. [Regras de negócio](#3-regras-de-negócio)
4. [Dinheiro: preços, razão contábil e repasses](#4-dinheiro-preços-razão-contábil-e-repasses)
5. [Pelada de grupo (C2C)](#5-pelada-de-grupo-c2c)
6. [Jogadores: perfil, nível, check-in e avaliações](#6-jogadores-perfil-nível-check-in-e-avaliações)
7. [Telas do site e do app do jogador](#7-telas-do-site-e-do-app-do-jogador)
8. [Portal da arena](#8-portal-da-arena)
9. [Back-office (Django Admin)](#9-back-office-django-admin)
10. [API REST](#10-api-rest)
11. [Rotinas automáticas](#11-rotinas-automáticas)
12. [Avisos por e-mail](#12-avisos-por-e-mail)
13. [Segurança](#13-segurança)
14. [Banco de dados](#14-banco-de-dados)
15. [Dados de demonstração](#15-dados-de-demonstração)
16. [Infraestrutura e deploy](#16-infraestrutura-e-deploy)
17. [Qualidade e testes](#17-qualidade-e-testes)
18. [Configuração (variáveis de ambiente)](#18-configuração-variáveis-de-ambiente)
19. [O que é simulado](#19-o-que-é-simulado)
20. [O que não existe (ainda)](#20-o-que-não-existe-ainda)
21. [Trabalho guardado fora da `main`](#21-trabalho-guardado-fora-da-main)

---

## 1. Visão geral

O ArenaMatch é um SaaS de futebol amador com três frentes que usam o mesmo banco:

| Frente | Para quem | O que entrega |
| --- | --- | --- |
| **B2B** | Donos de arenas (complexos esportivos) | Portal da arena: agenda das quadras, publicação de partidas abertas em um toque, check-in, financeiro e ajustes |
| **B2C** | Jogadores avulsos | App web mobile-first: achar jogo, pagar pelo app e entrar em campo |
| **C2C** | Organizadores de peladas (mensalistas) | Vender as vagas que faltam no grupo e sacar o dinheiro via Pix |

**Modelo de receita:** take rate (intermediação). O jogador paga a vaga pelo app
(100% in-app, sem pagamento "na arena"). A plataforma fica com uma taxa de
serviço, e o resto vai para a arena (partida aberta) ou para o organizador
(pelada de grupo). Não existe mensalidade de software cobrada da arena.

---

## 2. Quem usa e onde entra

| Endereço | O que é | Quem acessa |
| --- | --- | --- |
| `/` | Site de apresentação | Qualquer pessoa |
| `/app/` | App do jogador (feed e tudo do jogador) | Qualquer pessoa; comprar exige conta |
| `/app/organizar/` | Pelada de grupo (organizador) | Jogadores logados |
| `/manager/` | Portal da arena | Gestores de arena e superusuários |
| `/admin/` | Back-office da equipe ArenaMatch (gestores veem só as próprias arenas) | Equipe e gestores |
| `/api/` | API REST navegável | App Flutter e integrações |
| `mobile_app/` | App Flutter (Android e iOS), no repositório | Jogadores e organizadores |
| `/pagamentos/webhook/` | Notificações do gateway de pagamento | O gateway |

**Tipos de conta (podem ser combinados):** jogador, gestor de arena, superusuário.
Um superusuário vê todas as arenas no portal.

**Endereços antigos** (`/partidas/...`, `/perfil/`, `/entrar/` etc., de quando o
app ficava na raiz) redirecionam para `/app/...`.

---

## 3. Regras de negócio

### Arenas, quadras e agenda

- **Arena:**
  - dados: nome, CNPJ (valida dígitos e aceita o formato alfanumérico de 2026), endereço, telefone;
  - horário de funcionamento (pode virar a meia-noite) e latitude/longitude, para o "perto de mim";
  - um gestor responsável;
  - um contrato próprio: taxa da plataforma (padrão 15%), taxa mínima por vaga (padrão R$ 2,00), mínimo de jogadores (padrão 70% das vagas) e prazo do mínimo (padrão 3h antes, de 1 a 48h).
- **Quadra:**
  - nome único dentro da arena;
  - piso: sintético, salão, areia ou campo;
  - capacidade padrão de jogadores.
- **Horário da agenda** (faixa de uma quadra num dia):
  - tipo: mensalista, avulso ou bloqueado;
  - situação: confirmado, ocioso ou cancelado;
  - horários não podem se sobrepor na mesma quadra (o sistema recusa o conflito);
  - "00:00" no fim significa meia-noite.

### Partida aberta (da arena)

- Nasce de um horário **livre** (ocioso ou cancelado) e futuro.
- **O gestor define** o aluguel total, as vagas totais, as vagas de goleiro (o sistema sugere 2 a partir de 8 vagas) e o nível.
- **Situação:** aberta → lotada (automático pelas vagas) → finalizada ou cancelada.
- **Preço travado:** depois da primeira inscrição, aluguel, vagas e taxa não mudam mais.
- **Uma partida por horário.** Uma partida cancelada pode ser reaberta no mesmo horário.

### Inscrição (vaga)

| Situação | Quando |
| --- | --- |
| Aguardando pagamento | Assim que o jogador escolhe a vaga; segura a vaga por **10 minutos** |
| Confirmada | Pagamento aprovado (ou goleiro grátis, ou pago com crédito) |
| Expirada | Os 10 minutos acabaram sem pagamento; a vaga volta para a partida |
| Cancelada | O jogador desistiu (ou a reserva foi cancelada) |
| Reembolsada | A partida foi cancelada e o dinheiro voltou |

- Um jogador tem no máximo uma inscrição ativa por partida.
- A última vaga é protegida contra compra simultânea (trava de linha no banco).
- **Pagamento atrasado:** se o Pix é aprovado depois de a reserva expirar, o sistema confirma a vaga se ela ainda existir; se não, devolve o dinheiro automaticamente.

### Cancelamento e repasse pelo jogador

| Caso | O que acontece |
| --- | --- |
| Reserva ainda não paga | Cancela sem cobrança |
| Vaga paga, **até 24h antes** | Cancela; o valor integral volta como **crédito ArenaMatch** (não sacável) |
| Vaga paga, **a menos de 24h** | Não cancela; o jogador pode **repassar** a vaga à lista de espera. Se alguém comprar, ele recebe crédito integral; se ninguém comprar, a vaga continua dele. Dá para desfazer o repasse |
| Vaga de goleiro grátis | Pode ser liberada a qualquer momento antes do jogo |

### Mínimo de jogadores (quórum)

- No prazo (padrão 3h antes), a partida precisa de um mínimo de vagas pagas (padrão 70%).
- Se atingir, o jogo fica confirmado. Se não, a partida é **cancelada automaticamente** e todos são reembolsados:
  - Pix e cartão: estorno pela mesma forma;
  - crédito: volta como crédito;
  - reservas em andamento: canceladas.
- **Pelada de grupo não tem quórum** (veja a seção 5).

### Lista de espera

- Partida lotada: o jogador entra na fila (respeitando a trava de nível).
- Quando abre vaga (cancelamento, expiração ou repasse), os 10 primeiros da fila recebem e-mail. Quem pagar primeiro, leva.

### Cancelamento pela arena

O gestor cancela uma partida pelo portal (ou pelo admin). Todos recebem o
dinheiro de volta na hora, pela mesma regra do quórum.

---

## 4. Dinheiro: preços, razão contábil e repasses

### Preço da vaga (partida da arena)

| Parte | Cálculo |
| --- | --- |
| Parte da quadra | Aluguel ÷ vagas de linha, truncado no centavo (R$ 200 ÷ 14 = R$ 14,28) |
| Taxa de serviço | 15% da parte da quadra, com mínimo de R$ 2,00 (contrato da arena) |
| **Preço no Pix (ou crédito)** | Parte da quadra + taxa |
| Preço no cartão | Pix + 5% (para cobrir a tarifa do cartão) |
| Goleiro | Grátis (padrão); o aluguel é dividido só entre os jogadores de linha |

**Valores congelados:** o que cada jogador pagou fica gravado na inscrição.

**Centavos do rateio:** quando todas as vagas de linha são pagas, a arena recebe
o resíduo (ex.: os R$ 0,08 que faltam para R$ 200), pago pela plataforma no
fechamento da partida.

### Formas de pagamento

- **Pix:** gera um "copia e cola" e espera a confirmação.
- **Cartão:** aprovado na hora.
- **Crédito ArenaMatch:** só quando o saldo cobre a vaga inteira.
- **Gratuito:** goleiro grátis.

### Razão contábil

Todo centavo vira um **lançamento imutável**: não pode ser editado nem apagado,
nem pelo admin, e correções entram como estornos. O saldo de qualquer carteira é a
soma dos lançamentos.

| Carteira | De quem | O que entra e sai |
| --- | --- | --- |
| Arena | Cada arena | Vendas de vagas (a liberar), estornos, centavos do rateio e repasses |
| Plataforma | ArenaMatch | Taxa de serviço, acréscimo do cartão, tarifa do gateway (custo), estornos e centavos do rateio (custo) |
| Crédito do jogador | Cada jogador | Créditos de cancelamento e repasse, e uso de crédito (não sacável) |
| Saldo do organizador | Cada organizador | Vendas das peladas de grupo e saques via Pix (sacável) |

- **Tipos de lançamento:** venda de vaga, taxa de serviço, acréscimo do cartão, tarifa do gateway, estorno, crédito ao jogador, uso de crédito, ajuste de fechamento, repasse à arena e saque via Pix.
- **Tarifa do gateway:** custo 100% da plataforma (inclusive sobre a parte da arena) e não volta em estornos.
- **Liberação:** a parte da arena (e a do organizador) fica "a liberar" até **24h depois do fim do jogo**.
- **Repasse às arenas:** automático, de hora em hora, de todo o saldo liberado. Cada repasse fica registrado com a referência.

---

## 5. Pelada de grupo (C2C)

O mensalista que já tem horário com a arena vende pelo app as vagas que faltam no grupo.

| Regra | Como está |
| --- | --- |
| Quem cria | Qualquer conta de jogador (vira o "organizador") |
| Onde | Numa quadra de arena **parceira**, no horário de mensalista do grupo. Se a arena já cadastrou esse horário, a pelada usa ele; se não, o horário é criado como mensalista confirmado. Recusa horário avulso ou bloqueado e horário em conflito |
| Quando | Até 30 dias à frente, em horário futuro |
| Vagas | Vagas de linha que faltam (1 a 20) e vagas de goleiro (0 a 2) |
| Preço da linha | O organizador define quanto recebe por vaga. **Taxa C2C: 20%, mínimo de R$ 5 por vaga.** Ex.: R$ 15 + R$ 5 = R$ 20. Cartão: +5% |
| Goleiro de aluguel | Preço próprio para o gol, com taxa só percentual (sem o mínimo): R$ 10 + R$ 2 = R$ 12. Ou grátis |
| Quórum | Não há: o grupo joga mesmo sem vender as vagas |
| Nível | O organizador escolhe o nível; vale a mesma trava de nível das partidas |
| O organizador | Não compra vaga na própria pelada |
| Dinheiro | A parte da vaga vai para o **saldo do organizador** (a arena não recebe nada), liberada 24h depois do jogo |
| Saque | Via Pix, de todo o saldo disponível, mínimo de R$ 10, para a chave cadastrada (CPF, celular, e-mail ou aleatória, com validação) |
| Cancelamento | O organizador (ou a arena dona da quadra) cancela e todos são reembolsados. Uma pelada cancelada pode ser reaberta no mesmo horário pelo mesmo organizador |
| Jogador avulso | Mesmas regras de sempre: reserva de 10 min, crédito até 24h antes, repasse |

**Onde aparece:**
- **Feed:** "Pelada de grupo · por Fulano", o nome da pelada e o filtro "Peladas de grupo".
- **Partida:** cartão do organizador.
- **Checkout:** "Para o organizador" no lugar de "Parte da quadra".
- **Agenda da arena:** "Pelada de grupo".
- **Admin:** coluna "Origem".
- **API:** campos `origem` e `organizador`.

---

## 6. Jogadores: perfil, nível, check-in e avaliações

### Perfil

- **Questionário** antes da primeira partida:
  - autoavaliação de 1 a 5;
  - frequência (raramente, mensal, semanal, várias por semana);
  - experiência (nunca jogou em time, amigos/escolinha, amador, federado).
- **Também guarda:** posição (goleiro, defesa, meio, ataque), se "topa jogar no gol", apelido e região.
- **Nível de 1 a 5** (Iniciante, Recreativo, Intermediário, Avançado, Elite) = (2 × autoavaliação + frequência + experiência) ÷ 4, arredondado.
- **Ajuste pela comunidade:** se 3 colegas diferentes sinalizarem, depois de jogos, que o jogador joga acima (ou abaixo) da faixa, o nível sobe (ou desce) 1 ponto. Depois de um ajuste da comunidade, o jogador não pode mais mudar o nível pelo questionário.

### Trava de nível

| Nível da partida | Aceita jogadores de nível |
| --- | --- |
| Aberta a todos | 1 a 5 |
| Iniciante | 1 a 2 |
| Intermediário | 2 a 4 |
| Avançado | 4 a 5 |

A trava cai **1h antes do prazo do mínimo** (padrão: 4h antes do jogo), se ainda houver vaga.

### Goleiro

- A vaga de goleiro é para quem é goleiro ou marcou "topa jogar no gol".
- **Falta sem avisar:** o goleiro perde a vaga grátis por **14 dias**.

### Check-in e confiabilidade

- O comprovante do jogador tem um **QR**. A recepção lê com a câmera e marca a presença.
- A janela de check-in vai de **1h antes do jogo até o fim dele**.
- **Falta:** ao encerrar a partida, se a arena fez check-in de alguém, quem não fez leva falta.
- **Confiabilidade:** % de presença nos jogos com check-in, exibida no perfil.

### Avaliação pós-jogo

- **Quem pode:** quem jogou (sem falta), uma vez, até **7 dias** depois.
- **O que avalia:**
  - o nível da partida (abaixo, na medida ou acima);
  - elogios aos colegas (só positivos): fair play, pontual, bom de passe, artilheiro, paredão, raça;
  - em partidas com faixa de nível, um sinal de que um colega joga acima ou abaixo dela.

### Times sugeridos

- Dois times de força parecida ("Colete laranja" e "Colete azul"), com um goleiro em cada.
- Os mais fortes escolhem primeiro.
- Aparecem no check-in da arena e no comprovante do jogador, quando o jogo está confirmado.

---

## 7. Telas do site e do app do jogador

**Visual (desde 20/10, "ultra-minimalismo"):**
- tema claro: fundo `gray-50`, cartões brancos com borda fina, texto `gray-900`;
- uma cor forte só nos botões de ação: verde bandeira `#00873A`;
- fonte Inter, títulos em extra-negrito;
- botões grandes (`py-4 px-6 text-lg font-bold`, cantos `rounded-2xl`), uma ação principal por tela;
- o secundário fica recolhido em "Mais filtros", "Mais opções", "Quem vai", "Regras" etc.;
- celular primeiro, com barra inferior: Jogos, Minhas, Organizar e Perfil.

| Tela | Endereço | O que tem |
| --- | --- | --- |
| Site | `/` | Apresentação, números ao vivo (partidas, vagas, arenas, jogadores), 3 jogos em destaque, "como funciona" em 3 passos, diferenciais (nível, sem 4 contra 4, lista de espera, login pelo celular) e chamada para arenas |
| Feed | `/app/` | Estilo Uber: uma coluna de cartões com origem, hora e preço grandes, nome, local, vagas e o botão "Garantir vaga" na largura toda no celular. À vista: chips de dia e "Perto de mim" (localização do aparelho, não gravada). Em "Mais filtros": "Meu nível", origem (arenas ou peladas de grupo) e piso. Checkout rápido por cima da lista |
| Partida | `/app/partidas/<id>/` | Dia, horário, vagas, quem vai (linha e gol), mínimo de jogadores, como funciona, local com mapa, preço e ações (garantir vaga, lista de espera, sua inscrição) |
| Checkout | `/app/partidas/<id>/checkout/` | Linha ou goleiro, forma de pagamento com preços e a composição do valor |
| Pagamento Pix | `/app/inscricoes/<id>/pagamento/` | Pix copia e cola, prazo da reserva e "Simular pagamento aprovado" (só com o gateway simulado) |
| Comprovante | `/app/inscricoes/<id>/` | QR do check-in, adicionar ao Google Agenda, como chegar, times sugeridos, cancelar e repassar a vaga |
| Minhas partidas | `/app/minhas-inscricoes/` | Próximos jogos, histórico (com "Avaliar"), crédito e movimentações do crédito |
| Avaliar | `/app/partidas/<id>/avaliar/` | Nível da partida, elogios e sinais de nível dos colegas |
| Perfil | `/app/perfil/` | Nível, jogos, faltas, confiabilidade, crédito e elogios recebidos |
| Configurar perfil | `/app/perfil/configurar/` | Questionário de nível, posição, gol, apelido e região |
| Organizar | `/app/organizar/` | Saldo disponível e a liberar, saque via Pix, chave Pix, próximas peladas e já jogadas (vendidas, você recebe, cancelar vagas) e como funciona |
| Completar pelada | `/app/organizar/nova/` | Passo único: quadra, dia, horário, vagas (−/+) e quanto você recebe, com prévia ao vivo do preço. Nome, término (padrão: 1h depois), nível e goleiro de aluguel em "Mais opções" |
| Entrar pelo celular | `/app/entrar/` → `/app/entrar/codigo/` | Código de 6 dígitos por SMS; cria a conta no primeiro acesso |
| Entrar com senha | `/app/entrar/senha/` | Usuário e senha |
| Cadastro | `/app/cadastro/` | Conta de jogador com usuário e senha |
| Erros | — | Páginas 404 ("Bola fora") e 500 no visual do app |

---

## 8. Portal da arena

**Endereço:** `/manager/`, com o mesmo visual claro.
- **Navegação:** menu lateral no computador e barra inferior no celular.
- **Mais de uma arena:** o gestor (ou um superusuário) troca a arena pelo seletor.

| Tela | O que tem |
| --- | --- |
| **Início** | Só os números do dinheiro: **Saldo a receber** (liberado + a liberar, e quanto já caiu na conta no mês) e **Vendido no mês** (com as vagas vendidas). Embaixo, o botão gigante **Abrir quadra** e uma linha com os horários livres nos próximos 7 dias |
| **Abrir quadra** (`/manager/abrir-quadra/`) | Abas com os próximos 7 dias e os horários livres de cada quadra: um toque **publica a partida na hora** (aluguel sugerido, capacidade, goleiros e nível aberto, com o preço mostrado antes); "Desfazer" enquanto ninguém comprou |
| **Agenda** | Grade semanal por quadra (mensalista, avulso, pelada de grupo, partida aberta, livre e bloqueado, com legenda e contagem). Horário livre: formulário completo (aluguel, vagas, goleiros e nível, com prévia do preço). Partida: vendidas, valor para a quadra e cancelar com reembolso. Pelada de grupo: organizador, vendidas e cancelar |
| **Check-in** | Jogos de hoje com a lista de confirmados, "Marcar presença" e times sugeridos. O QR do comprovante abre a ficha do jogador para confirmar a presença |
| **Financeiro** | Liberado e a liberar à vista; transferido e vendido no mês em "Mês atual". Extrato filtrável (vendas, devoluções, transferências, centavos; período) e histórico de transferências recolhido, em linguagem de dono de quadra |
| **Ajustes** | Quadras (e "Adicionar quadra") e dados da arena, com horário de funcionamento; localização, mínimo de jogadores, prazo e contrato em "Mais opções" |
| Login e acesso | Login próprio do portal. Quem não é gestor vê "Acesso restrito"; gestor sem arena vê "Nenhuma arena vinculada" |

---

## 9. Back-office (Django Admin)

Fica em `/admin/`, para a equipe ArenaMatch. Os gestores entram com permissões limitadas às próprias arenas.

- **Página inicial:** painel com os indicadores da arena.
- **Arenas e quadras:** edição; o gestor não troca o responsável.
- **Agenda:**
  - filtros por período, situação, tipo, arena e quadra;
  - ação **"transformar em partida aberta"** (em lote, com tela de parâmetros);
  - ação "marcar como ocioso".
- **Partidas:**
  - ocupação em tempo real, preço e origem (arena ou pelada);
  - inscrições em linha;
  - ação **"cancelar partidas"** com reembolso.
- **Somente consulta**, porque só o sistema altera: inscrições, pagamentos, carteiras, lançamentos, repasses e saques.
- **Carteiras dos usuários:** chave Pix, saldo de organizador e crédito.
- **Perfis de jogador:** a equipe pode corrigir o nível.
- **Avaliações, elogios e sinais:** consulta e remoção de abusos.
- **Usuários:** papéis de jogador, gestor e equipe.

---

## 10. API REST

**Base:** `/api/`
- **Autenticação:** token (`Authorization: Token <chave>`) ou sessão.
- **Listas:** paginadas, 20 por página.
- **Erros de regra:** HTTP 400 com a mensagem.

| Método | Rota | O que faz |
| --- | --- | --- |
| GET | `/api/` | Índice navegável |
| GET | `/api/partidas/` | Feed (abertas e lotadas, futuras). Filtros: `nivel`, `piso`, `arena`, `origem` (`arena`/`pelada`), `data`, `de`, `ate`. Traz `origem`, `titulo`, `organizador` e preços de linha e goleiro (Pix e cartão) |
| GET | `/api/partidas/{id}/` | Detalhe com jogadores |
| POST | `/api/partidas/{id}/inscricoes/` | Checkout (`posicao`, `metodo_pagamento`) |
| POST, DELETE | `/api/partidas/{id}/lista-de-espera/` | Entrar e sair da lista |
| GET | `/api/minhas-inscricoes/` | Inscrições do jogador |
| GET, DELETE | `/api/minhas-inscricoes/{id}/` | Detalhar e cancelar |
| POST | `/api/minhas-inscricoes/{id}/repassar/` | Repassar vaga |
| POST | `/api/minhas-inscricoes/{id}/simular-pagamento/` | Aprovar Pix (só simulado) |
| GET | `/api/carteira/` | Crédito e movimentações |
| GET | `/api/arenas/` | Arenas e quadras |
| GET, POST | `/api/peladas/` | Peladas que o jogador organiza (vendidas, quanto recebe, se pode cancelar); o POST publica as vagas com o mínimo (quadra, dia, horário, vagas, valor) e aplica os padrões do site |
| POST | `/api/peladas/{id}/cancelar/` | Cancelar as vagas e reembolsar quem comprou |
| GET | `/api/organizador/carteira/` | Saldo disponível e a liberar, sacado, mínimo de saque, chave Pix, últimos saques e movimentações |
| PUT | `/api/organizador/chave-pix/` | Cadastrar ou trocar a chave Pix (mesma validação do site) |
| POST | `/api/organizador/saques/` | Sacar todo o disponível via Pix |
| POST | `/api/auth/celular/` | Login pelo celular, passo 1: envia o código (em `DEBUG`, devolve o código) |
| POST | `/api/auth/celular/verificar/` | Passo 2: código → token; cria o jogador no primeiro acesso e avisa se falta o questionário |
| POST | `/api/auth/cadastro/` | Criar conta de jogador e devolver o token |
| POST | `/api/auth/token/` | Usuário e senha → token |
| GET | `/api/me/` | Usuário logado |
| GET, PUT | `/api/perfil-jogador/` | Perfil e questionário de nível |

---

### App Flutter (`mobile_app/`)

Projeto criado com `flutter create` (Android, iOS e web), Flutter 3.47.6 e Dart 3.13.5.

| Parte | O que tem |
| --- | --- |
| Abas | `BottomNavigationBar` com **Jogos** (feed com "Garantir vaga" e Pix copia e cola), **Minhas Peladas** (completar pelada em passo único, saldo, chave Pix, saque e cancelar vagas) e **Perfil** (nível, próximos jogos, questionário e sair) |
| Login | Celular + código por SMS, token salvo no aparelho (`shared_preferences`) |
| Design | `lib/tema.dart` com os mesmos tokens do site (gray-50, branco, gray-900, verde bandeira) e botões de 56 px |
| API | `lib/api/`: cliente HTTP com token e leitura dos erros do DRF; um método por endpoint. Endereço por `--dart-define=API_URL=...` (padrão: produção) |
| Testes | 14 testes (modelos, cliente HTTP com `MockClient`, formatação e telas); `flutter analyze` sem avisos |
| Ainda não | rodado num aparelho ou emulador (a máquina não tem Android SDK; iOS exige Mac), QR de check-in, cartão de crédito, lista de espera, avaliação e push |

---

## 11. Rotinas automáticas

O agendador (APScheduler) roda num processo próprio; em produção, junto do site.
Todas as rotinas são **idempotentes**: rodar atrasado ou duas vezes não duplica nada.

| Rotina | A cada | O que faz |
| --- | --- | --- |
| Expirar reservas | 1 min | Devolve as vagas reservadas e não pagas em 10 min |
| Conferir quórum | 5 min | No prazo, confirma o jogo ou cancela e reembolsa |
| Finalizar partidas | 15 min | Encerra jogos terminados, marca faltas e credita os centavos do rateio |
| Gerar repasses | 60 min | Transfere às arenas o saldo liberado |
| Limpar sessões | 1 dia | Apaga logins expirados |

---

## 12. Avisos por e-mail

Os e-mails saem só depois que a operação é gravada no banco:

- inscrição confirmada;
- vaga aberta (lista de espera);
- partida cancelada;
- vaga repassada;
- pagamento devolvido.

> Hoje os e-mails vão **para o log**, não para a caixa de entrada: não há
> servidor de e-mail (SMTP) configurado, nem em produção.

---

## 13. Segurança

- **Segredos fora do código:** a chave do Django, a senha do banco e a senha das contas de demonstração vêm de variáveis de ambiente. O `.env` e o arquivo local de acessos não vão para o GitHub (o repositório é público).
- **HTTPS:** cookies seguros, HSTS, `nosniff` e política de referrer em produção. CSRF validado atrás do proxy HTTPS.
- **Login pelo celular:**
  - só o hash do código fica no banco;
  - o código vale 10 min, com 5 tentativas;
  - até 3 códigos a cada 15 min por número;
  - tentativa errada é registrada mesmo quando a operação falha.
- **Dinheiro:**
  - lançamentos imutáveis;
  - última vaga protegida contra compra simultânea;
  - notificações repetidas do gateway não duplicam pagamento;
  - valores congelados na inscrição.
- **Gateway simulado:** só roda onde é explicitamente permitido.
- **Escopo do gestor:** cada gestor só vê e altera as próprias arenas (portal e admin).
- **Ferramentas baixadas:** Tailwind e CLI do Railway são conferidos por SHA-256 antes de rodar.
- **Container:** o processo em produção não roda como root.

---

## 14. Banco de dados

PostgreSQL (18 local e em produção), 8 migrações.

| Modelo | Para que serve |
| --- | --- |
| `CustomUser` | Usuário (jogador, gestor, equipe), telefone e CPF |
| `Arena`, `Court` | Arena (com contrato) e quadras |
| `TimeSlot` | Horário da agenda de uma quadra |
| `OpenMatch` | Partida aberta ou pelada de grupo (organizador, nome, preço do goleiro) |
| `Booking` | Inscrição (vaga) com valores congelados, check-in e falta |
| `WaitlistEntry` | Lista de espera |
| `PlayerProfile` | Perfil, nível e suspensão de goleiro |
| `AvaliacaoPartida`, `Elogio`, `SinalNivel` | Avaliações pós-jogo |
| `CodigoAcesso` | Códigos do login pelo celular (hash) |
| `Payment` | Cobrança no gateway (ou crédito) |
| `LedgerAccount`, `LedgerEntry` | Razão contábil: carteiras e lançamentos |
| `Payout` | Repasse a uma arena |
| `Wallet`, `Saque` | Chave Pix do usuário e saques do organizador |

---

## 15. Dados de demonstração

O comando `populate_db` **apaga tudo** e recria uma demonstração realista. Ele
"volta no tempo" e passa por todas as regras do sistema, como se tudo tivesse
acontecido de verdade.

- **3 arenas com 8 quadras:**
  - Arena Gol de Placa (São Paulo);
  - Complexo Esportivo Tabelinha (Belo Horizonte);
  - Arena Pé na Areia (Rio de Janeiro, com CNPJ alfanumérico).
- **45 usuários:** 1 superusuário, 3 gestores e 41 jogadores (entre eles o Jogador Demo).
- **Agenda de 7 dias à frente e 6 dias de histórico,** com cerca de 70 partidas:
  - lotadas, finalizadas, uma cancelada por quórum e uma pela arena;
  - **20 partidas abertas** de arenas no futuro;
  - 9 peladas de grupo (3 já jogadas e 6 futuras, com goleiro grátis e de aluguel).
- **Histórico:** pagamentos, cancelamentos com crédito, check-ins com faltas, avaliações, ajuste de nível pela comunidade, repasses e um saque de organizador.
- **Jogador Demo:**
  - tem crédito e jogos para avaliar;
  - organiza peladas, com saldo disponível para sacar.
- **Opção `--se-vazio`:** só popula se o banco estiver vazio. Em servidor público, exige uma senha forte (`ARENAMATCH_SENHA_DEMO`) para todas as contas.

**Acessos locais:**

| Conta | Senha |
| --- | --- |
| `admin` | `admin123` |
| `carlos.andrade`, `fernanda.lima`, `rafael.souza` | `gestor123` |
| `jogador` (Demo) e demais jogadores | `jogador123` |
| Celular `(11) 90000-0001` | Código exibido na tela (só em desenvolvimento) |

**Em produção:** mesmos logins, com a senha da variável `ARENAMATCH_SENHA_DEMO`.
Ela também está no arquivo local `acessos-producao.local.txt`.

> **Situação em 19/10:** a produção ainda tem os dados de 17/10 (sem peladas de
> grupo; as partidas das arenas vão até 23/10). Para atualizar, rode o comando
> indicado no `RELATORIO_MADRUGADA.md`.

---

## 16. Infraestrutura e deploy

| Item | O que é |
| --- | --- |
| Linguagem e framework | Python (3.15 local, 3.14 em produção), Django 5.2 LTS, Django REST Framework 3.18 |
| Banco | PostgreSQL 18 (driver psycopg 3), configurado por `DATABASE_URL` |
| Agendador | APScheduler 3.11 |
| Visual | Templates Django + Tailwind CSS 4.3.3 compilado (sem Node), fonte Inter, tema claro |
| App mobile | Flutter 3.47.6 (Dart 3.13.5), pacotes `http` e `shared_preferences` |
| Servidor | gunicorn 26 + WhiteNoise 6 (CSS e estáticos comprimidos, com hash e cache longo) |
| **Produção** | **Railway**: serviço web + PostgreSQL, região Virginia (EUA), domínio `arenamatch-production.up.railway.app`, build pelo `Dockerfile`. O `start.sh` roda migrações, demonstração (se vazio), agendador e gunicorn |
| Conta Railway | Período de teste: US$ 5 de crédito e 30 dias a partir de 17/10 (até ~16/11), sem cartão |
| Alternativa pronta | Render (`render.yaml` + `build.sh`), não usada |
| Código | GitHub `pedromariano25/ArenaMatch` (público), branch `main` |

---

## 17. Qualidade e testes

- **203 testes automatizados no Django** passando, em 14 arquivos:
  - modelos (34), checkout (23), pelada de grupo (23), portal (22), jogadores (17);
  - app (15), API (14), API do app (9), admin (11), site (11), dados de demonstração (9);
  - partidas (6), deploy (5), agendador (4).
- **14 testes no app Flutter** e `flutter analyze` sem avisos.
- **Verificação de código:** `ruff` sem erros nas regras do projeto. Sem migrações pendentes.
- **Revisão visual:** capturas de todas as telas em 390 px (celular) e 1280 px (desktop), sem rolagem horizontal.
- **Conciliação do razão nos dados de demonstração:**
  - cada arena bate com as próprias vendas;
  - cada organizador fecha em vendas menos saques.

---

## 18. Configuração (variáveis de ambiente)

| Variável | Para que serve |
| --- | --- |
| `DJANGO_SECRET_KEY` | Chave criptográfica (obrigatória) |
| `DATABASE_URL` | Conexão com o PostgreSQL (obrigatória) |
| `DJANGO_DEBUG` | Modo de desenvolvimento (padrão: desligado) |
| `DJANGO_ALLOWED_HOSTS` | Hosts aceitos (padrão: qualquer um) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Origens extras para formulários |
| `DJANGO_SECURE_HSTS_SECONDS` | Duração do HSTS (padrão: 1 hora) |
| `DJANGO_LOG_LEVEL` | Nível do log |
| `DJANGO_EMAIL_BACKEND`, `DJANGO_DEFAULT_FROM_EMAIL` | E-mail (padrão: console) |
| `ARENAMATCH_GATEWAY_PAGAMENTO` | Classe do gateway (padrão: simulado) |
| `ARENAMATCH_PERMITIR_GATEWAY_SIMULADO` | Libera o gateway simulado |
| `ARENAMATCH_SMS_BACKEND` | Envio do código por SMS (padrão: só log) |
| `ARENAMATCH_URL_BASE` | Endereço público nos e-mails (detecta Render e Railway) |
| `ARENAMATCH_POPULAR_DEMO`, `ARENAMATCH_SENHA_DEMO` | Demonstração num servidor novo |
| `ARENAMATCH_MIGRAR_AO_INICIAR`, `ARENAMATCH_AGENDADOR_NO_WEB` | Comportamento do `start.sh` |
| `WEB_CONCURRENCY`, `PORT` | Processos e porta do gunicorn |
| `ARENAMATCH_CACHE_DIR` | Onde guardar o executável do Tailwind |

---

## 19. O que é simulado

| Parte | Hoje | Para ficar real |
| --- | --- | --- |
| **Pagamentos** | Gateway simulado: Pix com "copia e cola" de mentira, cartão aprovado na hora, estornos, repasses e saques só no nosso banco. **Nenhum dinheiro real se move**, nem em produção | Contratar um gateway com split (Mercado Pago, Pagar.me ou Asaas) e implementar a interface `Gateway` (cobrança, estorno, transferência, Pix e webhook com assinatura) |
| **SMS** | O código vai para o log (e para a tela, em desenvolvimento) | Contratar um provedor de SMS |
| **E-mail** | Vai para o log | Configurar SMTP |

---

## 20. O que não existe (ainda)

**Para cobrar de verdade:**
- gateway real com split, inclusive o pagamento aos organizadores;
- validação jurídica e contábil:
  - crédito não sacável e direito de arrependimento (CDC);
  - guarda do dinheiro de arenas e organizadores;
  - notas fiscais;
  - KYC dos organizadores;
- política de privacidade e termos de uso (LGPD).

**Produto:**
- confirmação da arena para peladas de grupo (hoje qualquer jogador declara o horário; a arena só vê e pode cancelar);
- notificações push e central de avisos no app;
- login com Google;
- convites com bônus, conquistas e jogo fixo semanal (estão numa branch, veja abaixo);
- mensalidade ou plano pago para as arenas (o único modelo de receita é a taxa por vaga);
- pagamento ao goleiro de aluguel (hoje o goleiro paga menos ou nada; o grupo não paga o goleiro pelo app).

**App:**
- app Flutter publicado nas lojas (o projeto existe, mas ainda não rodou num aparelho) e PWA instalável;
- no app, faltam: QR de check-in, cartão de crédito, lista de espera, avaliação pós-jogo e push;
- na API, faltam:
  - avaliação pós-jogo;
  - "perto de mim" (ordenar por distância);
  - registro de aparelho para push;
  - documentação OpenAPI;
  - CORS (só necessário para rodar o app Flutter no navegador).

**Operação:**
- domínio próprio;
- `ALLOWED_HOSTS` restrito;
- plano pago no Railway antes do fim do teste;
- agendador num serviço separado;
- monitoramento e alertas de erro;
- limite de SMS por IP.

---

## 21. Trabalho guardado fora da `main`

A branch `wip/fase4-retencao` tem modelos e regras (sem telas nem testes) para:

- central de avisos, com lembretes do jogo e alerta de "faltam X para fechar";
- convites pelo WhatsApp com bônus de crédito para quem convida;
- sequência semanal e conquistas;
- jogo fixo semanal da arena;
- endpoint de saúde e índices extras no banco.

Foi pausada para priorizar a pelada de grupo e **não está no ar**.
