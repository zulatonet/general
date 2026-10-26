# general

Monorepo de aplicações. Cada pasta na raiz é um projeto independente que vira
um serviço no **Easypanel**.

## Roteamento

| Pasta | Serviço Easypanel | Build | Porta | Descrição |
|---|---|---|---|---|
| [`chat_simples/`](chat_simples/) | `chat_simples` | Dockerfile | 8080 | **SalaVip**: chat em tempo real (aiohttp + PostgreSQL) em https://chat.salavip.live |
| [`transmissor_live/`](transmissor_live/) | `transmissor_live` | Dockerfile | — | Transmite a página da live do SalaVip 24h para o YouTube (Chromium + ffmpeg), com músicas de fundo |
| [`auditoria_bu/`](auditoria_bu/) | `auditoria_bu` | Dockerfile | 8080 | Consulta pública ao Boletim de Urna digital do TSE por seção, para o cidadão comparar com a cópia física |

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
