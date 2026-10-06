import { prisma } from "@/lib/prisma";
import { autenticado } from "@/lib/auth-moderacao";

// Lista de relatos pendentes — só acessível autenticado. Nunca exposta
// publicamente, nem agregada, nem em ranking.
export async function GET(req: Request) {
  if (!autenticado(req)) {
    return Response.json({ erro: "Não autenticado." }, { status: 401 });
  }

  const relatos = await prisma.relatoDivergencia.findMany({
    where: { status: "PENDENTE" },
    orderBy: { createdAt: "asc" },
    take: 100,
  });

  return Response.json({ relatos });
}
