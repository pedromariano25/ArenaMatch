# ArenaMatch · app (Flutter)

App do jogador para Android e iOS. Ele fala com a API Django do projeto (`/api/`).

## Abas

| Aba | O que tem | Endpoints |
| --- | --- | --- |
| **Jogos** | Feed estilo Uber (hora e preço grandes, um botão "Garantir vaga"), filtros Todos / Hoje / Amanhã / Peladas de grupo | `GET partidas/`, `POST partidas/{id}/inscricoes/` |
| **Minhas Peladas** | Pelada de grupo (C2C): "Completar uma pelada" num passo só (quadra, dia, horário, vagas, valor), saldo, saque via Pix, cancelar vagas | `GET/POST peladas/`, `POST peladas/{id}/cancelar/`, `GET organizador/carteira/`, `PUT organizador/chave-pix/`, `POST organizador/saques/`, `GET arenas/` |
| **Perfil** | Nível, próximos jogos, questionário de nível e sair | `GET me/`, `PUT perfil-jogador/`, `GET minhas-inscricoes/` |

O login é só pelo celular: o app pede um código por SMS (`POST auth/celular/`) e troca o código pelo token (`POST auth/celular/verificar/`). No primeiro acesso, a conta de jogador é criada. O token fica salvo no aparelho (`shared_preferences`) e vai no cabeçalho `Authorization: Token …`.

## Como rodar

O SDK precisa ser o Flutter 3.47 ou mais novo (Dart 3.13). Para rodar no Android, instale o Android Studio (que traz o Android SDK). Para o iOS, é preciso um Mac com Xcode.

```bash
cd mobile_app
flutter pub get
flutter analyze
flutter test

# Contra a produção (padrão)
flutter run

# Contra o Django local
flutter run --dart-define=API_URL=http://10.0.2.2:8000/api/    # emulador Android
flutter run --dart-define=API_URL=http://127.0.0.1:8000/api/   # simulador iOS
```

Com o Django local em `DEBUG`, a resposta do pedido de código traz o próprio código. Assim, a tela de login mostra o código e não é preciso SMS de verdade.

> O Django local só aceita o emulador se `10.0.2.2` estiver em `DJANGO_ALLOWED_HOSTS`.

## Estrutura

```
lib/
  main.dart                  abre a sessão salva e sobe o app
  app.dart                   MaterialApp (tema, pt-BR) e as 3 abas (BottomNavigationBar)
  tema.dart                  design system: cores, botões grandes, cartões, campos
  config.dart                API_URL (--dart-define) e a taxa da pelada (só para a prévia)
  formato.dart               R$, datas ("Hoje", "Amanhã"), prévia do preço da pelada
  api/
    cliente_api.dart         HTTP + token + ApiErro (lê os erros do DRF)
    arenamatch_api.dart      um método por endpoint usado pelo app
    sessao.dart              token no aparelho, usuário logado (InheritedNotifier)
  modelos/                   Partida, PeladaDoOrganizador, Inscricao, Carteira, Usuario, Quadra
  telas/                     jogos, garantir vaga, entrar, questionário, peladas, nova pelada, perfil
  widgets/                   cartão de partida e peças comuns (título, cartão, opção, vazio)
test/                        modelos, cliente HTTP (MockClient), formatação e telas
```

## Design

Usa o mesmo sistema do site: fundo `#F9FAFB` (gray-50), cartões brancos com borda `#E5E7EB` e texto `#111827`. O verde bandeira `#00873A` aparece só nos botões de ação. Os botões têm 56 px de altura, texto 18 em negrito e cantos de 16. Cada tela tem uma ação principal, e o que é secundário fica recolhido em "Mais opções".
