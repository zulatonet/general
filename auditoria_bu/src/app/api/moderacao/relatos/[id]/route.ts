import { z } from "zod";
import { prisma } from "@/lib/prisma";
import { autenticado } from "@/lib/auth-moderacao";

const corpo = z.object({ status: z.enum(["CONFIRMADA", "REJEITADA"]) });

export async function POST(req: Request, { params }: { params: { id: string } }) {
  if (!autenticado(req)) {
    return Response.json({ erro: "Não autenticado." }, { status: 401 });
  }

  const dados = corpo.safeParse(await req.json().catch(() => null));
  if (!dados.success) {
    return Response.json({ erro: "Dados inválidos." }, { status: 400 });
  }

  await prisma.relatoDivergencia.update({
    where: { id: params.id },
    data: { status: dados.data.status, revisadoEm: new Date(), revisadoPor: "moderador" },
  });

  return Response.json({ ok: true });
}
