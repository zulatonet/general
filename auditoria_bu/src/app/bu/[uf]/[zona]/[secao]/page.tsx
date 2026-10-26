"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

type BuDigital = {
  uf: string;
  municipio: string;
  zona: string;
  secao: string;
  ano: number;
  turno: number;
  hashBu: string;
  dataBu: string;
  votos: Record<string, number>;
  totalVotos: number;
  fonteUrl: string;
  confirmacoes: number;
};

export default function PaginaSecao({
  params,
}: {
  params: { uf: string; zona: string; secao: string };
}) {
  const ano = new Date().getFullYear();
  const searchParams = useSearchParams();
  const turnoForcado = searchParams.get("turno"); // null = deixa o servidor escolher o mais recente
  const [bu, setBu] = useState<BuDigital | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [mensagem, setMensagem] = useState<string | null>(null);

  useEffect(() => {
    setBu(null);
    setErro(null);
    const qs = new URLSearchParams({ ano: String(ano) });
    if (turnoForcado) qs.set("turno", turnoForcado);
    fetch(`/api/bu/${params.uf}/${params.zona}/${params.secao}?${qs}`)
      .then((r) => r.json())
      .then((d) => (d.erro ? setErro(d.erro) : setBu(d)));
  }, [params.uf, params.zona, params.secao, ano, turnoForcado]);

  async function confirmar() {
    if (!bu) return;
    const r = await fetch("/api/verificar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ uf: params.uf, zona: params.zona, secao: params.secao, ano, turno: bu.turno }),
    });
    const d = await r.json();
    if (d.ok) {
      setBu((b) => (b ? { ...b, confirmacoes: d.confirmacoes } : b));
      setMensagem("Obrigado por conferir!");
    } else {
      setMensagem(d.erro ?? "Não foi possível registrar.");
    }
  }

  async function relatarDivergencia() {
    if (!bu) return;
    const r = await fetch("/api/relato", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ uf: params.uf, zona: params.zona, secao: params.secao, ano, turno: bu.turno }),
    });
    const d = await r.json();
    setMensagem(d.mensagem ?? d.erro);
  }

  if (erro) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-12">
        <p className="text-red-600">{erro}</p>
      </main>
    );
  }
  if (!bu) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-12">
        <p>Carregando...</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-xl font-bold">
        {bu.uf} · {bu.municipio} · Zona {bu.zona} · Seção {bu.secao} · {bu.ano}
      </h1>

      <div className="mt-2 flex items-center gap-2 text-sm">
        <span className="rounded bg-black px-2 py-0.5 text-white">{bu.turno}º turno</span>
        <Link href={`?turno=1`} className="text-blue-700 underline">
          ver 1º turno
        </Link>
        <Link href={`?turno=2`} className="text-blue-700 underline">
          ver 2º turno
        </Link>
      </div>

      <p className="mt-4 rounded bg-yellow-50 p-3 text-sm text-yellow-900">
        Compare os números abaixo com a cópia física do Boletim de Urna
        afixada na sua seção eleitoral no dia da votação.
      </p>

      <table className="mt-6 w-full border-collapse text-sm">
        <tbody>
          {Object.entries(bu.votos).map(([chave, votos]) => (
            <tr key={chave} className="border-b">
              <td className="py-1">{chave}</td>
              <td className="py-1 text-right font-mono">{votos}</td>
            </tr>
          ))}
          <tr className="font-semibold">
            <td className="py-1">Total de votos</td>
            <td className="py-1 text-right font-mono">{bu.totalVotos}</td>
          </tr>
        </tbody>
      </table>

      <p className="mt-4 text-xs text-gray-500">
        Hash do BU: <span className="font-mono">{bu.hashBu}</span>
        <br />
        Data: {new Date(bu.dataBu).toLocaleString("pt-BR")}
        <br />
        <a href={bu.fonteUrl} className="underline" target="_blank" rel="noreferrer">
          Ver arquivo original no TSE
        </a>
      </p>

      <div className="mt-8 flex gap-3">
        <button onClick={confirmar} className="rounded bg-green-600 px-4 py-2 text-white">
          ✓ Conferi, está de acordo
        </button>
        <button onClick={relatarDivergencia} className="rounded border px-4 py-2">
          Reportar divergência
        </button>
      </div>

      <p className="mt-3 text-sm text-gray-600">{bu.confirmacoes} pessoa(s) confirmaram.</p>
      {mensagem && <p className="mt-3 text-sm">{mensagem}</p>}

      <p className="mt-8 text-xs text-gray-400">
        Relatos de divergência não aparecem publicamente: eles vão para uma
        fila de revisão humana antes de qualquer número ser exibido. Isso
        evita que cliques sem verificação sejam usados como &ldquo;prova&rdquo;
        de fraude — veja por quê no README do projeto.
      </p>
    </main>
  );
}
