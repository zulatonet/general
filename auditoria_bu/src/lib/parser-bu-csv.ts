/**
 * Parser do CSV de Boletim de Urna do TSE (o formato real do pacote
 * `resultados-<ano>-boletim-de-urna` em dadosabertos.tse.jus.br — um .zip
 * por UF contendo um .csv com uma linha por candidato/votável/seção).
 *
 * O CSV de um estado grande passa de 800 MB descompactado (tem linha pra
 * TODOS os cargos — presidente, governador, senador, deputados...), então
 * este parser é feito pra processar **linha por linha** (streaming), nunca
 * carregando o arquivo inteiro de uma vez. Só guardamos na memória as
 * linhas já filtradas de Presidente, agrupadas por seção — isso sim cabe
 * tranquilo (são bem menos linhas que o total).
 *
 * As colunas abaixo (SG_UF, NR_ZONA, NR_SECAO, DS_CARGO, NR_VOTAVEL,
 * QT_VOTOS...) são o layout público mais comum nesse tipo de dataset do
 * TSE. `npm run inspecionar:bu` imprime o cabeçalho real; se algum nome
 * de coluna não bater, ajuste o mapa COLUNAS abaixo.
 */
import { createHash } from "crypto";
import type { BuNormalizado } from "./tipos";

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

type ChaveColuna = keyof typeof COLUNAS;

function dividirLinhaCsv(linha: string, delimitador = ";"): string[] {
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
  const indices: Partial<Record<ChaveColuna, number>> = {};
  for (const chave of Object.keys(COLUNAS) as ChaveColuna[]) {
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

type Acumulado = {
  uf: string;
  municipio: string;
  municipioCod: string;
  zona: string;
  secao: string;
  votos: Record<string, number>;
  dataBu: string;
};

function converterDataBu(dataBu: string): string {
  // "DD/MM/AAAA HH:MM:SS" -> ISO. Data e hora em partes separadas, já que
  // a string toda tem um espaço no meio.
  const [dataParte, horaParte] = dataBu.split(" ");
  const [dia, mes, anoStr] = (dataParte ?? "").split("/");
  const data = dia && mes && anoStr ? new Date(`${anoStr}-${mes}-${dia}T${horaParte || "00:00:00"}`) : new Date();
  return Number.isNaN(data.getTime()) ? new Date().toISOString() : data.toISOString();
}

function finalizarAcumulado(a: Acumulado, ano: number, fonteUrl: string): BuNormalizado {
  const totalVotos = Object.values(a.votos).reduce((s, v) => s + v, 0);
  return {
    uf: a.uf,
    municipio: a.municipio,
    municipioCod: a.municipioCod,
    zona: a.zona,
    secao: a.secao,
    ano,
    hashBu: createHash("sha256").update(`${a.uf}-${a.zona}-${a.secao}-${JSON.stringify(a.votos)}`).digest("hex"),
    dataBu: converterDataBu(a.dataBu),
    votos: a.votos,
    totalVotos,
    fonteUrl,
  };
}

/**
 * Processador incremental: chame `linha()` uma vez por linha do CSV (a
 * primeira chamada DEVE ser o cabeçalho), e `finalizar()` no fim pra pegar
 * os BuNormalizado agrupados por seção. Não guarda linhas que não são de
 * Presidente — é isso que mantém o uso de memória baixo mesmo em estados
 * grandes.
 */
export function criarProcessadorCsvBu(fonteUrl: string, ano: number) {
  let indices: Partial<Record<ChaveColuna, number>> | null = null;
  const porSecao = new Map<string, Acumulado>();
  let numeroLinha = 0;

  function linha(texto: string) {
    numeroLinha++;
    if (!texto.trim()) return;

    if (indices === null) {
      indices = montarIndiceColunas(dividirLinhaCsv(texto));
      const faltando = (Object.keys(COLUNAS) as ChaveColuna[]).filter((k) => indices![k] === undefined);
      if (faltando.length > 0) {
        throw new Error(
          `Colunas não encontradas no CSV: ${faltando.join(", ")}. ` +
            `Cabeçalho real: ${texto}. Ajuste o mapa COLUNAS em src/lib/parser-bu-csv.ts.`
        );
      }
      return;
    }
    const idx = indices as Record<ChaveColuna, number>;

    const campos = dividirLinhaCsv(texto);
    const cargo = (campos[idx.cargo] ?? "").toUpperCase();
    const codCargo = campos[idx.codCargo] ?? "";
    const ehPresidente = codCargo === CODIGO_CARGO_PRESIDENTE || cargo.includes("PRESIDENTE");
    if (!ehPresidente) return;

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
    if (Number.isNaN(qtd)) return;

    const chaveVoto = NOMES_BRANCO.includes(nomeVotavel)
      ? "branco"
      : NOMES_NULO.includes(nomeVotavel)
        ? "nulo"
        : numeroVotavel || nomeVotavel;

    acumulado.votos[chaveVoto] = (acumulado.votos[chaveVoto] ?? 0) + qtd;
  }

  function finalizar(): BuNormalizado[] {
    if (indices === null) throw new Error("Nenhuma linha processada (o arquivo estava vazio?).");
    return Array.from(porSecao.values()).map((a) => finalizarAcumulado(a, ano, fonteUrl));
  }

  return { linha, finalizar, get linhasProcessadas() { return numeroLinha; } };
}

/** Versão simples pra testes/amostras pequenas: recebe o CSV inteiro como string. */
export function parsearCsvBu(conteudoCsv: string, fonteUrl: string, ano: number): BuNormalizado[] {
  const processador = criarProcessadorCsvBu(fonteUrl, ano);
  for (const l of conteudoCsv.split(/\r?\n/)) processador.linha(l);
  return processador.finalizar();
}
