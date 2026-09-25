# SalaVip — Chat

No ar em **https://chat.salavip.live**.


Chat em tempo real com **Mural de Recados** (só Admins escrevem), conversas
**privadas** e **salas com senha** que expiram em 24h, contatos fixados, busca,
anti-flood e comandos de admin. Pode ser **instalado como app** (PWA) e manda
**notificações** com o app fechado. Versão para rodar em container (Easypanel),
com página e WebSocket na **mesma porta** e banco **PostgreSQL** externo
(Supabase, Neon etc.).

## Stack

- Python 3.13 + [aiohttp](https://docs.aiohttp.org/) (HTTP + WebSocket)
- PostgreSQL via [asyncpg](https://magicstack.github.io/asyncpg/)
- Frontend sem dependências: `static/index.html`

## Rotas

| Rota | Descrição |
|---|---|
| `GET /` | Página do chat |
| `GET /ws` | WebSocket (autenticado pelo cookie de sessão) |
| `POST /api/entrar` | Login — cria a conta se o nome ainda não existir |
| `POST /api/sair` | Encerra a sessão |
| `GET /health` | Healthcheck (testa o banco) |
| `GET /manifest.webmanifest`, `GET /sw.js`, `/icones/*` | App instalável (PWA) e service worker |
| `GET /api/push/chave` | Chave pública VAPID |
| `POST /api/push/inscrever` / `POST /api/push/cancelar` | Liga/desliga as notificações do aparelho |
| `POST /api/audio?para=Nome&duracao=ms` | Envia áudio (sem `para` = Mural, só Admins) |
| `GET /api/audio/{id}` | Toca o áudio (privado: só quem recebeu, uma vez) |
| `GET /api/tela` | Imagem da Tela de Pixels (1 byte por pixel, comprimida) |

## Variáveis de ambiente

| Nome | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| `DATABASE_URL` | sim | — | Connection string do PostgreSQL |
| `ADMIN_PASSWORD` | não | vazio | Senha dos comandos `/admin`. Vazia = ninguém vira admin |
| `PORT` | não | `8080` | Porta HTTP/WebSocket |
| `ADMIN_RESET_MINUTES` | não | `60` | Minutos offline antes de permitir `/admin reset` |
| `SESSION_DAYS` | não | `30` | Validade da sessão (cookie) |
| `PRIVATE_TTL_HOURS` | não | `24` | Horas até mensagens privadas e de salas serem apagadas |
| `TIMEZONE` | não | `America/Sao_Paulo` | Fuso usado para contar os avisos de flood "do dia" |
| `VAPID_PRIVATE_KEY` | não | gerada | Chave do push. Se vazia, o chat gera uma e guarda no banco (tabela `config`) |
| `VAPID_SUBJECT` | não | `mailto:admin@example.com` | Contato enviado aos serviços de push. Use um e-mail seu (`mailto:...`) |
| `TRUSTED_IP_HEADER` | não | vazio | Cabeçalho com o IP real do visitante quando há proxy na frente. Com Cloudflare: `CF-Connecting-IP` |
| `LOG_LEVEL` | não | `INFO` | Nível de log (saída no stdout) |

Veja `.env.example`.

## Banco no Supabase (grátis)

1. Crie um projeto em [supabase.com](https://supabase.com).
2. Em **Connect** (ou *Project Settings → Database*), copie a connection string
   do **Transaction pooler** (porta `6543`). Ela funciona em IPv4, a conexão
   direta (porta 5432) do Supabase é só IPv6.
3. Substitua `[YOUR-PASSWORD]` pela senha do banco e use como `DATABASE_URL`.

As tabelas são criadas automaticamente na primeira execução. Qualquer outro
PostgreSQL funciona do mesmo jeito (Neon, Postgres do próprio Easypanel...).

**Segurança no Supabase:** o chat liga o **RLS (Row Level Security)** em todas
as tabelas, sem políticas. Isso bloqueia a API REST pública do Supabase (quem
tiver a `anon key` não lê nem altera nada), e o chat continua funcionando
porque conecta como dono das tabelas. No painel as tabelas deixam de aparecer
como *Unrestricted*. O chat **não usa** a `anon key` nem a `service_role key`,
então não cadastre essas chaves no Easypanel.

## Deploy no Easypanel

1. **Create Service → App**.
2. **Source → GitHub**: repositório `zulatonet/general`, branch `main`,
   **Build Path** `/chat_simples`.
3. **Build → Dockerfile** (arquivo `Dockerfile`).
4. **Environment**: cadastre `DATABASE_URL` e `ADMIN_PASSWORD`.
5. **Domains**: adicione o domínio apontando para a porta **8080**. O HTTPS e o
   WebSocket (`wss://`) passam pelo proxy do Easypanel sem configuração extra.
6. **Deploy**.

> Mantenha **1 réplica**: a lista de quem está online fica em memória.

## Rodar localmente

```bash
cd chat_simples
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql://usuario:senha@localhost:5432/chat"
export ADMIN_PASSWORD="minha-senha"
python chat.py        # http://localhost:8080
```

## Contas e sessões

- Na primeira entrada a pessoa escolhe **nome + senha**, e a conta é criada na hora.
  Depois, o nome só pode ser usado com a senha certa.
- Nome: 2 a 20 caracteres (letras, números, `.`, `-`, `_`), sem espaços.
  Maiúsculas/minúsculas não diferenciam (`Ana` = `ana`).
- Senha: mínimo 6 caracteres, guardada com hash `scrypt`.
- A sessão fica num cookie `HttpOnly` válido por `SESSION_DAYS` dias.
- Esqueceu a senha? O admin redefine com `/senha Usuario NovaSenha`.

## App e notificações (PWA + Web Push)

O chat funciona como app instalável, sem loja: ícone na tela inicial, tela
cheia e **notificação com som** (o som padrão do aparelho) quando chega
mensagem, mesmo com o app fechado.

**Android (Chrome):**
1. Abra o chat no Chrome e entre na conta.
2. Toque em **🔔 Ativar notificações** no aviso do topo e permita.
3. Toque em **📲 Instalar app** (ou no menu ⋮ → *Instalar app*).

**iPhone (iOS 16.4 ou mais novo):**
1. Abra o chat no **Safari**, toque em **Compartilhar ⬆️** → **Adicionar à Tela de Início**.
2. Abra o chat pelo ícone novo, entre e toque em **🔔 Ativar notificações**.

> No iPhone, notificação só funciona com o app adicionado à tela inicial
> (limitação da Apple).

**Quando chega notificação:**
- Mensagem privada, mensagem de sala (para os membros), recado no Mural e
  quando alguém coloca você numa sala.
- O servidor manda para **todos** os aparelhos da pessoa, e cada aparelho
  decide: se o chat está aberto na tela dele, não mostra (a página já toca o
  som); se não, mostra. Assim, com o chat aberto no computador, o celular
  continua avisando.
- **Android:** se o app for "morto" (deslizado para fora dos recentes), muitos
  celulares forçam a parada do Chrome e nada chega até abrir de novo. Libere o
  Chrome e o SalaVip em bateria/início automático (o painel 🔔 Notificações
  explica por marca).
- Várias mensagens da mesma conversa viram uma notificação só, com contador.
- Tocar na notificação abre direto a conversa.
- Ao sair da conta, o aparelho para de receber as notificações dela.

**Prévia do link (WhatsApp, Telegram, Facebook):** a página tem tags Open
Graph com o nome, a descrição e a imagem `static/icones/og-image.jpg`
(1200×630). Os links absolutos usam o domínio de quem acessou, então
funcionam em qualquer domínio apontado para o serviço. O WhatsApp guarda a
prévia em cache: se ela mudar, a nova pode levar um tempo para aparecer.

**Diagnóstico:** na barra lateral, **🔔 Notificações** abre um painel que
mostra a permissão do navegador, se o aparelho está inscrito, quantos
aparelhos a conta tem cadastrados e o último erro. Tem os botões **Testar
agora** (notificação local e push pelo servidor, com a resposta do serviço
de push) e **Testar em 15 s**, para fechar o app e ver se chega com ele
fechado. Cada envio também aparece no log (`push entregue ao serviço ...`).

**Como funciona:** o servidor manda o push para o serviço do navegador
(Google, Mozilla ou Apple), que entrega no aparelho. O conteúdo vai
criptografado de ponta a ponta (RFC 8291) e o servidor se identifica com
VAPID (RFC 8292), implementados em `webpush.py`. Não precisa de Firebase nem
de conta em nenhum serviço. Por segurança, o servidor só envia para os
endereços oficiais desses serviços.

## Tela de Pixels 🎨

É a **página inicial** do chat: uma tela coletiva de **320×180 pixels** onde
todo mundo pinta junto, com paleta de 16 cores.

- **1 pixel a cada 10 segundos por usuário.** Ninguém é dono de pixel: qualquer
  um pinta por cima.
- **Toque/clique** num pixel para escolher (aproxima sozinho se estiver
  pequeno), escolha a cor e aperte **Pintar**. Pintar em dois passos evita
  pintar sem querer enquanto arrasta.
- **Navegação:** arraste para mover; **pinça** (celular), **roda do mouse** ou
  botões ＋ － para zoom; ⤢ mostra a tela inteira.
- Ao escolher um pixel aparece **quem pintou e quando**.
- As mudanças chegam para todos em tempo real, em lotes a cada 0,25 s.
- Embaixo da tela aparece o **último recado do Mural** (toque para abrir o Mural).
- Desenho inicial: "PREENCHA SEUS PIXELS / A CADA 10 SEGUNDOS".
- **Moderação (Admins):** `/tela desfazer Nome [minutos]` volta os pixels de um
  vândalo para as cores de antes; `/tela apagar X Y Largura Altura` pinta de
  branco uma área.
- **Como é guardada:** a imagem inteira (1 byte por pixel, 57,6 KB) fica em
  memória e é salva no banco a cada 5 s e ao desligar. O histórico de quem
  pintou o quê fica 30 dias.

## Regras do chat

### Mural de Recados
- Todo mundo lê; **só Admins e o Master escrevem**.
- Recados do Mural **não expiram**.
- Quem não é admin pode digitar comandos (`/...`) no Mural.

### Mensagens privadas e salas
- Ficam no banco por **`PRIVATE_TTL_HOURS` (24h)** e depois são apagadas
  automaticamente (limpeza a cada 5 minutos). O aviso aparece no topo de
  cada conversa privada e de sala.

### Áudios (até 10 segundos)
- Com a caixa de texto vazia, o botão vira **🎤**: **segure para gravar**,
  **solte para enviar**, **deslize para o lado para cancelar**. Aos 10 s envia
  sozinho; toques de menos de meio segundo são ignorados.
- **Privado:** o áudio é de **ouvir uma vez**. Quem recebe toca e o arquivo é
  apagado do banco na hora; quem enviou vê "✓ enviado" → "✓✓ ouvido" (e
  também não consegue ouvir de novo). Se não for ouvido, some em 24h com a conversa.
- **Mural:** só Admins enviam; o áudio fica guardado e todos podem ouvir
  quantas vezes quiserem.
- **Salas:** não aceitam áudio.
- Os arquivos ficam no **PostgreSQL** (tabela `audios`), não no disco do
  servidor. Em Opus a 32 kbps, 10 s dão uns 40 KB.

### Anti-flood
- Mais de **8 mensagens em 10 segundos** conta **1 aviso** e trava o envio por
  **1 minuto**.
- São **3 avisos por dia** (no fuso `TIMEZONE`). No 4º, o envio fica travado
  por **24 horas**.
- Enquanto travado, a pessoa ainda lê e usa comandos, mas não envia mensagens.
- Um Admin pode destravar com `/liberar Nome`.

### Salas com senha
- Qualquer um cria uma sala (botão **+ Criar**) com nome e senha. Limite de 5
  salas por pessoa. A sala aparece para todos.
- Ao clicar numa sala em que não está, a pessoa vê quem criou e pode:
  - **Entrar com senha**, direto; ou
  - **Solicitar entrada**: o pedido chega no privado do dono.
- O dono aceita com `/aceitar Sala Nome`, em qualquer conversa, ou só com
  `/aceitar Sala` dentro do privado com a pessoa. Também pode incluir alguém
  sem pedido.
- Mensagens da sala só chegam aos membros e também expiram em 24h.

### Contatos e busca
- A barra lateral tem **busca** (pessoas e salas) e três seções: **Salas**,
  **Contatos** (pessoas fixadas com 📌, no topo) e **Todos**.
- Os contatos fixados ficam salvos na conta.
- Sem busca, "Todos" mostra no máximo 200 pessoas (online primeiro); a busca
  encontra qualquer uma.
- No celular a barra lateral abre pelo botão ☰.

## Comandos

Interceptados no servidor e nunca exibidos no chat. Comandos inválidos ou de
quem não tem permissão são ignorados em silêncio. `/help` mostra só os
comandos que a pessoa pode usar.

### Papéis

- **Master** 👑: um só. É quem assumiu com `/admin SENHA`. Pode tudo, inclusive
  promover e revogar Admins.
- **Admin** 🛡️: vários. Modera o chat, mas não pode agir sobre o Master nem
  sobre outros Admins (`/nome`, `/senha`, `/liberar`, `/apagar Usuario`).

| Comando | Quem pode | Efeito |
|---|---|---|
| `/aceitar Sala Nome` | Dono da sala | Coloca Nome na sala (no privado com a pessoa, basta `/aceitar Sala`) |
| `/remover Sala Nome` | Dono da sala ou Admin | Tira Nome da sala |
| `/sairsala Sala` | Membro | Sai da sala (também pelo botão "Sair da sala") |
| `/apagarsala Sala` | Dono da sala ou Admin | Apaga a sala e as mensagens dela |
| `/apagar` (dentro da sala) | Dono da sala ou Admin | Apaga as mensagens da sala |
| `/help` | Todos | Lista os comandos disponíveis para você |
| `/admin SENHA` | Qualquer um (com a senha) | Vira Master, se ainda não houver um |
| `/admin reset SENHA` | Qualquer um (com a senha) | Tira o Master atual (se offline há `ADMIN_RESET_MINUTES`); ele continua Admin |
| `/admin promover Nome` | Master | Torna Nome um Admin |
| `/admin revogar Nome` | Master | Tira o Admin de Nome |
| `/admin transferir Nome` | Master | Passa o Master para Nome (o antigo continua Admin) |
| `/admin lista` | Admin | Mostra o Master e os Admins |
| `/nome Usuario NovoNome` | Admin | Troca o nome de Usuario, mantendo o histórico |
| `/senha Usuario NovaSenha` | Admin | Redefine a senha e derruba as sessões dele |
| `/liberar Usuario` | Admin | Destrava quem foi bloqueado por flood |
| `/tela desfazer Usuario [minutos]` | Admin | Desfaz os pixels de Usuario (padrão: última 1 h) |
| `/tela apagar X Y Largura Altura` | Admin | Pinta de branco uma área da Tela de Pixels |
| `/apagar` | Admin | Apaga a conversa aberta (Mural ou privada) |
| `/apagar Usuario` | Admin | Apaga todas as mensagens de Usuario |
| `/apagar total` | Master | Apaga todas as mensagens (mantém usuários) |

> Ao atualizar de uma versão anterior, o admin existente vira Master
> automaticamente.

## Segurança

### Contra força bruta
| Alvo | Proteção |
|---|---|
| Senha de uma conta | 10 tentativas / 5 min por IP **e** 20 senhas erradas / 15 min por conta (segura botnet com muitos IPs) |
| Senha de admin (`/admin SENHA`) | 5 / 15 min por usuário **e** 20 erros / hora no chat todo: passou disso, a senha de admin para de funcionar por 1 h. Cada erro vai para o log com nome e IP |
| Senha de sala | 5 / 15 min por usuário e 30 erros / hora por sala |
| Criação de contas | 3 contas novas / hora por IP |

> Use uma `ADMIN_PASSWORD` forte (12+ caracteres, letras, números e símbolos).
> O chat avisa no log quando ela é fraca.

### Contra sobrecarga (DoS)
- 120 chamadas / min por IP na API e no WebSocket, e 20 conexões WebSocket novas / min por IP.
- No máximo 5 conexões abertas por conta (abas/aparelhos).
- 20 ações / 10 s por usuário no WebSocket; anti-flood nas mensagens.
- Mensagem de até 2000 caracteres; frame WebSocket de até 16 KB; áudio de até 200 KB.
- Hash de senha (scrypt, ~16 MB cada) limitado a 4 ao mesmo tempo.
- `/health` consulta o banco no máximo a cada 5 s.
- **DDoS de volume** (milhares de máquinas) não se resolve no código: coloque o
  domínio atrás do **Cloudflare** (plano grátis, proxy laranja ligado, WebSocket
  funciona) e cadastre `TRUSTED_IP_HEADER=CF-Connecting-IP` para os limites por
  IP enxergarem o visitante real e não o Cloudflare.

### Contra injeção e manipulação pelo navegador (DevTools)
- Toda regra é conferida no servidor (permissões, salas, Mural, flood). Mexer
  na página não dá poder nenhum.
- SQL sempre parametrizado; conteúdo de usuário exibido com `textContent`
  (sem XSS). Testado com `<img onerror>`, `<script>`, `<svg onload>`.
- CSP com *nonce*: só o script da própria página roda; sem `object`, `base`
  ou formulários para fora. Mais `X-Frame-Options`, `nosniff`, HSTS,
  `Permissions-Policy` (só microfone) e `Cross-Origin-Opener-Policy`.
- Nomes só com letras latinas: impede "clones" como `Аndre` (A cirílico).
- Tipos de cada campo validados; payloads malformados são ignorados.
- Checagem de `Origin` no login, na API e no WebSocket (CSRF / sequestro de WebSocket).
- Áudio: tipo, assinatura do arquivo, tamanho e duração conferidos; nunca é
  servido como HTML.
- Push só para os serviços oficiais dos navegadores (sem SSRF).

### Dados
- Senhas com scrypt; sessões guardadas só como hash; cookie `HttpOnly`,
  `SameSite=Lax` e `Secure`.
- RLS ligado em todas as tabelas (bloqueia a API pública do Supabase).
- Conexão criptografada (SSL) obrigatória com bancos externos, como o Supabase.
- Container roda como usuário sem privilégios.

## Banco de dados

- `usuarios` (id, apelido, senha_hash, is_admin, is_master, avisos_flood, avisos_dia, bloqueado_ate, criado_em, ultimo_acesso)
- `sessoes` (token_hash, usuario_id, criado_em, expira_em)
- `salas` (id, nome, senha_hash, dono_id, criado_em)
- `sala_membros` (sala_id, usuario_id, entrou_em)
- `contatos` (usuario_id, contato_id): pessoas fixadas
- `push_inscricoes` (endpoint, usuario_id, p256dh, auth, criado_em): aparelhos com notificação ligada
- `audios` (id, mensagem_id, mime, dados): arquivos de áudio, apagados junto com a mensagem
- `tela` (id=1, largura, altura, pixels): a Tela de Pixels inteira
- `tela_log` (x, y, cor, usuario_id, criado_em): histórico de pinturas (30 dias)
- `config` (chave, valor): configurações geradas pelo chat (ex.: chave VAPID)
- `mensagens` (id, remetente_id, destinatario_id, sala_id, texto, enviado_em, lida,
  audio_id, audio_duracao_ms, audio_unico, audio_ouvido)
  - Mural: `destinatario_id` e `sala_id` nulos (não expira)
  - Privada: `destinatario_id` preenchido (expira)
  - Sala: `sala_id` preenchido (expira)

## Diferenças para a versão home lab

| Antes | Agora |
|---|---|
| Duas portas (8082 página, 8081 WebSocket) | Uma porta (`/` e `/ws`) |
| SQLite local | PostgreSQL externo (`DATABASE_URL`) |
| `device_id` no navegador, falsificável | Nome + senha, sessão em cookie `HttpOnly` |
| Senha do admin no código (e exibida no chat) | `ADMIN_PASSWORD` no ambiente, nunca exibida |
| Tailscale Funnel / SysV / systemd | Container Docker + proxy do Easypanel |
| Sem reconexão | Reconecta sozinho com backoff |
| Horários no fuso do servidor | Horários no fuso de quem lê |
