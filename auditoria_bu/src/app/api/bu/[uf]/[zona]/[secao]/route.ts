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
  const uf = params.uf.toUpperCase();

  const bu = await prisma.buDigital.findUnique({
    where: { uf_zona_secao_ano: { uf, zona: params.zona, secao: params.secao, ano } },
  });

  if (!bu) {
    return Response.json({ erro: "BU não encontrado para essa seção/ano." }, { status: 404 });
  }

  const confirmacoes = await prisma.verificacao.count({ where: { buDigitalId: bu.id } });

  return Response.json({
    uf: bu.uf,
    municipio: bu.municipio,
    zona: bu.zona,
    secao: bu.secao,
    ano: bu.ano,
    hashBu: bu.hashBu,
    dataBu: bu.dataBu,
    votos: bu.votos,
    totalVotos: bu.totalVotos,
    fonteUrl: bu.fonteUrl,
    confirmacoes,
  });
}
