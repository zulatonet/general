/**
 * Baixa só o recurso de UMA UF (não salva nada no banco) e imprime a
 * estrutura crua na tela — rode isto ANTES da coleta completa pra
 * confirmar se o mapa de colunas em src/lib/parser-bu-csv.ts bate com o
 * CSV real do TSE. Lê em streaming (não carrega o CSV inteiro — pode
 * passar de 800 MB descompactado num estado grande).
 *
 * Uso: npm run inspecionar:bu -- 2022 SP
 */
import { listarArquivosZip, linhasCsvDoZip } from "../src/lib/zip-csv-stream";
import { criarProcessadorCsvBu } from "../src/lib/parser-bu-csv";

const CKAN_BASE = process.env.TSE_CKAN_BASE ?? "https://dadosabertos.tse.jus.br";
// Quantas seções de exemplo mostrar antes de parar (não precisa ler o
// arquivo inteiro só pra inspecionar).
const LIMITE_SECOES = 3;

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

  console.log("Baixando o zip (o conteúdo dele é processado em streaming, sem carregar tudo na memória)...");
  const buffer = Buffer.from(await (await fetch(recurso.url)).arrayBuffer());
  console.log(`Zip baixado: ${(buffer.length / 1024 / 1024).toFixed(1)} MB compactado.`);

  console.log("\n=== Arquivos dentro do zip ===");
  for (const a of await listarArquivosZip(buffer)) {
    console.log(`  ${a.nome} — ${(a.bytes / 1024 / 1024).toFixed(1)} MB descompactado`);
  }

  const processador = criarProcessadorCsvBu(recurso.url, ano);
  let cabecalhoImpresso = false;
  let primeiraLinhaDadosImpressa = false;

  for await (const linha of linhasCsvDoZip(buffer)) {
    if (!cabecalhoImpresso) {
      console.log(`\n=== Cabeçalho (linha 1) ===\n${linha}`);
      cabecalhoImpresso = true;
    } else if (!primeiraLinhaDadosImpressa) {
      console.log(`\n=== Primeira linha de dados (linha 2) ===\n${linha}`);
      primeiraLinhaDadosImpressa = true;
    }

    processador.linha(linha); // lança erro aqui mesmo se faltar coluna

    // Já viu seções suficientes pra conferir? Para de ler o resto do
    // arquivo (não precisa descompactar o estado inteiro só pra inspecionar).
    if (processador.linhasProcessadas > 20000) break;
  }

  const bus = processador.finalizar();
  console.log(`\n=== Parser extraiu ${bus.length} seção(ões) com votos de Presidente (nas primeiras linhas lidas) ===`);
  console.log(bus.slice(0, LIMITE_SECOES));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
