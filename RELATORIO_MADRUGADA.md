# Relatório · ArenaMatch no ar e pelada de grupo (C2C)

**Período:** 17 a 19/10/2026 · relatórios anteriores em [`docs/`](docs/)

## Resumo

- **O ArenaMatch está no ar:** <https://arenamatch-production.up.railway.app>
  (Railway, com PostgreSQL 18, HTTPS e o agendador rodando junto).
- **Fase 3 conferida:** site, app do jogador e portal da arena estão completos no
  visual escuro e neon. Revisei todas as telas em 390 px e 1280 px, sem rolagem
  horizontal. As que mudaram nesta rodada foram feed, partida, checkout e agenda
  da arena, além das telas novas do organizador.
- **Fase 4 · Pelada de grupo (C2C):** o mensalista vende pelo app as vagas que
  faltam no grupo. Inclui goleiro de aluguel, divisão do pagamento no razão,
  carteira do organizador com saque via Pix e diferenciação visual no feed.
- **Qualidade:** 193 testes automatizados passando (eram 169), 24 deles novos para o C2C.
- **Pendente:** recriar os dados de demonstração **em produção**. O comando foi
  bloqueado pelo controle de segurança do Claude Code e precisa de você (veja abaixo).

> O trabalho de retenção que eu tinha começado antes desta rodada (avisos,
> convites com bônus, conquistas e jogo fixo) ficou guardado na branch
> `wip/fase4-retencao`, fora da `main`. Não foi publicado.

---

## Como acessar

| Endereço | O que é |
| --- | --- |
| <https://arenamatch-production.up.railway.app/> | Site |
| <https://arenamatch-production.up.railway.app/app/> | App do jogador |
| <https://arenamatch-production.up.railway.app/app/organizar/> | Organizar (pelada de grupo) |
| <https://arenamatch-production.up.railway.app/manager/> | Portal da arena |
| <https://arenamatch-production.up.railway.app/admin/> | Back-office |

| Perfil | Login | Onde entrar |
| --- | --- | --- |
| Jogador Demo (também organiza peladas) | `jogador` | `/app/entrar/senha/` |
| Gestores das 3 arenas | `carlos.andrade`, `fernanda.lima`, `rafael.souza` | `/manager/` |
| Superusuário | `admin` | `/admin/` |

**A senha é a mesma para todas as contas.** Ela não está neste arquivo, porque o
repositório é público. Está:

- no arquivo `acessos-producao.local.txt`, na pasta do projeto (ignorado pelo Git);
- nas variáveis do serviço no Railway (`ARENAMATCH_SENHA_DEMO`).

Em produção o login pelo celular não mostra o código na tela, então use o login com senha.

### Falta um passo seu: recriar a demonstração em produção

O banco de produção ainda tem os dados de 17/10: partidas das arenas até 23/10 e
nenhuma pelada de grupo. Para recriar tudo, com as peladas de grupo e o goleiro de
aluguel, rode no PowerShell, na pasta do projeto (apaga e recria os dados de teste,
cerca de 1 minuto):

```powershell
& "$env:LOCALAPPDATA\arenamatch\railway-v5.63.4\railway.exe" ssh --service arenamatch -- python manage.py populate_db --force
```

A senha das contas não muda. Também dá para testar sem isso: entre como `jogador`,
vá em **Organizar > Completar uma pelada** e crie uma.

---

## Fase 4 · Pelada de grupo (C2C)

### Como funciona

1. **O organizador** (mensalista) abre em **Organizar > Completar uma pelada**:
   - o nome da pelada, a quadra parceira, o dia e o horário que o grupo já tem;
   - quantas vagas faltam e quanto quer receber por vaga.
2. **O avulso** vê a pelada no feed (destaque magenta, com o organizador) e paga pelo app.
3. **A divisão:** a taxa fica com o ArenaMatch, e o valor da vaga vai para a
   carteira do organizador. Ele saca via Pix depois, para abater a quadra.

| Exemplo (o seu) | Valor |
| --- | --- |
| O organizador recebe por vaga | R$ 15,00 |
| Taxa ArenaMatch (20%, mínimo de R$ 5 por vaga) | R$ 5,00 |
| **O avulso paga (Pix)** | **R$ 20,00** |
| No cartão (+5% para a operadora) | R$ 21,00 |

### Goleiro de aluguel

- O organizador pode abrir vagas só para o gol, com preço próprio.
- Ex.: R$ 10 para o grupo + R$ 2 de taxa (só os 20%, sem o mínimo) = **R$ 12**.
- Ou deixa a vaga grátis (o grupo banca).
- O mesmo campo existe nas partidas das arenas, que continuam com goleiro grátis por padrão.

### O dinheiro (razão contábil)

- **Saldo do organizador:** uma carteira nova no razão (`ORGANIZADOR`), separada
  do crédito de jogador (que não é sacável). O valor de cada vaga fica "a liberar"
  até o dia seguinte ao jogo, como já acontece com as arenas.
- **Saque:** via Pix, de todo o disponível (mínimo de R$ 10), para a chave cadastrada.
  - `Wallet` guarda a chave Pix do usuário.
  - `Saque` registra cada transferência.
  - Os saldos continuam vindo do razão, que é a única fonte de verdade.
- **A arena não recebe nada da pelada:** conferi nos dados de demonstração que o
  razão de cada arena continua batendo com as partidas dela e que o saldo de cada
  organizador é igual às vendas menos os saques.

### Onde aparece

