# Auditoria Cidadã de BUs

Site público que espelha o Boletim de Urna (BU) digital de cada seção
eleitoral, exatamente como o TSE já publica em `dadosabertos.tse.jus.br`,
para o cidadão comparar com a cópia física afixada no seu local de votação.

## O que este site NÃO é

Isto **não é uma "apuração paralela"**. Os dados exibidos vêm da mesma fonte
oficial (TSE) — o site não faz nenhuma contagem independente de votos. O
valor dele está em facilitar a conferência individual: "o que está na tela
bate com o papel que eu vi colado na minha seção?".

## Por que não tem ranking nem contador público de "divergência"

Essa decisão de design foi discutida e é importante manter:

- Como o BU digital exibido vem direto do TSE, um clique de "algo errado"
  **nunca prova** divergência nenhuma por si só — ele só mede "quantas
  pessoas clicaram", o que é trivial de manipular (script, bot, campanha
  coordenada).
- Um contador público, e pior, um **ranking** de seções "mais denunciadas",
  é material pronto pra viralizar como "prova" de fraude em massa antes de
  qualquer verificação — o mesmo padrão que alimentou desinformação
  eleitoral e os ataques de 8 de janeiro de 2023 no Brasil.
- Por isso: **"Conferi, está de acordo" é o único contador público**
  (confirmação nunca pode virar arma de desinformação). Relatos de
  divergência vão para uma **fila de moderação privada** (`/moderacao`,
  com senha) e só entram em qualquer estatística depois de confirmados por
  um humano — e mesmo assim, sem formar ranking.

Se alguma mudança futura tocar nessa área, releia esta seção antes.

## Stack

- Next.js 14 (App Router) + TailwindCSS
- PostgreSQL + Prisma ORM
- Scripts de coleta/totalização via `tsx` (rodados por cron fora do app)

## Rodando localmente

```bash
cp .env.example .env.local   # preencha DATABASE_URL, SESSION_SECRET, MODERACAO_SENHA
npm install
npx prisma migrate deploy
npm run seed:exemplo         # dados fictícios, só para testar a UI
npm run dev
```

## Coleta de dados (pendente de finalizar)

`scripts/baixar-bus.ts` é um **esqueleto**: não consegui confirmar os
endpoints exatos do catálogo de dados abertos do TSE nesta sessão (acesso
bloqueado pela rede do ambiente). Antes de usar em produção:

1. Abra `dadosabertos.tse.jus.br` e confirme o pacote de BUs do ano desejado
   (é um catálogo CKAN).
2. Verifique o formato disponível — `.bu` binário (ASN.1, assinado) ou um
   espelho em JSON/CSV.
3. Complete `listarArquivosDaUf` e `baixarEConverter` no script.
4. Se for o `.bu` binário, implemente o parser ASN.1 em
   `src/lib/parser-bu.ts` e teste campo a campo contra um BU que você já
   conhece o resultado — essa é a parte mais fácil de acertar por fora e
   errar os números por dentro.

Depois de rodar a coleta, rode `npm run totalizar` (ou agende via cron) para
atualizar os totais exibidos na home.

## Variáveis de ambiente

Ver `.env.example`. Nenhum segredo vai pro git.

## Easypanel

1. **Create Service → App**.
2. **Source → GitHub**: `zulatonet/general`, branch do projeto, **Build Path**
   `/auditoria_bu`.
3. **Build → Dockerfile**.
4. **Environment**: `DATABASE_URL` (Postgres externo, ex. Supabase/Neon, com
   SSL), `SESSION_SECRET`, `MODERACAO_SENHA`.
5. **Domains**: domínio → porta `8080`.

O container roda `prisma migrate deploy` automaticamente antes de subir o
servidor.

## Privacidade (LGPD)

- Nenhum IP é armazenado — só um hash irreversível (IP+UA+segredo), usado
  apenas para limitar ações por dispositivo.
- Nenhuma foto de BU físico é exibida publicamente; evidências anexadas a
  um relato (quando implementado o upload) ficam visíveis só para quem
  modera.
- Relatos de divergência não carregam nome nem identificação.
