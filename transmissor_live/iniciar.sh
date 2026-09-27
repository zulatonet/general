#!/usr/bin/env bash
# Transmissor da live: abre a página da live num Chromium com tela e som
# virtuais, mistura com músicas de fundo e manda tudo para o YouTube (RTMP).
#
#   Xvfb (monitor virtual) ──> Chromium em tela cheia com a LIVE_URL
#   PulseAudio (placa de som virtual "live") <── som da página (áudios, "plim")
#   ffmpeg: filma a tela + som da página + músicas em loop ──> RTMP
#
# Cada peça que cair é reiniciada sozinha.
set -u

# ---------------- configuração (variáveis de ambiente) ----------------
# Aceita "FPS=15   # comentário" colado no painel: corta o comentário e os espaços.
limpar() {
  local nome v
  for nome in "$@"; do
    v="${!nome-}"
    [ "$nome" != LIVE_URL ] && v="${v%%#*}"          # na LIVE_URL o # não é comentário
    v="${v#"${v%%[![:space:]]*}"}"; v="${v%"${v##*[![:space:]]}"}"
    printf -v "$nome" '%s' "$v"
  done
}
limpar LIVE_URL YOUTUBE_KEY RTMP_URL RTMP_EXTRA RESOLUCAO FPS VIDEO_KBPS AUDIO_KBPS PRESET \
       MUSICA_VOLUME ABAIXAR_MUSICA PASTA_MUSICAS MUSICAS_URLS REINICIAR_NAVEGADOR_H

LIVE_URL="${LIVE_URL:-}"                          # link secreto da página da live (/live link no chat)
YOUTUBE_KEY="${YOUTUBE_KEY:-}"                    # chave de transmissão do YouTube
RTMP_URL="${RTMP_URL:-rtmp://a.rtmp.youtube.com/live2/${YOUTUBE_KEY}}"
RTMP_EXTRA="${RTMP_EXTRA:-}"                      # outros destinos ao mesmo tempo (Rumble, Twitch...), separados por vírgula
RESOLUCAO="${RESOLUCAO:-1280x720}"
FPS="${FPS:-30}"
VIDEO_KBPS="${VIDEO_KBPS:-2500}"
AUDIO_KBPS="${AUDIO_KBPS:-160}"
PRESET="${PRESET:-veryfast}"                      # ultrafast gasta menos CPU, com imagem um pouco pior
MUSICA_VOLUME="${MUSICA_VOLUME:-0.35}"            # 0 a 1
ABAIXAR_MUSICA="${ABAIXAR_MUSICA:-1}"             # 1 = a música baixa sozinha quando alguém fala
PASTA_MUSICAS="${PASTA_MUSICAS:-/musicas /musicas_repo}"   # pastas separadas por espaço
MUSICAS_URLS="${MUSICAS_URLS:-}"                  # links diretos de .mp3 (separados por espaço ou vírgula)
REINICIAR_NAVEGADOR_H="${REINICIAR_NAVEGADOR_H:-12}"   # recarrega o navegador de tempos em tempos (0 = nunca)
CHROMIUM_BIN="${CHROMIUM_BIN:-chromium}"

LARGURA="${RESOLUCAO%x*}"
ALTURA="${RESOLUCAO#*x}"
export DISPLAY=":99"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-$(id -u)}"
TRABALHO="${TRABALHO:-/tmp/transmissor}"
mkdir -p "$XDG_RUNTIME_DIR" "$TRABALHO" && chmod 700 "$XDG_RUNTIME_DIR"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [transmissor] $*"; }

if [ -z "$LIVE_URL" ]; then
  log "ERRO: defina LIVE_URL (no chat, digite /live link e copie o endereço)."
  exit 1
fi
if [ -z "$YOUTUBE_KEY" ] && [ "${RTMP_URL}" = "rtmp://a.rtmp.youtube.com/live2/" ]; then
  log "ERRO: defina YOUTUBE_KEY (YouTube Studio > Transmitir ao vivo > Chave da transmissão)."
  exit 1
fi

