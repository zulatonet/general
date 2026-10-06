/**
 * Coletor de Boletins de Urna do TSE.
 *
 * IMPORTANTE — isto é um ESQUELETO, não um coletor pronto. Eu (Claude) não
 * consegui confirmar, nesta sessão, os endpoints exatos do catálogo de
 * dados abertos do TSE (o acesso a dadosabertos.tse.jus.br foi bloqueado
 * pela rede daqui), então não vou inventar URLs como se fossem verificadas.
 * Antes de rodar isto de verdade:
 *
 *   1. Abra https://dadosabertos.tse.jus.br no navegador e ache o pacote
 *      "Resultados <ano> - Boletim de Urna" (é um catálogo CKAN).
 *   2. Confirme o formato disponível: alguns anos têm só o .bu binário
 *      (ASN.1, assinado digitalmente), outros também têm um espelho em
 *      JSON/CSV mais fácil de ler.
 *   3. Preencha BASE_URL e a lógica de listagem abaixo com o que encontrar.
 *
 * Se o formato for o .bu binário, a parte mais delicada é o parser ASN.1 —
 * implemente em src/lib/parser-bu.ts e me chame de volta se quiser ajuda
 * nessa parte especificamente (ela é fácil de acertar por fora e errar os
 * valores por dentro, então vale testar campo a campo contra um BU que
 * você já conhece o resultado).
 */
import { prisma } from "../src/lib/prisma";
import type { BuNormalizado } from "../src/lib/tipos";

const BASE_URL = process.env.TSE_BASE_URL ?? "https://dadosabertos.tse.jus.br"; // TODO: confirmar
const UFS = [
  "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
  "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
  "SP", "SE", "TO",
];

async function listarArquivosDaUf(uf: string, ano: number): Promise<string[]> {
  // TODO: substituir pela chamada real ao catálogo CKAN do TSE, filtrando
  // por UF e ano, e devolvendo as URLs dos arquivos de BU.
  void BASE_URL;
  void ano;
  throw new Error(`listarArquivosDaUf(${uf}) ainda não implementado — ver comentário no topo do arquivo.`);
}

async function baixarEConverter(url: string, ano: number): Promise<BuNormalizado> {
  // TODO: baixar o arquivo, e então:
  //  - se for .bu binário: decodificar com src/lib/parser-bu.ts (ASN.1);
  //  - se for JSON/CSV: só mapear os campos para BuNormalizado.
  void url;
  void ano;
  throw new Error("baixarEConverter ainda não implementado.");
}

async function salvar(bu: BuNormalizado) {
  await prisma.buDigital.upsert({
    where: { uf_zona_secao_ano: { uf: bu.uf, zona: bu.zona, secao: bu.secao, ano: bu.ano } },
    create: {
      uf: bu.uf,
      municipio: bu.municipio,
      municipioCod: bu.municipioCod,
      zona: bu.zona,
      secao: bu.secao,
      hashBu: bu.hashBu,
      dataBu: new Date(bu.dataBu),
      votos: bu.votos,
      totalVotos: bu.totalVotos,
      fonteUrl: bu.fonteUrl,
      ano: bu.ano,
    },
    update: {
      votos: bu.votos,
      totalVotos: bu.totalVotos,
      hashBu: bu.hashBu,
      dataBu: new Date(bu.dataBu),
    },
  });
}

async function main() {
  const ano = Number(process.argv[2] ?? new Date().getFullYear());
  console.log(`Coletando BUs de ${ano}...`);

  for (const uf of UFS) {
    console.log(`UF ${uf}...`);
    const urls = await listarArquivosDaUf(uf, ano);
    for (const url of urls) {
      const bu = await baixarEConverter(url, ano);
      await salvar(bu);
    }
  }

  console.log("Coleta concluída.");
  await prisma.$disconnect();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
