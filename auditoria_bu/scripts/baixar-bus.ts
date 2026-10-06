/**
 * Coletor de Boletins de Urna do TSE.
 *
 * Como funciona (confirmado via busca — ver src/lib/parser-bu-json.ts pro
 * detalhe do que é certeza e o que precisa validação):
 *   1. Pergunta pro catálogo CKAN de dados abertos do TSE (API pública,
 *      sem chave) quais recursos existem pro pacote
 *      "resultados-<ano>-boletim-de-urna".
 *   2. Pra cada UF, baixa o ZIP do 1º turno (e do 2º turno, se existir).
 *   3. Dentro do ZIP tem um JSON por seção, nomeado
 *      p<pleito>-<uf>-m<município>-z<zona>-s<seção>.json.
 *   4. Converte cada um pra BuNormalizado (só os votos de Presidente) e
 *      salva/atualiza no banco.
 *
 * IMPORTANTE antes de rodar isto a sério:
 *   - Rode primeiro `npm run inspecionar:bu -- <ano> <UF>` pra baixar só
 *     UM arquivo de exemplo e ver a estrutura real na tela. Se
 *     `acharCargoPresidente`/`extrairVotosDoCargo` em
 *     src/lib/parser-bu-json.ts não baterem com o que você vir, ajuste
 *     antes de rodar a coleta completa — ela vai falhar alto (lança
 *     erro) em vez de salvar dado errado, mas é melhor confirmar antes.
 */
import AdmZip from "adm-zip";
import { prisma } from "../src/lib/prisma";
import { parsearBuJson, extrairContextoDoNome } from "../src/lib/parser-bu-json";

const CKAN_BASE = process.env.TSE_CKAN_BASE ?? "https://dadosabertos.tse.jus.br";
const UFS = [
  "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
  "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
  "SP", "SE", "TO",
];

type RecursoCkan = { name: string; format: string; url: string };

async function listarRecursos(ano: number): Promise<RecursoCkan[]> {
  const url = `${CKAN_BASE}/api/3/action/package_show?id=resultados-${ano}-boletim-de-urna`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`CKAN respondeu ${r.status} em ${url}`);
  const dados = await r.json();
  if (!dados.success) throw new Error(`CKAN: ${JSON.stringify(dados.error)}`);
  return (dados.result.resources ?? []) as RecursoCkan[];
}

function recursoEhDaUf(recurso: RecursoCkan, uf: string): boolean {
  // Os nomes são tipo "SE - Boletim de Urna - Primeiro turno - 05.10.2022".
  const sigla = recurso.name.trim().slice(0, 2).toUpperCase();
  return sigla === uf && /boletim de urna/i.test(recurso.name) && recurso.format?.toUpperCase() === "ZIP";
}

async function processarUf(uf: string, ano: number, recursos: RecursoCkan[]) {
  const doUf = recursos.filter((r) => recursoEhDaUf(r, uf));
  if (doUf.length === 0) {
    console.log(`  ${uf}: nenhum recurso ZIP encontrado (nome pode ter mudado — confira manualmente).`);
    return;
  }

  for (const recurso of doUf) {
    console.log(`  ${uf}: baixando ${recurso.name}...`);
    const r = await fetch(recurso.url);
    if (!r.ok) {
      console.log(`  ${uf}: falhou (${r.status}) em ${recurso.url}`);
      continue;
    }
    const buffer = Buffer.from(await r.arrayBuffer());
    const zip = new AdmZip(buffer);

    let salvos = 0;
    let erros = 0;
    for (const entrada of zip.getEntries()) {
      if (!entrada.entryName.endsWith(".json")) continue;
      const ctx = extrairContextoDoNome(entrada.entryName.split("/").pop() ?? "");
      if (!ctx) continue;

      try {
        const bu = parsearBuJson(entrada.getData().toString("utf-8"), {
          ...ctx,
          municipio: ctx.municipioCod, // TODO: resolver nome do município (tabela de municípios do TSE)
          ano,
          fonteUrl: recurso.url,
        });
        await prisma.buDigital.upsert({
          where: { uf_zona_secao_ano: { uf: bu.uf, zona: bu.zona, secao: bu.secao, ano: bu.ano } },
          create: { ...bu, dataBu: new Date(bu.dataBu) },
          update: { votos: bu.votos, totalVotos: bu.totalVotos, hashBu: bu.hashBu },
        });
        salvos++;
      } catch (err) {
        erros++;
        if (erros <= 3) console.log(`    erro: ${(err as Error).message}`);
      }
    }
    console.log(`  ${uf}: ${salvos} seções salvas, ${erros} com erro.`);
  }
}

async function main() {
  const ano = Number(process.argv[2] ?? new Date().getFullYear());
  console.log(`Coletando BUs de ${ano}...`);

  const recursos = await listarRecursos(ano);
  console.log(`${recursos.length} recursos encontrados no pacote.`);

  for (const uf of UFS) {
    await processarUf(uf, ano, recursos);
  }

  console.log("Coleta concluída.");
  await prisma.$disconnect();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
