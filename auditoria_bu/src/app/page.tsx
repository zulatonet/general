"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const router = useRouter();
  const [uf, setUf] = useState("");
  const [zona, setZona] = useState("");
  const [secao, setSecao] = useState("");

  function consultar(e: React.FormEvent) {
    e.preventDefault();
    if (!uf || !zona || !secao) return;
    router.push(`/bu/${uf.toUpperCase()}/${zona}/${secao}`);
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-2xl font-bold">Auditoria Cidadã de BUs</h1>
      <p className="mt-2 text-gray-600">
        Consulte o Boletim de Urna digital oficial da sua seção eleitoral — o
        mesmo dado que o TSE já disponibiliza publicamente — e compare com a
        cópia física afixada no seu local de votação.
      </p>

      <form onSubmit={consultar} className="mt-8 grid grid-cols-3 gap-3">
        <input
          className="rounded border px-3 py-2"
          placeholder="UF (ex.: MG)"
          maxLength={2}
          value={uf}
          onChange={(e) => setUf(e.target.value)}
        />
        <input
          className="rounded border px-3 py-2"
          placeholder="Zona"
          value={zona}
          onChange={(e) => setZona(e.target.value)}
        />
        <input
          className="rounded border px-3 py-2"
          placeholder="Seção"
          value={secao}
          onChange={(e) => setSecao(e.target.value)}
        />
        <button
          type="submit"
          className="col-span-3 rounded bg-black px-4 py-2 text-white hover:bg-gray-800"
        >
          Consultar meu BU
        </button>
      </form>

      <p className="mt-6 text-sm text-gray-500">
        Não sabe sua zona e seção? Elas estão no seu título de eleitor ou no
        comprovante de votação.
      </p>

      <hr className="my-10" />

      <h2 className="text-lg font-semibold">Sobre este site</h2>
      <p className="mt-2 text-sm text-gray-600">
        Este site espelha dados públicos do TSE (dadosabertos.tse.jus.br) —
        ele não realiza nenhuma contagem independente de votos. Os totais por
        estado/município/nacional exibidos aqui são os mesmos totais oficiais,
        apenas pré-calculados para carregar rápido. O valor deste site está em
        facilitar que você compare o BU da sua seção com a cópia física
        afixada lá — nunca em substituir a apuração oficial.
      </p>
    </main>
  );
}
