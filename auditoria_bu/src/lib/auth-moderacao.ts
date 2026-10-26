import { createHmac, timingSafeEqual } from "crypto";

const COOKIE = "moderacao_sessao";

function assinar(valor: string): string {
  const segredo = process.env.SESSION_SECRET ?? "";
  return createHmac("sha256", segredo).update(valor).digest("hex");
}

export function criarTokenSessao(): string {
  const payload = `moderador:${Date.now()}`;
  return `${payload}.${assinar(payload)}`;
}

export function tokenValido(token: string | undefined | null): boolean {
  if (!token) return false;
  const [payload, assinatura] = token.split(".");
  if (!payload || !assinatura) return false;
  const esperado = assinar(payload);
  if (esperado.length !== assinatura.length) return false;
  if (!timingSafeEqual(Buffer.from(esperado), Buffer.from(assinatura))) return false;

  // Sessão expira em 12h.
  const criadoEm = Number(payload.split(":")[1]);
  return Date.now() - criadoEm < 12 * 60 * 60 * 1000;
}

export function autenticado(req: Request): boolean {
  const cookieHeader = req.headers.get("cookie") ?? "";
  const match = cookieHeader.match(new RegExp(`${COOKIE}=([^;]+)`));
  return tokenValido(match?.[1]);
}

export const NOME_COOKIE = COOKIE;
