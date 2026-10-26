-- DropIndex
DROP INDEX "ApuracaoOficial_nivel_uf_ano_idx";

-- DropIndex
DROP INDEX "ApuracaoOficial_nivel_uf_municipio_ano_candidato_key";

-- DropIndex
DROP INDEX "BuDigital_uf_zona_secao_ano_key";

-- AlterTable
-- Adiciona com DEFAULT 1 pra não quebrar linhas que já existiam (coletadas
-- antes do turno existir, sempre eram 1º turno), depois tira o default pra
-- bater com o schema (toda coleta nova já manda o turno explicitamente).
ALTER TABLE "ApuracaoOficial" ADD COLUMN     "turno" INTEGER NOT NULL DEFAULT 1;
ALTER TABLE "ApuracaoOficial" ALTER COLUMN "turno" DROP DEFAULT;

ALTER TABLE "BuDigital" ADD COLUMN     "turno" INTEGER NOT NULL DEFAULT 1;
ALTER TABLE "BuDigital" ALTER COLUMN "turno" DROP DEFAULT;

ALTER TABLE "RelatoDivergencia" ADD COLUMN     "turno" INTEGER NOT NULL DEFAULT 1;
ALTER TABLE "RelatoDivergencia" ALTER COLUMN "turno" DROP DEFAULT;

-- CreateIndex
CREATE INDEX "ApuracaoOficial_nivel_uf_ano_turno_idx" ON "ApuracaoOficial"("nivel", "uf", "ano", "turno");

-- CreateIndex
CREATE UNIQUE INDEX "ApuracaoOficial_nivel_uf_municipio_ano_turno_candidato_key" ON "ApuracaoOficial"("nivel", "uf", "municipio", "ano", "turno", "candidato");

-- CreateIndex
CREATE UNIQUE INDEX "BuDigital_uf_zona_secao_ano_turno_key" ON "BuDigital"("uf", "zona", "secao", "ano", "turno");
