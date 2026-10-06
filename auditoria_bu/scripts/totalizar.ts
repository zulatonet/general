/**
 * Recalcula a tabela ApuracaoOficial a partir dos BuDigital já salvos.
 * Isto é um ESPELHO dos totais do TSE (soma dos BUs que o próprio TSE
 * publicou) — não uma apuração independente. Rode via cron (ex.: a cada
 * 5 min no dia da eleição; 1x/dia fora do período eleitoral).
 */
import { prisma } from "../src/lib/prisma";

async function totalizarAno(ano: number) {
  const bus = await prisma.buDigital.findMany({ where: { ano } });

  type Chave = string; // `${nivel}|${uf}|${municipio}|${candidato}`
  const somas = new Map<Chave, number>();

  for (const bu of bus) {
    const votos = bu.votos as Record<string, number>;
    for (const [candidato, qtd] of Object.entries(votos)) {
      for (const [nivel, uf, municipio] of [
        ["NACIONAL", "", ""],
        ["ESTADO", bu.uf, ""],
        ["MUNICIPIO", bu.uf, bu.municipio],
      ] as const) {
        const chave = `${nivel}|${uf}|${municipio}|${candidato}`;
        somas.set(chave, (somas.get(chave) ?? 0) + qtd);
      }
    }
  }

  for (const [chave, totalVotos] of Array.from(somas.entries())) {
    const [nivel, uf, municipio, candidato] = chave.split("|");
    await prisma.apuracaoOficial.upsert({
      where: {
        nivel_uf_municipio_ano_candidato: { nivel, uf, municipio, ano, candidato },
      },
      create: {
        nivel,
        uf,
        municipio,
        ano,
        candidato,
        legenda: candidato, // TODO: mapear número -> nome do candidato/coligação
        totalVotos,
      },
      update: { totalVotos },
    });
  }

  console.log(`Totalização de ${ano}: ${somas.size} linhas atualizadas.`);
}

async function main() {
  const ano = Number(process.argv[2] ?? new Date().getFullYear());
  await totalizarAno(ano);
  await prisma.$disconnect();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
