import { z } from "zod";
import { prisma } from "@/lib/prisma";
import { fingerprintDaRequisicao } from "@/lib/fingerprint";
import { limitado } from "@/lib/limite-taxa";

const corpo = z.object({
  uf: z.string().length(2),
  zona: z.string().min(1).max(10),
  secao: z.string().min(1).max(10),
  ano: z.number().int(),
});

// "Conferi meu BU físico e bate com o digital" — único contador público do
// sistema. É seguro mostrar: só soma confirmações, nunca acusações, então
// não dá pra virar "prova" de fraude mesmo em massa.
export async function POST(req: Request) {
  const fp = fingerprintDaRequisicao(req);
  if (limitado(`verificar:${fp}`, 30, 60_000)) {
    return Response.json({ erro: "Muitas requisições, tente novamente em instantes." }, { status: 429 });
  }

  const dados = corpo.safeParse(await req.json().catch(() => null));
  if (!dados.success) {
    return Response.json({ erro: "Dados inválidos." }, { status: 400 });
  }
  const { uf, zona, secao, ano } = dados.data;

  const bu = await prisma.buDigital.findUnique({
    where: { uf_zona_secao_ano: { uf: uf.toUpperCase(), zona, secao, ano } },
  });
  if (!bu) {
    return Response.json({ erro: "BU não encontrado." }, { status: 404 });
  }

  await prisma.verificacao.upsert({
    where: { buDigitalId_fingerprint: { buDigitalId: bu.id, fingerprint: fp } },
    create: { buDigitalId: bu.id, fingerprint: fp },
    update: {},
  });

  const confirmacoes = await prisma.verificacao.count({ where: { buDigitalId: bu.id } });
  return Response.json({ ok: true, confirmacoes });
}
