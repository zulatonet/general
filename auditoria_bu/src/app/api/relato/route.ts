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

// Relato de "algo não bate com o BU físico". Propositalmente SEM campo de
// comentário e SEM qualquer contador público: fica "PENDENTE" até alguém
// da moderação revisar. Nunca vira ranking, nunca vira número exibido
// sem revisão humana — ver README para o porquê dessa escolha de design.
export async function POST(req: Request) {
  const fp = fingerprintDaRequisicao(req);
  if (limitado(`relato:${fp}`, 10, 60_000)) {
    return Response.json({ erro: "Muitas requisições, tente novamente em instantes." }, { status: 429 });
  }
  // Limite adicional, mais apertado, por seção+dispositivo nas últimas 24h.
  const dados = corpo.safeParse(await req.json().catch(() => null));
  if (!dados.success) {
    return Response.json({ erro: "Dados inválidos." }, { status: 400 });
  }
  const { uf, zona, secao, ano } = dados.data;

  if (limitado(`relato:${fp}:${uf}:${zona}:${secao}`, 1, 24 * 60 * 60_000)) {
    return Response.json(
      { erro: "Você já relatou essa seção nas últimas 24h." },
      { status: 429 }
    );
  }

  await prisma.relatoDivergencia.create({
    data: { uf: uf.toUpperCase(), zona, secao, ano, fingerprint: fp },
  });

  return Response.json({
    ok: true,
    mensagem: "Relato registrado para revisão. Ele não aparece publicamente até ser confirmado.",
  });
}
