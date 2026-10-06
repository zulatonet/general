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
`resultados-<ano>-boletim-de-urna`, baixa o ZIP de cada UF e extrai os JSONs
por seção (`p<pleito>-<uf>-m<município>-z<zona>-s<seção>.json`), filtrando
só os votos de Presidente.

**Antes de rodar a coleta completa**, valide com um arquivo de exemplo:

```bash
npm run inspecionar:bu -- 2022 SP
```

Isso baixa só um ZIP, mostra o JSON cru de uma seção na tela e tenta
extrair os votos — confira se os números batem com o que apareceu. Se não
bater (ou se der erro), ajuste `acharCargoPresidente` e
`extrairVotosDoCargo` em `src/lib/parser-bu-json.ts`: eu não consegui
testar contra um arquivo real nesta sessão (acesso a `dadosabertos.tse.jus.br`
bloqueado pela rede do ambiente onde foi desenvolvido), então a extração de
votos usa os nomes de campo mais prováveis — mas pode precisar de ajuste
fino. O nome do arquivo (uf/município/zona/seção) é confiável, só o
conteúdo interno do JSON (cargo/candidato/votos) é que precisa validação.

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
