/**
 * Baixa só o recurso de UMA UF (não salva nada no banco) e imprime a
 * estrutura crua na tela — rode isto ANTES da coleta completa pra
 * confirmar se o mapa de colunas em src/lib/parser-bu-csv.ts bate com o
 * CSV real do TSE.
 *
 * Uso: npm run inspecionar:bu -- 2022 SP
 */
import AdmZip from "adm-zip";
import { parsearCsvBu } from "../src/lib/parser-bu-csv";

const CKAN_BASE = process.env.TSE_CKAN_BASE ?? "https://dadosabertos.tse.jus.br";

async function main() {
  const ano = Number(process.argv[2] ?? new Date().getFullYear());
  const uf = (process.argv[3] ?? "SP").toUpperCase();

  const url = `${CKAN_BASE}/api/3/action/package_show?id=resultados-${ano}-boletim-de-urna`;
  console.log(`Buscando pacote: ${url}`);
  const dados = await (await fetch(url)).json();
  if (!dados.success) throw new Error(JSON.stringify(dados.error));

  type Recurso = { name: string; format: string; url: string };
  const todos = (dados.result.resources ?? []) as Recurso[];

  const recurso = todos.find(
    (r) => r.name.trim().slice(0, 2).toUpperCase() === uf && /boletim de urna/i.test(r.name) && /primeiro turno/i.test(r.name)
  );
  if (!recurso) {
    console.log(
      "Recursos dessa UF:",
      todos.filter((r) => r.name.trim().slice(0, 2).toUpperCase() === uf).map((r) => ({ name: r.name, format: r.format, url: r.url }))
    );
    throw new Error(`Não achei "Boletim de Urna - Primeiro turno" da UF ${uf}. Veja a lista acima.`);
  }
  console.log(`Recurso achado: ${recurso.name} (format=${recurso.format})\nURL: ${recurso.url}`);

  console.log(`Baixando...`);
  const buffer = Buffer.from(await (await fetch(recurso.url)).arrayBuffer());

  let conteudoCsv: string;
  // Alguns recursos podem vir como .zip de verdade, outros como .csv direto
  // (o campo "format" nem sempre reflete o content-type real). Detecta pela
  // assinatura do zip (PK\x03\x04) em vez de confiar só na extensão da URL.
  if (buffer.length >= 4 && buffer[0] === 0x50 && buffer[1] === 0x4b) {
    const zip = new AdmZip(buffer);
    const entradas = zip.getEntries();
    console.log(
      "\n=== Arquivos dentro do zip ===",
      entradas.map((e) => ({ nome: e.entryName, bytes: e.header.size }))
    );
    const csv = entradas.find((e) => /\.csv$/i.test(e.entryName));
    if (!csv) throw new Error("Nenhum .csv dentro do zip — confira a lista de arquivos acima pra ver o que tem.");
    console.log(`\nUsando: ${csv.entryName}`);
    conteudoCsv = csv.getData().toString("latin1"); // TSE costuma publicar em Latin-1/ISO-8859-1
  } else {
    console.log("\n(resposta não é um .zip — tratando como CSV direto)");
    conteudoCsv = buffer.toString("latin1");
  }

  const linhas = conteudoCsv.split(/\r?\n/).filter((l) => l.trim());
  console.log(`\n=== Cabeçalho (linha 1) ===\n${linhas[0]}`);
  console.log(`\n=== Primeira linha de dados (linha 2) ===\n${linhas[1]}`);
  console.log(`\nTotal de linhas: ${linhas.length}`);

  try {
    const bus = parsearCsvBu(conteudoCsv, recurso.url, ano);
    console.log(`\n=== Parser extraiu ${bus.length} seções com votos de Presidente ===`);
    console.log("Primeiras 3:", bus.slice(0, 3));
  } catch (err) {
    console.log("\n=== O parser NÃO conseguiu extrair — ajuste src/lib/parser-bu-csv.ts ===");
    console.log((err as Error).message);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
