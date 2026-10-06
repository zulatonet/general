"use client";

import { useEffect, useState } from "react";

type Relato = {
  id: string;
  uf: string;
  zona: string;
  secao: string;
  ano: number;
  status: string;
  createdAt: string;
};

export default function Moderacao() {
  const [senha, setSenha] = useState("");
  const [logado, setLogado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [relatos, setRelatos] = useState<Relato[]>([]);

  async function carregar() {
    const r = await fetch("/api/moderacao/relatos");
    if (r.status === 401) {
      setLogado(false);
      return;
    }
    const d = await r.json();
    setRelatos(d.relatos ?? []);
    setLogado(true);
  }

  useEffect(() => {
    carregar();
  }, []);

  async function entrar(e: React.FormEvent) {
    e.preventDefault();
    setErro(null);
    const r = await fetch("/api/moderacao/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ senha }),
    });
    if (r.ok) {
      await carregar();
    } else {
      const d = await r.json();
      setErro(d.erro ?? "Erro ao entrar.");
    }
  }

  async function decidir(id: string, status: "CONFIRMADA" | "REJEITADA") {
    await fetch(`/api/moderacao/relatos/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    setRelatos((rs) => rs.filter((r) => r.id !== id));
  }

  if (!logado) {
    return (
      <main className="mx-auto max-w-sm px-4 py-12">
        <h1 className="text-xl font-bold">Moderação</h1>
        <form onSubmit={entrar} className="mt-6 space-y-3">
          <input
            type="password"
            className="w-full rounded border px-3 py-2"
            placeholder="Senha"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
          />
          <button type="submit" className="w-full rounded bg-black px-4 py-2 text-white">
            Entrar
          </button>
          {erro && <p className="text-sm text-red-600">{erro}</p>}
        </form>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-xl font-bold">Relatos pendentes</h1>
      <p className="mt-2 text-sm text-gray-600">
        Nenhum relato aparece publicamente até ser confirmado aqui.
      </p>

      <ul className="mt-6 divide-y">
        {relatos.map((r) => (
          <li key={r.id} className="flex items-center justify-between py-3">
            <span>
              {r.uf} · Zona {r.zona} · Seção {r.secao} · {r.ano}
            </span>
            <span className="flex gap-2">
              <button
                onClick={() => decidir(r.id, "CONFIRMADA")}
                className="rounded bg-green-600 px-3 py-1 text-sm text-white"
              >
                Confirmar
              </button>
              <button
                onClick={() => decidir(r.id, "REJEITADA")}
                className="rounded border px-3 py-1 text-sm"
              >
                Rejeitar
              </button>
            </span>
          </li>
        ))}
        {relatos.length === 0 && <p className="py-6 text-sm text-gray-500">Nenhum relato pendente.</p>}
      </ul>
    </main>
  );
}
