/**
 * Parser do CSV de Boletim de Urna do TSE (o formato real do pacote
 * `resultados-<ano>-boletim-de-urna` em dadosabertos.tse.jus.br — o
 * recurso diz format=CSV, dentro de um .zip por UF).
 *
 * O CSV tem UMA LINHA POR CANDIDATO/VOTÁVEL POR SEÇÃO (não uma linha por
 * seção) — por isso agrupamos por UF+zona+seção antes de salvar.
 *
 * As colunas abaixo (DT_GERACAO, SG_UF, NR_ZONA, NR_SECAO, DS_CARGO,
 * NR_VOTAVEL, NM_VOTAVEL, QT_VOTOS, ...) são o layout público mais comum
 * nesse tipo de dataset do TSE — mas eu não baixei um arquivo de verdade
 * nesta sessão pra conferir com certeza absoluta. `npm run inspecionar:bu`
 * imprime o cabeçalho real; se algum nome de coluna não bater com o que
 * está aqui, ajuste o mapa `COLUNAS` abaixo (é só trocar o nome entre
 * aspas pelo nome real da coluna — o resto do código não precisa mudar).
 */
import { createHash } from "crypto";
import type { BuNormalizado } from "./tipos";

// Nome da coluna esperado -> possíveis variações (a primeira que existir no
// cabeçalho real é usada). Ajuste aqui se `inspecionar:bu` mostrar outro nome.
const COLUNAS = {
  uf: ["SG_UF"],
  municipioCod: ["CD_MUNICIPIO"],
  municipio: ["NM_MUNICIPIO"],
  zona: ["NR_ZONA"],
  secao: ["NR_SECAO"],
  cargo: ["DS_CARGO"],
  codCargo: ["CD_CARGO_PERGUNTA"],
  numeroVotavel: ["NR_VOTAVEL"],
  nomeVotavel: ["NM_VOTAVEL"],
  votos: ["QT_VOTOS"],
  dataGeracao: ["DT_GERACAO"],
  horaGeracao: ["HH_GERACAO"],
} as const;

function dividirLinhaCsv(linha: string, delimitador = ";"): string[] {
  // CSV simples com possíveis campos entre aspas (nomes de município podem
  // ter acento, mas raramente têm o delimitador dentro — ainda assim,
  // trata aspas por segurança.
  const campos: string[] = [];
  let atual = "";
  let dentroDeAspas = false;
  for (let i = 0; i < linha.length; i++) {
    const c = linha[i];
    if (c === '"') {
      dentroDeAspas = !dentroDeAspas;
    } else if (c === delimitador && !dentroDeAspas) {
      campos.push(atual);
      atual = "";
    } else {
      atual += c;
    }
  }
  campos.push(atual);
  return campos.map((c) => c.trim().replace(/^"|"$/g, ""));
}

function montarIndiceColunas(cabecalho: string[]) {
  const normalizado = cabecalho.map((c) => c.trim().toUpperCase());
  const indices: Partial<Record<keyof typeof COLUNAS, number>> = {};
  for (const chave of Object.keys(COLUNAS) as (keyof typeof COLUNAS)[]) {
    for (const candidato of COLUNAS[chave]) {
      const i = normalizado.indexOf(candidato);
      if (i >= 0) {
        indices[chave] = i;
        break;
      }
    }
  }
  return indices;
}

const CODIGO_CARGO_PRESIDENTE = "1";
const NOMES_BRANCO = ["BRANCO"];
const NOMES_NULO = ["NULO", "NULO/BRANCO"];

export function parsearCsvBu(conteudoCsv: string, fonteUrl: string, ano: number): BuNormalizado[] {
  const linhas = conteudoCsv.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (linhas.length < 2) return [];

  const indices = montarIndiceColunas(dividirLinhaCsv(linhas[0]));
  const faltando = (Object.keys(COLUNAS) as (keyof typeof COLUNAS)[]).filter((k) => indices[k] === undefined);
  if (faltando.length > 0) {
    throw new Error(
      `Colunas não encontradas no CSV: ${faltando.join(", ")}. ` +
        `Cabeçalho real: ${linhas[0]}. Ajuste o mapa COLUNAS em src/lib/parser-bu-csv.ts.`
    );
  }
  const idx = indices as Record<keyof typeof COLUNAS, number>;

  type Acumulado = {
    uf: string;
    municipio: string;
    municipioCod: string;
    zona: string;
    secao: string;
    votos: Record<string, number>;
    dataBu: string;
  };
  const porSecao = new Map<string, Acumulado>();

  for (let i = 1; i < linhas.length; i++) {
    const campos = dividirLinhaCsv(linhas[i]);
    const cargo = (campos[idx.cargo] ?? "").toUpperCase();
    const codCargo = campos[idx.codCargo] ?? "";
    const ehPresidente = codCargo === CODIGO_CARGO_PRESIDENTE || cargo.includes("PRESIDENTE");
    if (!ehPresidente) continue;

    const uf = (campos[idx.uf] ?? "").toUpperCase();
    const zona = campos[idx.zona] ?? "";
    const secao = campos[idx.secao] ?? "";
    const chave = `${uf}|${zona}|${secao}`;

    if (!porSecao.has(chave)) {
      porSecao.set(chave, {
        uf,
        municipio: campos[idx.municipio] ?? "",
        municipioCod: campos[idx.municipioCod] ?? "",
        zona,
        secao,
        votos: {},
        dataBu: `${campos[idx.dataGeracao] ?? ""} ${campos[idx.horaGeracao] ?? ""}`.trim(),
      });
    }
    const acumulado = porSecao.get(chave)!;

    const nomeVotavel = (campos[idx.nomeVotavel] ?? "").toUpperCase();
    const numeroVotavel = campos[idx.numeroVotavel] ?? "";
    const qtd = Number(campos[idx.votos] ?? "0");
    if (Number.isNaN(qtd)) continue;

    const chaveVoto = NOMES_BRANCO.includes(nomeVotavel)
      ? "branco"
      : NOMES_NULO.includes(nomeVotavel)
        ? "nulo"
        : numeroVotavel || nomeVotavel;

    acumulado.votos[chaveVoto] = (acumulado.votos[chaveVoto] ?? 0) + qtd;
  }

  return Array.from(porSecao.values()).map((a) => {
    const totalVotos = Object.values(a.votos).reduce((s, v) => s + v, 0);
    // "DD/MM/AAAA HH:MM:SS" -> ISO. Faz a data e a hora separadamente,
    // já que a string toda tem um espaço no meio.
    const [dataParte, horaParte] = a.dataBu.split(" ");
    const [dia, mes, anoStr] = (dataParte ?? "").split("/");
    const dataParseada =
      dia && mes && anoStr ? new Date(`${anoStr}-${mes}-${dia}T${horaParte || "00:00:00"}`) : new Date();
    return {
      uf: a.uf,
      municipio: a.municipio,
      municipioCod: a.municipioCod,
      zona: a.zona,
      secao: a.secao,
      ano,
      hashBu: createHash("sha256").update(`${a.uf}-${a.zona}-${a.secao}-${JSON.stringify(a.votos)}`).digest("hex"),
      dataBu: Number.isNaN(dataParseada.getTime()) ? new Date().toISOString() : dataParseada.toISOString(),
      votos: a.votos,
      totalVotos,
      fonteUrl,
    };
  });
}
