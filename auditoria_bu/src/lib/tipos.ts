// Formato normalizado de um BU, depois de baixado/convertido, pronto para
// salvar no banco. O coletor (scripts/baixar-bus.ts) é quem produz isto,
// seja a partir do .bu binário (ASN.1) ou do espelho em JSON do TSE.
export type BuNormalizado = {
  uf: string;
  municipio: string;
  municipioCod: string;
  zona: string;
  secao: string;
  hashBu: string;
  dataBu: string; // ISO 8601
  votos: Record<string, number>; // chave = número do candidato, "branco", "nulo"
  totalVotos: number;
  fonteUrl: string;
  ano: number;
};
