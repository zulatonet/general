"""Tela de Pixels: uma tela coletiva onde cada usuário pinta 1 pixel a cada 10 s.

A imagem fica na memória (1 byte por pixel = índice da paleta) e é salva no
banco a cada poucos segundos. As mudanças vão para todos em lotes pequenos
(a cada 0,25 s) pelo WebSocket. Ninguém é dono de pixel: qualquer um pinta
por cima.
"""
import time

import db

LARGURA = 320
ALTURA = 180
ESPERA_S = 10
SALVAR_A_CADA_S = 5

# Paleta de 16 cores (a clássica do r/place). O índice é o que fica guardado.
PALETA = [
    "#FFFFFF", "#E4E4E4", "#888888", "#222222",
    "#FFA7D1", "#E50000", "#E59500", "#A06A42",
    "#E5D900", "#94E044", "#02BE01", "#00D3DD",
    "#0083C7", "#0000EA", "#CF6EE4", "#820080",
]
BRANCO, PRETO, VERDE = 0, 3, 10

# Fonte 5x7 só com as letras do desenho inicial.
FONTE = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "C": [".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "G": [".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": [".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "N": ["#...#", "##..#", "##..#", "#.#.#", "#..##", "#..##", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "X": ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    "0": [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    " ": ["....."] * 7,
}


def _escrever(pixels, texto, y, cor, escala=2):
    """Escreve `texto` centralizado na linha `y` (topo), em letras de pixel."""
    avanco = 6 * escala  # 5 colunas + 1 de espaço
    largura_texto = len(texto) * avanco - escala
    x0 = (LARGURA - largura_texto) // 2
    for i, letra in enumerate(texto):
        for linha, bits in enumerate(FONTE[letra]):
            for coluna, bit in enumerate(bits):
                if bit != "#":
                    continue
                for dy in range(escala):
                    for dx in range(escala):
                        x = x0 + i * avanco + coluna * escala + dx
                        py = y + linha * escala + dy
                        if 0 <= x < LARGURA and 0 <= py < ALTURA:
                            pixels[py * LARGURA + x] = cor


def desenho_inicial():
    """Tela branca com 'PREENCHA SEUS PIXELS / A CADA 10 SEGUNDOS' no centro."""
    pixels = bytearray([BRANCO]) * (LARGURA * ALTURA)
    altura_bloco = 7 * 2 * 2 + 6  # duas linhas de 14 px + 6 de espaço
    y0 = (ALTURA - altura_bloco) // 2
    _escrever(pixels, "PREENCHA SEUS PIXELS", y0, PRETO)
    _escrever(pixels, "A CADA 10 SEGUNDOS", y0 + 20, VERDE)
    return pixels


INICIAL = desenho_inicial()


class Tela:
    def __init__(self):
        self.pixels = bytearray(INICIAL)
        self.para_enviar = []   # [(x, y, cor)] ainda não transmitidos
        self.para_gravar = []   # [(x, y, cor, usuario_id)] ainda não no histórico
        self.sujo = False
        self.ultimo_salvo = time.monotonic()
        self.ultimo_pixel = {}  # usuario_id -> momento (monotonic) do último pixel

    async def carregar(self):
        row = await db.carregar_tela()
        if row and row["largura"] == LARGURA and row["altura"] == ALTURA and len(row["pixels"]) == LARGURA * ALTURA:
            self.pixels = bytearray(row["pixels"])
        else:
            self.pixels = bytearray(INICIAL)
            await db.salvar_tela(LARGURA, ALTURA, self.pixels)

    def espera_restante(self, usuario_id):
        ultimo = self.ultimo_pixel.get(usuario_id)
        return 0.0 if ultimo is None else max(0.0, ESPERA_S - (time.monotonic() - ultimo))

    @staticmethod
    def valido(x, y, cor):
        return (all(isinstance(v, int) and not isinstance(v, bool) for v in (x, y, cor))
                and 0 <= x < LARGURA and 0 <= y < ALTURA and 0 <= cor < len(PALETA))

    def pintar(self, usuario_id, x, y, cor):
        """Pinta se o usuário já pode. Retorna os segundos que faltam (0 = pintou)."""
        restante = self.espera_restante(usuario_id)
        if restante > 0:
            return restante
        self.ultimo_pixel[usuario_id] = time.monotonic()
        self.aplicar([(x, y, cor)], usuario_id)
        return 0.0

    def aplicar(self, alteracoes, usuario_id):
        """Aplica [(x, y, cor)] sem espera (usado também pela moderação)."""
        for x, y, cor in alteracoes:
            self.pixels[y * LARGURA + x] = cor
            self.para_enviar.append((x, y, cor))
            self.para_gravar.append((x, y, cor, usuario_id))
        self.sujo = True

    async def descarregar(self, transmitir):
        """Transmite as mudanças pendentes, grava o histórico e salva a tela de tempos em tempos."""
        # Grava o histórico antes de avisar, para "quem pintou" já responder certo.
        if self.para_gravar:
            lote, self.para_gravar = self.para_gravar, []
            await db.registrar_pixels(lote)
        if self.para_enviar:
            lote, self.para_enviar = self.para_enviar, []
            await transmitir({"tipo": "pixels", "p": lote})
        if self.sujo and time.monotonic() - self.ultimo_salvo >= SALVAR_A_CADA_S:
            await self.salvar()

    async def salvar(self):
        self.sujo = False
        self.ultimo_salvo = time.monotonic()
        await db.salvar_tela(LARGURA, ALTURA, self.pixels)

    def limpar_esperas(self):
        agora = time.monotonic()
        for uid in [u for u, t in self.ultimo_pixel.items() if agora - t > ESPERA_S]:
            del self.ultimo_pixel[uid]
