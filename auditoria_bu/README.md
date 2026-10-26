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
`resultados-<ano>-boletim-de-urna`, baixa o recurso "Boletim de Urna" do
turno escolhido de cada UF (um `.zip` contendo um `.csv` com uma linha por
candidato/seção) e filtra só as linhas do cargo Presidente, agrupando por
seção.

**1º e 2º turno são registros diferentes** (mesma zona/seção/ano, turno
diferente) — o banco trata isso como chave composta (`uf+zona+seção+ano+
turno`), nunca sobrescrevendo um pelo outro. Na consulta por seção
(`/bu/UF/ZONA/SECAO`), se você não especificar o turno na URL
(`?turno=1` ou `?turno=2`), o site mostra automaticamente o mais recente
que existir pra aquela seção.

**Antes de rodar a coleta completa**, valide com uma UF de exemplo:

```bash
npm run inspecionar:bu -- 2022 SP      # 1º turno (padrão)
npm run inspecionar:bu -- 2026 MG 2    # 2º turno
```

Isso baixa só o recurso de uma UF, mostra a lista de arquivos dentro do
zip, o cabeçalho real do CSV e tenta extrair os votos de uma seção —
confira se os números batem. As colunas já foram confirmadas contra o
cabeçalho real do CSV de SP/2022 (incluindo `DS_CARGO_PERGUNTA` — não
`DS_CARGO`, que era o meu primeiro palpite). Se um ano futuro mudar o
layout, o mesmo comando mostra o cabeçalho real e o erro aponta
exatamente qual coluna ajustar no mapa `COLUNAS` em
`src/lib/parser-bu-csv.ts`.

**Estados grandes passam de 800 MB descompactados** (o CSV tem linha pra
todos os cargos, não só Presidente) — por isso a leitura é em streaming
(`src/lib/zip-csv-stream.ts`): o zip nunca é descompactado inteiro na
memória, só a linha atual é processada por vez, e a coleta grava em lotes
de 500 seções por transação.

Depois de confirmar, rode a coleta completa:

```bash
npm run coletar -- 2022            # todas as UFs, 1º turno
npm run totalizar -- 2022          # totaliza o 1º turno

npm run coletar -- 2026 MG 2       # só uma UF, 2º turno (teste antes de soltar pra todas)
npm run coletar -- 2026 2          # todas as UFs, só o 2º turno
npm run totalizar -- 2026 2        # totaliza o 2º turno
```

Agende via cron: `coletar` a cada 5 min no dia da eleição (ou 1x/dia fora
do período eleitoral), `totalizar` logo depois de cada coleta — do turno
que estiver em andamento.

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
