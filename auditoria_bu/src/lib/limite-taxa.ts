// Limitador de taxa simples em memória, por chave (ex.: fingerprint + rota).
// Suficiente para um único processo; não substitui um WAF/CDN na frente.

const janelas = new Map<string, { contagem: number; expiraEm: number }>();

export function limitado(chave: string, max: number, janelaMs: number): boolean {
  const agora = Date.now();
  const atual = janelas.get(chave);

  if (!atual || atual.expiraEm < agora) {
    janelas.set(chave, { contagem: 1, expiraEm: agora + janelaMs });
    return false;
  }
  atual.contagem += 1;
  return atual.contagem > max;
}

// Limpa entradas velhas de tempos em tempos para não vazar memória.
setInterval(() => {
  const agora = Date.now();
  for (const [chave, v] of Array.from(janelas.entries())) {
    if (v.expiraEm < agora) janelas.delete(chave);
  }
}, 60_000).unref?.();
