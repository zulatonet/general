import { prisma } from "@/lib/prisma";

// Totais do TSE, sempre identificados como dados oficiais agregados — isto
// NÃO é uma "apuração paralela", é a mesma soma que o TSE já publica,
// só pré-calculada (ver cron em scripts/totalizar.ts) para não pesar a
// consulta em tempo real.
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const nivel = (searchParams.get("nivel") ?? "NACIONAL").toUpperCase();
  const uf = searchParams.get("uf")?.toUpperCase() ?? "";
  const municipio = searchParams.get("municipio") ?? "";
  const ano = Number(searchParams.get("ano") ?? new Date().getFullYear());

  if (!["NACIONAL", "ESTADO", "MUNICIPIO"].includes(nivel)) {
    return Response.json({ erro: "nivel inválido" }, { status: 400 });
  }
  if (nivel === "ESTADO" && !uf) {
    return Response.json({ erro: "uf obrigatória para nivel=ESTADO" }, { status: 400 });
  }
  if (nivel === "MUNICIPIO" && (!uf || !municipio)) {
    return Response.json({ erro: "uf e municipio obrigatórios para nivel=MUNICIPIO" }, { status: 400 });
  }

  const linhas = await prisma.apuracaoOficial.findMany({
    where: { nivel, ano, uf, municipio },
    orderBy: { totalVotos: "desc" },
  });

  return Response.json({
    fonte: "Totalização oficial do TSE (dadosabertos.tse.jus.br), espelhada aqui.",
    nivel,
    uf,
    municipio,
    ano,
    resultados: linhas,
  });
}
