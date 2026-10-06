/**
 * Popula alguns BUs de exemplo (dados FICTÍCIOS) para testar o site
 * localmente sem depender do coletor real. Nunca rode isto em produção.
 */
import { prisma } from "../src/lib/prisma";

async function main() {
  const ano = new Date().getFullYear();

  await prisma.buDigital.upsert({
    where: { uf_zona_secao_ano: { uf: "MG", zona: "0001", secao: "0010", ano } },
    create: {
      uf: "MG",
      municipio: "Manhuaçu",
      municipioCod: "41238",
      zona: "0001",
      secao: "0010",
      hashBu: "exemplo-hash-0010",
      dataBu: new Date(),
      votos: { "13": 150, "22": 120, branco: 5, nulo: 3 },
      totalVotos: 278,
      fonteUrl: "https://dadosabertos.tse.jus.br/exemplo",
      ano,
    },
    update: {},
  });

  console.log("Seed de exemplo criado.");
  await prisma.$disconnect();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
