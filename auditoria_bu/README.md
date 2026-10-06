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

## Coleta de dados

`scripts/baixar-bus.ts` já é uma implementação real: pergunta pro catálogo
CKAN de dados abertos do TSE (API pública, sem chave) os recursos do pacote
`resultados-<ano>-boletim-de-urna`, baixa o recurso "Boletim de Urna -
Primeiro turno" de cada UF (um `.zip` contendo um `.csv` com uma linha por
candidato/seção) e filtra só as linhas do cargo Presidente, agrupando por
seção.

**Antes de rodar a coleta completa**, valide com uma UF de exemplo:

```bash
npm run inspecionar:bu -- 2022 SP
```

Isso baixa só o recurso de uma UF, mostra a lista de arquivos dentro do
zip, o cabeçalho real do CSV e tenta extrair os votos de uma seção —
confira se os números batem. Se não bater (ou der erro de "coluna não
encontrada"), ajuste o mapa `COLUNAS` em `src/lib/parser-bu-csv.ts`.

**Estados grandes passam de 800 MB descompactados** (o CSV tem linha pra
todos os cargos, não só Presidente) — por isso a leitura é em streaming
(`src/lib/zip-csv-stream.ts`): o zip nunca é descompactado inteiro na
memória, só a linha atual é processada por vez, e a coleta grava em lotes
de 500 seções por transação.

Depois de confirmar, rode a coleta completa:

```bash
npm run coletar -- 2022
npm run totalizar -- 2022
```

Agende os dois via cron: `coletar` a cada 5 min no dia da eleição (ou 1x/dia
fora do período eleitoral), `totalizar` logo depois de cada coleta.

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
