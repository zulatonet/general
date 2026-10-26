FROM debian:bookworm-slim

# Navegador + monitor virtual + placa de som virtual + ffmpeg (sem nada de interface gráfica real).
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium xvfb pulseaudio pulseaudio-utils ffmpeg \
      fonts-noto-color-emoji fonts-dejavu-core fonts-liberation \
      ca-certificates curl procps tini \
    && rm -rf /var/lib/apt/lists/*

COPY iniciar.sh /usr/local/bin/iniciar.sh
# Músicas enviadas pelo GitHub (pasta musicas/). O volume do Easypanel, se houver, fica em /musicas.
COPY musicas /musicas_repo
RUN chmod 755 /usr/local/bin/iniciar.sh \
    && useradd --create-home --uid 10001 live \
    && mkdir -p /musicas && chown live:live /musicas

USER live
WORKDIR /home/live

# Não é um serviço web: o "saudável" aqui é o ffmpeg estar rodando.
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s --retries=3 \
  CMD pgrep -x ffmpeg >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/local/bin/iniciar.sh"]
