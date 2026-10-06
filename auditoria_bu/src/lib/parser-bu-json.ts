/**
 * Converte um JSON de Boletim de Urna do TSE (formato "BU na Web") num
 * BuNormalizado, pegando só os votos do cargo PRESIDENTE.
 *
 * O QUE EU SEI COM CONFIANÇA (confirmado por documentação pública do TSE
 * e pela busca — não fabriquei isto):
 *  - O arquivo tem um campo de dicionário abreviado: ele (Eleição), carg
 *    (Cargo), par (Partidos), el (Eleitores), vt (Votos), cand
 *    (Candidatos), perg (Pergunta), resp (Resposta).
 *  - O nome do arquivo (p<pleito>-<uf>-m<município>-z<zona>-s<seção>.json)
 *    já dá uf/município/zona/seção com certeza — uso isso, não o conteúdo,
 *    pra esses campos.
 *  - O código de cargo 1 = Presidente é o padrão histórico do TSE (cargos
 *    1=Presidente, 3=Governador, 5=Senador, 6=Dep. Federal, 7=Dep.
 *    Estadual, 8=Dep. Distrital), mas CONFIRME isso rodando
 *    `npm run inspecionar:bu -- <caminho-do-json>` num arquivo de verdade
 *    antes de rodar a coleta em produção.
 *
 * O QUE EU NÃO SEI AO CERTO (não consegui baixar um arquivo de verdade
 * pra testar nesta sessão — acesso à rede do TSE bloqueado aqui):
 *  - A profundidade exata de aninhamento de `carg` → `cand` → `vt`.
 *
 * Por isso este parser tenta alguns formatos plausíveis e, se não
 * encontrar nada reconhecível, lança um erro dizendo exatamente o que
 * faltou — em vez de salvar um BU com votos errados silenciosamente.
 */
import { createHash } from "crypto";
import type { BuNormalizado } from "./tipos";

const COD_CARGO_PRESIDENTE = 1;

type NoArbitrario = Record<string, unknown>;

function comoArray(valor: unknown): NoArbitrario[] {
  if (Array.isArray(valor)) return valor as NoArbitrario[];
  if (valor && typeof valor === "object") return [valor as NoArbitrario];
  return [];
}

function acharCargoPresidente(json: NoArbitrario): NoArbitrario | null {
  // Tenta os formatos mais prováveis: raiz.carg[], raiz.ele.carg[], raiz.cand (achatado).
  const candidatosDeLista = [
    ...comoArray(json.carg),
    ...comoArray((json.ele as NoArbitrario | undefined)?.carg),
    ...comoArray((json.el as NoArbitrario | undefined)?.carg),
  ];
  for (const c of candidatosDeLista) {
    const codigo = Number(c.cd ?? c.codCargo ?? c.cod ?? c.codigo ?? NaN);
    const nome = String(c.nm ?? c.nome ?? c.ds ?? "").toLowerCase();
    if (codigo === COD_CARGO_PRESIDENTE || nome.includes("presidente")) return c;
  }
  return null;
}

function extrairVotosDoCargo(cargo: NoArbitrario): { votos: Record<string, number>; total: number } {
  const votos: Record<string, number> = {};
  let total = 0;

  for (const cand of comoArray(cargo.cand)) {
    const numero = String(cand.nr ?? cand.numero ?? cand.cd ?? "");
    const qtd = Number(cand.vt ?? cand.votos ?? cand.qt ?? NaN);
    if (!numero || Number.isNaN(qtd)) continue;
    votos[numero] = qtd;
    total += qtd;
  }

  // Branco/nulo costumam vir como "candidatos" especiais (nr 95/96) ou
  // como campos à parte — cobre os dois casos.
  const brancoDireto = Number(cargo.vb ?? cargo.votosBrancos ?? NaN);
  const nuloDireto = Number(cargo.vn ?? cargo.votosNulos ?? NaN);
  if (!Number.isNaN(brancoDireto) && !("branco" in votos)) {
    votos.branco = brancoDireto;
    total += brancoDireto;
  }
  if (!Number.isNaN(nuloDireto) && !("nulo" in votos)) {
    votos.nulo = nuloDireto;
    total += nuloDireto;
  }

  return { votos, total };
}

export function parsearBuJson(
  conteudoJson: string,
  contexto: { uf: string; municipio: string; municipioCod: string; zona: string; secao: string; ano: number; fonteUrl: string }
): BuNormalizado {
  let json: NoArbitrario;
  try {
    json = JSON.parse(conteudoJson);
  } catch {
    throw new Error(`JSON inválido em ${contexto.fonteUrl}`);
  }

  const cargo = acharCargoPresidente(json);
  if (!cargo) {
    throw new Error(
      `Não achei o cargo Presidente no BU de ${contexto.uf}/${contexto.zona}/${contexto.secao}. ` +
        `Rode 'npm run inspecionar:bu' nesse arquivo e ajuste acharCargoPresidente() em src/lib/parser-bu-json.ts.`
    );
  }

  const { votos, total } = extrairVotosDoCargo(cargo);
  if (Object.keys(votos).length === 0) {
    throw new Error(
      `Achei o cargo Presidente mas nenhum voto em ${contexto.uf}/${contexto.zona}/${contexto.secao}. ` +
        `Ajuste extrairVotosDoCargo() em src/lib/parser-bu-json.ts com base na estrutura real.`
    );
  }

  return {
    uf: contexto.uf,
    municipio: contexto.municipio,
    municipioCod: contexto.municipioCod,
    zona: contexto.zona,
    secao: contexto.secao,
    ano: contexto.ano,
    hashBu: createHash("sha256").update(conteudoJson).digest("hex"),
    dataBu: new Date().toISOString(), // TODO: usar a data/hora real do BU, se o JSON trouxer
    votos,
    totalVotos: total,
    fonteUrl: contexto.fonteUrl,
  };
}

// Nome de arquivo: p<pleito>-<uf>-m<municipio>-z<zona>-s<secao>.json
const REGEX_NOME_ARQUIVO = /^p(\d+)-([a-z]{2})-m(\d+)-z(\d+)-s(\d+)\.json$/i;

export function extrairContextoDoNome(nomeArquivo: string) {
  const m = nomeArquivo.match(REGEX_NOME_ARQUIVO);
  if (!m) return null;
  const [, , uf, municipioCod, zona, secao] = m;
  return { uf: uf.toUpperCase(), municipioCod, zona, secao };
}
