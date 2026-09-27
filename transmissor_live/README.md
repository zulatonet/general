# transmissor_live

Transmite a **página da live do SalaVip** (`/live?chave=...`) 24h para o
YouTube, direto da VPS, **sem OBS e sem PC ligado**, com **músicas de fundo em
loop**.

```
Xvfb (monitor virtual) ──> Chromium em tela cheia com a LIVE_URL
PulseAudio (placa de som virtual) <── som da página (áudios dos usuários, "plim")
ffmpeg: filma a tela + som da página + músicas ──> RTMP do YouTube
```

- Quando um usuário manda áudio, **a música abaixa sozinha** e volta depois
  (`ABAIXAR_MUSICA=1`).
- Se o navegador ou o ffmpeg caírem, eles voltam sozinhos. O navegador também é
  reaberto a cada 12 h (`REINICIAR_NAVEGADOR_H`) para não acumular memória.
- Não é um serviço web: não precisa de domínio nem de porta. O healthcheck
  confere se o ffmpeg está rodando.

## Easypanel

1. **Create Service → App** (ex.: `transmissor_live`).
2. **Source → GitHub**: `zulatonet/general`, a mesma branch do chat,
   **Build Path** `/transmissor_live`.
3. **Build → Dockerfile**.
4. **Environment**: copie o `.env.example` e preencha pelo menos:
   - `LIVE_URL`: no chat, como Master, digite `/live link` e cole o endereço.
   - `YOUTUBE_KEY`: YouTube Studio → Transmitir ao vivo → Stream → Chave da transmissão.
5. **Músicas** (qualquer uma das formas, podem ser usadas juntas):
   - **Pelo GitHub (mais fácil)**: no site do GitHub, abra a pasta
     `transmissor_live/musicas/` na branch do projeto → **Add file → Upload
     files** → arraste os `.mp3` → **Commit changes**. Depois faça o deploy:
     as músicas entram na imagem.
   - **Volume do Easypanel** montado em `/musicas`: o Easypanel não tem botão de
     upload para volumes; os arquivos ficam na VPS em
     `/etc/easypanel/projects/<projeto>/<serviço>/volumes/<nome do volume>/`.
     Envie por SFTP (WinSCP/FileZilla, usuário root) e reinicie o serviço.
   - `MUSICAS_URLS` com links diretos de `.mp3`, separados por vírgula.
6. **Domains / Ports**: nada. **Deploy**.

Nos logs aparece `transmitindo 1280x720 30fps...` e, em ~20 s, a live fica
"ao vivo" no YouTube Studio.

## Dicas

- **CPU**: 720p 30fps com `PRESET=veryfast` usa perto de 1,5 a 2 vCPUs. Se a VPS
  sofrer, use `PRESET=ultrafast`, `FPS=24` ou `RESOLUCAO=854x480`.
- **Internet**: `VIDEO_KBPS=2500` + áudio ≈ 3 Mbps de upload constante, por destino.
- **Vários destinos** (`RTMP_EXTRA`): o vídeo é codificado uma vez só e enviado
  a todos, então não pesa mais na CPU. Se um destino cair, os outros seguem no
  ar; o transmissor tenta reconectá-lo depois de 1, 2, 4... até 30 min (cada
  tentativa corta uns 5 s de todos os destinos).
- Pode colar comentários nas variáveis (`FPS=15   # ...`): são ignorados.
- **YouTube**: no Studio, **desligue o encerramento automático** da transmissão
  (Configurações → "Encerrar transmissão automaticamente"), para a live
  sobreviver a quedas curtas.
- **Direitos autorais**: use só música livre (Biblioteca de Áudio do YouTube,
  NCS, Pixabay Music). Música comercial derruba a live.
- Para mudar a chave da página (`/live novolink`), atualize a `LIVE_URL` e
  reinicie o serviço.

## Variáveis

| Variável | Padrão | Para quê |
|---|---|---|
| `LIVE_URL` | (obrigatória) | link secreto da página da live |
| `YOUTUBE_KEY` | (obrigatória) | chave da transmissão |
| `RTMP_URL` | YouTube + chave | outro destino RTMP no lugar do YouTube |
| `RTMP_EXTRA` | vazio | destinos extras ao mesmo tempo (Rumble, Twitch...), separados por vírgula |
| `RESOLUCAO` | `1280x720` | tamanho do vídeo |
| `FPS` | `30` | quadros por segundo |
| `VIDEO_KBPS` / `AUDIO_KBPS` | `2500` / `160` | qualidade |
| `PRESET` | `veryfast` | `ultrafast` gasta menos CPU |
| `MUSICA_VOLUME` | `0.35` | volume da música (0 a 1) |
| `ABAIXAR_MUSICA` | `1` | abaixa a música quando alguém fala |
| `MUSICAS_URLS` | vazio | links de `.mp3` para baixar ao iniciar |
| `REINICIAR_NAVEGADOR_H` | `12` | reabre o navegador a cada N horas (0 = nunca) |
