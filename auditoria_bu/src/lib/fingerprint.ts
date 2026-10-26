import { createHash } from "crypto";

/**
 * Gera uma "impressão" anônima e irreversível a partir do IP + User-Agent,
 * só para limitar 1 ação por seção/dispositivo. Nunca armazenamos o IP em
 * si — só este hash, que não dá para voltar ao IP original.
 */
export function fingerprintDaRequisicao(req: Request): string {
  const ip =
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ??
    req.headers.get("x-real-ip") ??
    "desconhecido";
  const ua = req.headers.get("user-agent") ?? "";
  const sal = process.env.SESSION_SECRET ?? "sal-local-nao-use-em-producao";

  return createHash("sha256").update(`${sal}:${ip}:${ua}`).digest("hex");
}
