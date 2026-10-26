/**
 * Lê o .csv de dentro de um .zip do TSE SEM carregar o arquivo
 * descompactado inteiro na memória — estados grandes passam de 800 MB
 * descompactados. `unzipper.Open.buffer` só lê o índice central do zip
 * (barato); a descompactação de verdade acontece aos poucos, conforme o
 * readline consome o stream.
 */
import * as readline from "readline";
import * as unzipper from "unzipper";

export async function listarArquivosZip(buffer: Buffer): Promise<{ nome: string; bytes: number }[]> {
  const diretorio = await unzipper.Open.buffer(buffer);
  return diretorio.files.map((f) => ({ nome: f.path, bytes: f.uncompressedSize }));
}

export async function* linhasCsvDoZip(buffer: Buffer): AsyncGenerator<string> {
  const diretorio = await unzipper.Open.buffer(buffer);
  const entrada = diretorio.files.find((f) => /\.csv$/i.test(f.path));
  if (!entrada) {
    throw new Error(`Nenhum .csv dentro do zip. Arquivos: ${diretorio.files.map((f) => f.path).join(", ")}`);
  }

  const stream = entrada.stream();
  stream.setEncoding("latin1"); // TSE publica em Latin-1/ISO-8859-1
  const rl = readline.createInterface({ input: stream, crlfDelay: Infinity });
  try {
    for await (const linha of rl) {
      yield linha;
    }
  } finally {
    // Se quem consome parar de ler antes do fim (ex.: break numa
    // inspeção), fecha tudo em vez de deixar o stream pendurado.
    rl.close();
    stream.destroy();
  }
}
