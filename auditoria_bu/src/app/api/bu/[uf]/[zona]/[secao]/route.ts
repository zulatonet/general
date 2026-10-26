import { prisma } from "@/lib/prisma";

// Retorna o BU DIGITAL BRUTO daquela seção — exatamente como baixado do
// TSE, nunca um valor somado/consolidado. É este dado que o cidadão compara
// com a cópia física afixada na sua seção eleitoral.
export async function GET(
  req: Request,
  { params }: { params: { uf: string; zona: string; secao: string } }
) {
  const { searchParams } = new URL(req.url);
  const ano = Number(searchParams.get("ano") ?? new Date().getFullYear());
  const turnoParam = searchParams.get("turno");
  const uf = params.uf.toUpperCase();

  // Sem turno explícito na URL: mostra o mais recente que existir pra essa
  // seção (2º turno, quando houver, senão 1º) — é o resultado mais atual.
  const bu = turnoParam
    ? await prisma.buDigital.findUnique({
        where: {
          uf_zona_secao_ano_turno: { uf, zona: params.zona, secao: params.secao, ano, turno: Number(turnoParam) },
        },
      })
    : await prisma.buDigital.findFirst({
        where: { uf, zona: params.zona, secao: params.secao, ano },
        orderBy: { turno: "desc" },
      });

  if (!bu) {
    return Response.json({ erro: "BU não encontrado para essa seção/ano/turno." }, { status: 404 });
  }

  const confirmacoes = await prisma.verificacao.count({ where: { buDigitalId: bu.id } });

  return Response.json({
    uf: bu.uf,
    municipio: bu.municipio,
    zona: bu.zona,
    secao: bu.secao,
    ano: bu.ano,
    turno: bu.turno,
    hashBu: bu.hashBu,
    dataBu: bu.dataBu,
    votos: bu.votos,
    totalVotos: bu.totalVotos,
    fonteUrl: bu.fonteUrl,
    confirmacoes,
  });
}