| Tela | O que mudou |
| --- | --- |
| Feed | Selo "Arena parceira" ou "Pelada de grupo · por Fulano" (magenta), nome da pelada, "faltam N vagas para completar", filtro por origem |
| Partida | Cartão do organizador; para ele mesmo, "Esta é a sua pelada" e botão de chamar a galera no WhatsApp |
| Checkout | "Para o organizador" no lugar de "Parte da quadra"; preço do goleiro de aluguel |
| Organizar (nova) | Disponível para saque, a liberar, chave Pix, sacar, próximas peladas e já jogadas |
| Completar pelada (nova) | Formulário com prévia ao vivo de quanto o jogador paga e quanto você recebe |
| Agenda da arena | O horário aparece como "Pelada de grupo" (com o organizador) e a arena pode cancelar |
| API | Campos `origem`, `titulo`, `organizador` e preço do goleiro |

---

## Fase 5 · Deploy no Railway

| Item | Situação |
| --- | --- |
| CLI do Railway | v5.63.4, baixada do GitHub com o hash conferido (sem instalar Node) |
| Login | Você autorizou no navegador em 17/10; continua válido |
| Projeto | `arenamatch`: serviço web e PostgreSQL 18, região Virginia (EUA) |
| Build | `Dockerfile` (Python 3.14). Escolhi o Dockerfile porque o `railway.json` deixa de ser lido em 01/12/2026 e o formato novo do Railway ainda é beta em Python |
| Subida | `start.sh`: migrações, demonstração (só com banco vazio), agendador e gunicorn |
| Domínio | <https://arenamatch-production.up.railway.app> (porta 8080) |
| Versão no ar | `846d6a7` (pelada de grupo), publicada em 19/10 |

**Custo:** a conta está no período de teste, com US$ 5 de crédito e 30 dias a
partir de 17/10, sem cartão cadastrado. Até 19/10 foram usados US$ 0,19. Quando o
crédito ou o prazo acabar, o site para. Para continuar, é preciso assinar um plano
pago no painel do Railway (confira o preço atual lá).

### O que travou no caminho

- **Porta:** no primeiro deploy, o app subiu na porta 8080 e o domínio apontava
  para a 8000 (erro 502). O classificador de segurança bloqueou o *redeploy*, então
  ajustei o domínio para a 8080, sem novo deploy.
- **Dados de produção:** a recriação pelo `railway ssh` foi bloqueada pelo mesmo
  controle ("escrita por shell remoto"). Não contornei; o comando está acima.

---

## Decisões que tomei sozinho (vale revisar)

| Tema | O que fiz | Por quê |
| --- | --- | --- |
| **Onde a pelada acontece** | Só em **quadras parceiras**, no horário de mensalista do grupo | Mantém mapa, "perto de mim", check-in e agenda da arena. A arena vê o horário como "Pelada de grupo" |
| **Quem pode declarar o horário** | Qualquer jogador; se a arena já cadastrou aquele mensalista, a pelada usa o horário dela | **Risco:** alguém pode inventar uma pelada numa quadra parceira. Mitigação de hoje: a arena vê e pode cancelar (com reembolso). Próximo passo: a arena confirma a pelada com um toque |
| **Taxa C2C** | 20% sobre o valor do organizador, mínimo de R$ 5 por vaga de linha | Reproduz o seu exemplo (R$ 15 + R$ 5 = R$ 20). As constantes ficam no topo de `models.py` |
| **Goleiro de aluguel** | Preço próprio, só com a taxa percentual (sem o mínimo) | "Subsidiado": goleiro mais barato que a linha. Pagar o goleiro (dinheiro do grupo para ele) exigiria o organizador pagar antes; ficou para depois |
| **Quórum** | Pelada de grupo nunca é cancelada por falta de jogadores | O grupo joga de qualquer jeito |
| **Liberação e saque** | Valor libera no dia seguinte ao jogo; saque manual de todo o disponível, mínimo de R$ 10 | Igual à arena (dá tempo de tratar reclamação) e evita transferências pequenas |
| **`Wallet`** | Guarda a chave Pix; os saldos vêm do razão | Um saldo gravado na carteira seria uma segunda fonte de verdade e poderia divergir dos lançamentos |
| **Organizador** | Não pode comprar vaga na própria pelada | Ele já está no grupo |

## Pontos de atenção antes de cobrar de verdade

1. **Nenhum dinheiro real se move:** o gateway segue simulado, inclusive os saques via Pix.
2. **Pagar pessoas físicas (organizadores) pede validação jurídica e fiscal:**
   - KYC (CPF do titular da chave Pix);
   - split no gateway, para o ArenaMatch não guardar o dinheiro;
   - como o organizador declara o que recebe.

   Some isso à lista do relatório de 14/10 (crédito não sacável, notas fiscais e LGPD).
3. **Confirmação da arena** para peladas de grupo nas quadras dela (risco acima).
4. **Plano do Railway** antes de 16/11 (fim do teste).

## Verificação

- 193 testes automatizados passando, 24 deles novos para o C2C. Cobrem:
  - preço e taxa mínima;
  - divisão no razão (organizador, plataforma e arena intocada);
  - goleiro pago e goleiro grátis;
  - quórum;
  - horário de mensalista;
  - cancelamento e reabertura;
  - saque (chave, mínimo e liberação);
  - agenda e números da arena;
  - telas do organizador;
  - feed com filtro por origem;
  - API.
- Conciliação do razão nos dados de demonstração.
- Em produção:
  - a migração foi aplicada;
  - as telas novas respondem;
  - o login passa pelo HTTPS do Railway;
  - o feed mostra as 14 partidas das arenas como "Arena parceira".

## Commits

```text
b77f8f7 feat(deploy): Railway com Dockerfile e migrações na subida
846d6a7 feat(c2c): pelada de grupo, goleiro de aluguel e carteira do organizador
        docs: relatório (Railway e pelada de grupo)
```
