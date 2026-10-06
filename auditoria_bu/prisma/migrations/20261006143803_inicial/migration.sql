-- CreateTable
CREATE TABLE "BuDigital" (
    "id" TEXT NOT NULL,
    "uf" TEXT NOT NULL,
    "municipio" TEXT NOT NULL,
    "municipioCod" TEXT NOT NULL,
    "zona" TEXT NOT NULL,
    "secao" TEXT NOT NULL,
    "hashBu" TEXT NOT NULL,
    "dataBu" TIMESTAMP(3) NOT NULL,
    "votos" JSONB NOT NULL,
    "totalVotos" INTEGER NOT NULL,
    "fonteUrl" TEXT NOT NULL,
    "ano" INTEGER NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "BuDigital_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ApuracaoOficial" (
    "id" TEXT NOT NULL,
    "nivel" TEXT NOT NULL,
    "uf" TEXT NOT NULL DEFAULT '',
    "municipio" TEXT NOT NULL DEFAULT '',
    "ano" INTEGER NOT NULL,
    "candidato" TEXT NOT NULL,
    "legenda" TEXT NOT NULL,
    "totalVotos" INTEGER NOT NULL,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ApuracaoOficial_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Verificacao" (
    "id" TEXT NOT NULL,
    "buDigitalId" TEXT NOT NULL,
    "criadoEm" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "fingerprint" TEXT NOT NULL,

    CONSTRAINT "Verificacao_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "RelatoDivergencia" (
    "id" TEXT NOT NULL,
    "uf" TEXT NOT NULL,
    "zona" TEXT NOT NULL,
    "secao" TEXT NOT NULL,
    "ano" INTEGER NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'PENDENTE',
    "evidenciaUrl" TEXT,
    "fingerprint" TEXT NOT NULL,
    "revisadoPor" TEXT,
    "revisadoEm" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "RelatoDivergencia_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "BuDigital_hashBu_key" ON "BuDigital"("hashBu");

-- CreateIndex
CREATE INDEX "BuDigital_uf_municipio_idx" ON "BuDigital"("uf", "municipio");

-- CreateIndex
CREATE UNIQUE INDEX "BuDigital_uf_zona_secao_ano_key" ON "BuDigital"("uf", "zona", "secao", "ano");

-- CreateIndex
CREATE INDEX "ApuracaoOficial_nivel_uf_ano_idx" ON "ApuracaoOficial"("nivel", "uf", "ano");

-- CreateIndex
CREATE UNIQUE INDEX "ApuracaoOficial_nivel_uf_municipio_ano_candidato_key" ON "ApuracaoOficial"("nivel", "uf", "municipio", "ano", "candidato");

-- CreateIndex
CREATE INDEX "Verificacao_buDigitalId_idx" ON "Verificacao"("buDigitalId");

-- CreateIndex
CREATE UNIQUE INDEX "Verificacao_buDigitalId_fingerprint_key" ON "Verificacao"("buDigitalId", "fingerprint");

-- CreateIndex
CREATE INDEX "RelatoDivergencia_uf_zona_secao_ano_idx" ON "RelatoDivergencia"("uf", "zona", "secao", "ano");

-- CreateIndex
CREATE INDEX "RelatoDivergencia_status_idx" ON "RelatoDivergencia"("status");

-- AddForeignKey
ALTER TABLE "Verificacao" ADD CONSTRAINT "Verificacao_buDigitalId_fkey" FOREIGN KEY ("buDigitalId") REFERENCES "BuDigital"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
