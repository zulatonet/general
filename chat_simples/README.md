# Chat — Sala de Bate-Papo

Chat em tempo real com mural **Geral**, conversas **privadas**, notificação de
não lidas e comandos de admin. Versão para rodar em container (Easypanel),
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

## Variáveis de ambiente

| Nome | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| `DATABASE_URL` | sim | — | Connection string do PostgreSQL |
| `ADMIN_PASSWORD` | não | vazio | Senha dos comandos `/admin`. Vazia = ninguém vira admin |
| `PORT` | não | `8080` | Porta HTTP/WebSocket |
| `ADMIN_RESET_MINUTES` | não | `60` | Minutos offline antes de permitir `/admin reset` |
| `SESSION_DAYS` | não | `30` | Validade da sessão (cookie) |
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

## Comandos

Interceptados no servidor e nunca exibidos no chat. Comandos inválidos ou de
quem não tem permissão são ignorados em silêncio.

### Papéis

- **Master** 👑: um só. É quem assumiu com `/admin SENHA`. Pode tudo, inclusive
  promover e revogar Admins.
- **Admin** 🛡️: vários. Modera o chat, mas não pode agir sobre o Master nem
  sobre outros Admins (`/nome`, `/senha`, `/apagar Usuario`).

| Comando | Quem pode | Efeito |
|---|---|---|
| `/admin SENHA` | Qualquer um (com a senha) | Vira Master, se ainda não houver um |
| `/admin reset SENHA` | Qualquer um (com a senha) | Tira o Master atual (se offline há `ADMIN_RESET_MINUTES`); ele continua Admin |
| `/admin promover Nome` | Master | Torna Nome um Admin |
| `/admin revogar Nome` | Master | Tira o Admin de Nome |
| `/admin transferir Nome` | Master | Passa o Master para Nome (o antigo continua Admin) |
| `/admin lista` | Admin | Mostra o Master e os Admins |
| `/nome Usuario NovoNome` | Admin | Troca o nome de Usuario, mantendo o histórico |
| `/senha Usuario NovaSenha` | Admin | Redefine a senha e derruba as sessões dele |
| `/apagar` | Admin | Apaga a conversa aberta (Geral ou privada) |
| `/apagar Usuario` | Admin | Apaga todas as mensagens de Usuario |
| `/apagar total` | Master | Apaga todas as mensagens (mantém usuários) |
| `/help` | Admin | Lista os comandos (o Master vê também os dele) |

> Ao atualizar de uma versão anterior, o admin existente vira Master
> automaticamente.

## Proteções

- Mensagens ligadas ao **ID** do usuário, e não ao apelido: ninguém herda
  conversas de outra pessoa.
- Rate limiting: 10 logins / 5 min por IP; 20 mensagens / 10 s por usuário;
  5 tentativas de senha de admin / 15 min por usuário.
- Limites: mensagem de até 2000 caracteres; frame WebSocket de até 16 KB.
- Checagem de `Origin` no login e no WebSocket (bloqueia uso a partir de outros sites).
- Cabeçalhos de segurança (CSP, `X-Frame-Options`, `nosniff`).
- Sem SQL injection (consultas parametrizadas) e sem XSS (`textContent`).

## Banco de dados

- `usuarios` (id, apelido, senha_hash, is_admin, is_master, criado_em, ultimo_acesso)
- `sessoes` (token_hash, usuario_id, criado_em, expira_em)
- `mensagens` (id, remetente_id, destinatario_id — NULL = Geral —, texto, enviado_em, lida)

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
