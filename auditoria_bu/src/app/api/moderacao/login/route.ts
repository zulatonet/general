import { timingSafeEqual } from "crypto";
import { criarTokenSessao, NOME_COOKIE } from "@/lib/auth-moderacao";
import { limitado } from "@/lib/limite-taxa";
import { fingerprintDaRequisicao } from "@/lib/fingerprint";

export async function POST(req: Request) {
  const fp = fingerprintDaRequisicao(req);
  if (limitado(`login-moderacao:${fp}`, 5, 60_000)) {
    return Response.json({ erro: "Muitas tentativas, aguarde um minuto." }, { status: 429 });
  }

  const senhaEsperada = process.env.MODERACAO_SENHA ?? "";
  const { senha } = await req.json().catch(() => ({ senha: "" }));

  const a = Buffer.from(String(senha ?? ""));
  const b = Buffer.from(senhaEsperada);
  const ok = senhaEsperada.length > 0 && a.length === b.length && timingSafeEqual(a, b);

  if (!ok) {
    return Response.json({ erro: "Senha incorreta." }, { status: 401 });
  }

  const token = criarTokenSessao();
  const resposta = Response.json({ ok: true });
  resposta.headers.set(
    "Set-Cookie",
    `${NOME_COOKIE}=${token}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=${12 * 60 * 60}`
  );
  return resposta;
}
