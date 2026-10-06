/**
 * Baixa só UM arquivo de exemplo (não salva nada no banco) e imprime a
 * estrutura crua na tela — rode isto ANTES da coleta completa pra
 * confirmar se acharCargoPresidente/extrairVotosDoCargo (em
 * src/lib/parser-bu-json.ts) batem com o formato real.
 *
 * Uso: npm run inspecionar:bu -- 2022 SP
 */
import AdmZip from "adm-zip";
import { parsearBuJson, extrairContextoDoNome } from "../src/lib/parser-bu-json";

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
      "Recursos dessa UF (todos, pra eu ver o formato real):",
      todos.filter((r) => r.name.trim().slice(0, 2).toUpperCase() === uf).map((r) => ({ name: r.name, format: r.format, url: r.url }))
    );
    throw new Error(`Não achei "Boletim de Urna - Primeiro turno" da UF ${uf}. Veja a lista acima.`);
  }
  console.log(`Recurso achado: ${recurso.name} (format=${recurso.format})`);

  console.log(`Baixando ${recurso.name}...`);
  const buffer = Buffer.from(await (await fetch(recurso.url)).arrayBuffer());
  const zip = new AdmZip(buffer);
  const primeiroJson = zip.getEntries().find((e) => e.entryName.endsWith(".json"));
  if (!primeiroJson) throw new Error("Nenhum .json dentro do zip — o formato pode ser outro (talvez .bu binário).");

  const conteudo = primeiroJson.getData().toString("utf-8");
  console.log(`\n=== Arquivo: ${primeiroJson.entryName} ===`);
  console.log(conteudo.slice(0, 4000));

  const ctx = extrairContextoDoNome(primeiroJson.entryName.split("/").pop() ?? "");
  console.log("\n=== Contexto extraído do nome do arquivo ===", ctx);

  if (ctx) {
    try {
      const bu = parsearBuJson(conteudo, { ...ctx, municipio: ctx.municipioCod, ano, fonteUrl: recurso.url });
      console.log("\n=== Parser conseguiu extrair (confira se os números batem com o arquivo acima) ===");
      console.log(bu);
    } catch (err) {
      console.log("\n=== O parser NÃO conseguiu extrair — ajuste src/lib/parser-bu-json.ts ===");
      console.log((err as Error).message);
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
