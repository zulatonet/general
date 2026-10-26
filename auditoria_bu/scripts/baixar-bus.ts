/**
 * Coletor de Boletins de Urna do TSE.
 *
 * Como funciona:
 *   1. Pergunta pro catálogo CKAN de dados abertos do TSE (API pública,
 *      sem chave) quais recursos existem pro pacote
 *      "resultados-<ano>-boletim-de-urna".
 *   2. Pra cada UF, baixa o recurso "Boletim de Urna - Primeiro turno"
 *      (um .zip contendo um .csv com uma linha por candidato/seção —
 *      estados grandes passam de 800 MB descompactado).
 *   3. Lê o CSV em STREAMING (nunca carrega o arquivo inteiro
 *      descompactado na memória), filtra só as linhas do cargo
 *      Presidente, agrupa por seção e salva/atualiza no banco.
 *
 * IMPORTANTE antes de rodar isto a sério:
 *   - Rode primeiro `npm run inspecionar:bu -- <ano> <UF>` numa UF pra
 *     conferir se as colunas batem com o mapa em src/lib/parser-bu-csv.ts.
 *     Se não bater, ele já lança erro dizendo qual coluna faltou.
 *
 * Uso:
 *   npm run coletar -- 2022          (todas as UFs, 1º turno)
 *   npm run coletar -- 2022 SP       (só uma UF, pra testar antes de
 *                                      soltar pra todas — estados grandes
 *                                      passam de vários GB descompactados)
 *   npm run coletar -- 2026 MG 2     (UF + turno — o 2º turno só existe
 *                                      pras UFs que tiveram 2º turno de
 *                                      Presidente/Governador)
 *   npm run coletar -- 2026 2        (todas as UFs, só o 2º turno)
 */
import { prisma } from "../src/lib/prisma";
import { criarProcessadorCsvBu } from "../src/lib/parser-bu-csv";
import { linhasCsvDoZip } from "../src/lib/zip-csv-stream";

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

function recursoEhDaUf(recurso: RecursoCkan, uf: string, turno: number): boolean {
  // Os nomes são tipo "SE - Boletim de Urna - Primeiro turno - 05.10.2022"
  // ou "... Segundo turno - ...".
  const sigla = recurso.name.trim().slice(0, 2).toUpperCase();
  const nomeTurno = turno === 2 ? "segundo turno" : "primeiro turno";
  return sigla === uf && /boletim de urna/i.test(recurso.name) && new RegExp(nomeTurno, "i").test(recurso.name);
}

async function processarUf(uf: string, ano: number, turno: number, recursos: RecursoCkan[]) {
  const recurso = recursos.find((r) => recursoEhDaUf(r, uf, turno));
  if (!recurso) {
    console.log(
      `  ${uf}: nenhum recurso de ${turno}º turno encontrado (pode não ter havido ${turno}º turno nessa UF, ou o nome mudou).`
    );
    return;
  }

  console.log(`  ${uf}: baixando ${recurso.name}...`);
  const r = await fetch(recurso.url);
  if (!r.ok) {
    console.log(`  ${uf}: falhou (${r.status}) em ${recurso.url}`);
    return;
  }
  const buffer = Buffer.from(await r.arrayBuffer());

  const processador = criarProcessadorCsvBu(recurso.url, ano);
  try {
    for await (const linha of linhasCsvDoZip(buffer)) {
      processador.linha(linha);
    }
  } catch (err) {
    console.log(`  ${uf}: erro ao processar — ${(err as Error).message}`);
    return;
  }

  const bus = processador.finalizar();
  let salvos = 0;
  // Grava em lotes (uma transação a cada 500) em vez de uma promise por
  // vez — mais rápido e não deixa a conexão aberta tempo demais.
  const TAMANHO_LOTE = 500;
  for (let i = 0; i < bus.length; i += TAMANHO_LOTE) {
    const lote = bus.slice(i, i + TAMANHO_LOTE);
    await prisma.$transaction(
      lote.map((bu) =>
        prisma.buDigital.upsert({
          where: {
            uf_zona_secao_ano_turno: { uf: bu.uf, zona: bu.zona, secao: bu.secao, ano: bu.ano, turno: bu.turno },
          },
          create: { ...bu, dataBu: new Date(bu.dataBu) },
          update: { votos: bu.votos, totalVotos: bu.totalVotos, hashBu: bu.hashBu },
        })
      )
    );
    salvos += lote.length;
  }
  console.log(`  ${uf}: ${salvos} seções salvas (de ${processador.linhasProcessadas} linhas lidas no CSV).`);
}

async function main() {
  const ano = Number(process.argv[2] ?? new Date().getFullYear());
  // O 3º argumento pode ser a UF (ex.: "MG") ou, se você quiser todas as
  // UFs mas num turno específico, direto o turno ("1"/"2") no lugar dela:
  // `npm run coletar -- 2026 2` = todas as UFs, 2º turno.
  const arg3 = process.argv[3]?.toUpperCase();
  const arg3EhTurno = arg3 === "1" || arg3 === "2";
  const ufUnica = arg3EhTurno ? undefined : arg3;
  const turno = Number(arg3EhTurno ? arg3 : (process.argv[4] ?? "1"));
  if (turno !== 1 && turno !== 2) throw new Error("turno precisa ser 1 ou 2");
  console.log(`Coletando BUs de ${ano}, ${turno}º turno${ufUnica ? ` (só ${ufUnica})` : ""}...`);

  const recursos = await listarRecursos(ano);
  console.log(`${recursos.length} recursos encontrados no pacote.`);

  if (ufUnica) {
    if (!UFS.includes(ufUnica)) throw new Error(`UF inválida: ${ufUnica}`);
    await processarUf(ufUnica, ano, turno, recursos);
  } else {
    for (const uf of UFS) {
      await processarUf(uf, ano, turno, recursos);
    }
  }

  console.log("Coleta concluída.");
  await prisma.$disconnect();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