# Destinos: o principal + os extras. Um só vai direto; vários usam o "tee"
# (o vídeo é codificado uma vez e enviado a todos).
DESTINOS=("$RTMP_URL")
for d in ${RTMP_EXTRA//,/ }; do DESTINOS+=("$d"); done
ocultar() { echo "${1%/*}/****"; }

PIDS=()
encerrar() {
  log "encerrando..."
  for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
  pkill -P $$ 2>/dev/null
  exit 0
}
trap encerrar TERM INT

# ---------------- monitor virtual ----------------
rm -f /tmp/.X99-lock
Xvfb :99 -screen 0 "${LARGURA}x${ALTURA}x24" -nolisten tcp -ac >/dev/null 2>&1 &
PIDS+=($!)
for _ in $(seq 1 50); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.1; done
log "monitor virtual ${RESOLUCAO} pronto"

# ---------------- placa de som virtual ----------------
pulseaudio --daemonize=yes --exit-idle-time=-1 --disallow-exit --log-target=stderr >/dev/null 2>&1 \
  || log "aviso: pulseaudio não iniciou em modo daemon"
for _ in $(seq 1 50); do pactl info >/dev/null 2>&1 && break; sleep 0.1; done
pactl load-module module-null-sink sink_name=live sink_properties=device.description=live >/dev/null
pactl set-default-sink live
log "placa de som virtual pronta"

# ---------------- músicas de fundo ----------------
PLAYLIST="$TRABALHO/playlist.txt"
baixar_musicas() {
  [ -z "$MUSICAS_URLS" ] && return
  mkdir -p "$TRABALHO/baixadas"
  local i=0
  for url in ${MUSICAS_URLS//,/ }; do
    i=$((i + 1))
    local destino="$TRABALHO/baixadas/musica_$(printf '%03d' "$i").mp3"
    [ -s "$destino" ] && continue
    curl -fsSL --max-time 120 -o "$destino" "$url" && log "música baixada: $url" || log "aviso: não baixei $url"
  done
}
montar_playlist() {
  : > "$PLAYLIST"
  # shellcheck disable=SC2086
  find $PASTA_MUSICAS "$TRABALHO/baixadas" -maxdepth 2 -type f \
    \( -iname '*.mp3' -o -iname '*.m4a' -o -iname '*.aac' -o -iname '*.ogg' -o -iname '*.wav' -o -iname '*.flac' \) \
    2>/dev/null | shuf | while read -r arq; do
      printf "file '%s'\n" "${arq//\'/\'\\\'\'}" >> "$PLAYLIST"
    done
  [ -s "$PLAYLIST" ]
}
baixar_musicas

# ---------------- navegador com a página da live ----------------
navegador() {
  while true; do
    rm -rf "$TRABALHO/perfil"
    # Perfil novo já em português e com o tradutor desligado (senão aparece o balão "Traduzir?" na live).
    mkdir -p "$TRABALHO/perfil/Default"
    echo '{"translate":{"enabled":false},"intl":{"accept_languages":"pt-BR,pt"},"browser":{"has_seen_welcome_page":true}}' \
      > "$TRABALHO/perfil/Default/Preferences"
    log "abrindo a página da live no navegador"
    LANGUAGE=pt_BR "$CHROMIUM_BIN" --lang=pt-BR --accept-lang=pt-BR,pt --no-sandbox --disable-dev-shm-usage --no-first-run --no-default-browser-check \
      --disable-infobars --disable-session-crashed-bubble --disable-features=Translate,TranslateUI,MediaRouter \
      --autoplay-policy=no-user-gesture-required --hide-scrollbars --force-device-scale-factor=1 \
      --kiosk --window-position=0,0 --window-size="${LARGURA},${ALTURA}" \
      --user-data-dir="$TRABALHO/perfil" --password-store=basic "$LIVE_URL" >/dev/null 2>&1
    log "navegador fechou; abrindo de novo em 3 s"
    sleep 3
  done
}
navegador &
PIDS+=($!)

if [ "$REINICIAR_NAVEGADOR_H" != "0" ]; then
  ( while true; do sleep $((REINICIAR_NAVEGADOR_H * 3600)); log "recarregando o navegador (manutenção)"; pkill -f -- "--user-data-dir=$TRABALHO/perfil"; done ) &
  PIDS+=($!)
fi

sleep "${ESPERA_PAGINA_S:-8}"   # dá tempo da página carregar antes de começar a filmar

# ---------------- ffmpeg: tela + som + músicas -> YouTube ----------------
transmitir() {
  local entradas=(-thread_queue_size 1024 -f x11grab -draw_mouse 0 -video_size "$RESOLUCAO" -framerate "$FPS" -i ":99.0+0,0"
                  -thread_queue_size 1024 -f pulse -i live.monitor)
  local filtro formato="aresample=async=1,aformat=sample_rates=44100:channel_layouts=stereo"
  if montar_playlist; then
    log "músicas de fundo: $(wc -l < "$PLAYLIST") arquivo(s), volume $MUSICA_VOLUME"
    entradas+=(-re -stream_loop -1 -f concat -safe 0 -i "$PLAYLIST")
    if [ "$ABAIXAR_MUSICA" = "1" ]; then
      # A voz (som da página) comanda um compressor na música: quando alguém fala, a música abaixa.
      filtro="[1:a]${formato},asplit=2[voz][chave];[2:a]${formato},volume=${MUSICA_VOLUME}[mus];"
      filtro+="[mus][chave]sidechaincompress=threshold=0.02:ratio=12:attack=20:release=600[musica];"
      filtro+="[musica][voz]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[aout]"
    else
      filtro="[1:a]${formato}[voz];[2:a]${formato},volume=${MUSICA_VOLUME}[musica];"
      filtro+="[musica][voz]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[aout]"
    fi
  else
    log "sem músicas de fundo (coloque arquivos na pasta musicas/ do GitHub, no volume /musicas ou use MUSICAS_URLS)"
    filtro="[1:a]${formato}[aout]"
  fi
  local gop=$((FPS * 2)) saida
  if [ "${#DESTINOS[@]}" -eq 1 ]; then
    saida=(-f flv "${DESTINOS[0]}")
  else
    # onfail=ignore: se um destino cair, os outros continuam no ar.
    local lista="" d
    for d in "${DESTINOS[@]}"; do lista+="${lista:+|}[f=flv:onfail=ignore]${d}"; done
    saida=(-flags +global_header -f tee "$lista")
  fi
  ffmpeg -nostdin -y -hide_banner -loglevel "${FFMPEG_LOG:-warning}" -stats_period 60 \
    "${entradas[@]}" \
    -filter_complex "$filtro" -map 0:v -map "[aout]" \
    -c:v libx264 -preset "$PRESET" -b:v "${VIDEO_KBPS}k" -maxrate "${VIDEO_KBPS}k" -bufsize "$((VIDEO_KBPS * 2))k" \
    -pix_fmt yuv420p -g "$gop" -keyint_min "$gop" -sc_threshold 0 -r "$FPS" \
    -c:a aac -b:a "${AUDIO_KBPS}k" -ar 44100 \
    "${saida[@]}" 2>&1 | stdbuf -oL tr '\r' '\n' | vigiar_destinos
  return "${PIPESTATUS[0]}"
}

# Lê o log do ffmpeg. Se um destino cair (os outros seguem no ar), reinicia o
# ffmpeg depois de um tempo para reconectá-lo. Cada reinício corta uns segundos
# de todos, então a espera dobra a cada falha seguida (1, 2, 4... até 30 min).
vigiar_destinos() {
  local linha agendado="" d falhas espera
  while IFS= read -r linha; do
    for d in "${DESTINOS[@]}"; do linha="${linha//"$d"/$(ocultar "$d")}"; done   # não mostra as chaves no log
    [ -n "$linha" ] && echo "$linha"
    if [[ "$linha" == *"Slave muxer"*"failed"* ]] && [ -z "$agendado" ]; then
      falhas=$(cat "$TRABALHO/falhas" 2>/dev/null || echo 0)
      espera=$(( ${RECONECTAR_S:-60} << (falhas < 5 ? falhas : 5) ))
      [ "$espera" -gt 1800 ] && espera=1800
      echo $((falhas + 1)) > "$TRABALHO/falhas"
      log "um destino caiu; os outros seguem no ar. Tentando reconectar em $((espera / 60)) min"
      ( sleep "$espera"; pkill -u "$(id -u)" -x ffmpeg ) &
      agendado=$!
    fi
  done
  if [ -n "$agendado" ]; then
    kill "$agendado" 2>/dev/null   # o ffmpeg já parou por conta própria
  else
    echo 0 > "$TRABALHO/falhas"    # rodou sem nenhum destino caído
  fi
  return 0
}

while true; do
  log "transmitindo ${RESOLUCAO} ${FPS}fps ${VIDEO_KBPS}kbps para: $(for d in "${DESTINOS[@]}"; do printf '%s ' "$(ocultar "$d")"; done)"
  transmitir
  log "ffmpeg parou (código $?); tentando de novo em 5 s"
  sleep 5
done &
PIDS+=($!)

wait
