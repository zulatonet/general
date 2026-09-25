# general

Monorepo de aplicações. Cada pasta na raiz é um projeto independente que vira
um serviço no **Easypanel**.

## Roteamento

| Pasta | Serviço Easypanel | Build | Porta | Descrição |
|---|---|---|---|---|
| [`chat_simples/`](chat_simples/) | `chat` | Dockerfile | 8080 | Chat em tempo real (aiohttp + PostgreSQL) |

## Como apontar uma pasta no Easypanel

1. **Create Service → App**.
2. **Source → GitHub**: `zulatonet/general`, branch `main`, **Build Path** `/<pasta>`.
3. **Build → Dockerfile**.
4. **Environment**: variáveis listadas no `.env.example` da pasta.
5. **Domains**: domínio → porta do serviço (tabela acima).

## Convenções

- Cada pasta é autocontida: `Dockerfile`, `README.md` e `.env.example` próprios.
- Configuração e segredos só por variável de ambiente, nunca no código nem no git.
- Nada de dependências entre pastas (o build de uma não enxerga as outras).
