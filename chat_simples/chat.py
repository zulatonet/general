"""SalaVip: página + WebSocket numa única porta (aiohttp + PostgreSQL)."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from aiohttp import WSMsgType, web

import db
import tela as tela_mod
import webpush

# ---------------------------------------------------------------
# Configuração (variáveis de ambiente)
# ---------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SENHA_ADMIN = os.environ.get("ADMIN_PASSWORD", "")
PORTA = int(os.environ.get("PORT", "8080"))
TEMPO_MINIMO_RESET = timedelta(minutes=int(os.environ.get("ADMIN_RESET_MINUTES", "60")))
SESSAO_DIAS = int(os.environ.get("SESSION_DAYS", "30"))
TTL_HORAS = int(os.environ.get("PRIVATE_TTL_HOURS", "24"))
FUSO = os.environ.get("TIMEZONE", "America/Sao_Paulo")
# Push: se as chaves não forem informadas, o chat gera e guarda no banco.
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")
# Só enviamos push para os serviços oficiais dos navegadores (evita SSRF).
SERVICOS_PUSH = ("fcm.googleapis.com", "push.services.mozilla.com", "push.apple.com", "notify.windows.com")
# Atrás do Cloudflare, use TRUSTED_IP_HEADER=CF-Connecting-IP para ler o IP real do visitante.
TRUSTED_IP_HEADER = os.environ.get("TRUSTED_IP_HEADER", "").strip()
MAX_CONEXOES_POR_USUARIO = 5
NOME_COOKIE = "chat_sessao"

MAX_APELIDO = 20
MIN_SENHA = 6
MIN_SENHA_SALA = 4
MAX_SENHA = 128
MAX_TEXTO = 2000
MAX_SALAS_POR_USUARIO = 5
MAX_AUDIO_MS = 10_000
MAX_AUDIO_BYTES = 200 * 1024
MIME_AUDIO = re.compile(r"^audio/[a-z0-9.+-]+(;\s*codecs=[\"']?[a-z0-9.,+ -]+[\"']?)?$", re.I)
# Só letras latinas (com acentos), números, ponto, hífen e _: bloqueia nomes "clonados" com
# letras de outros alfabetos (ex.: "Аndre" com A cirílico imitando "Andre").
APELIDO_VALIDO = re.compile(r"^[A-Za-z0-9À-ÖØ-öø-ÿ_.-]{2,%d}$" % MAX_APELIDO)

# Anti-flood: mais de FLOOD_MAX_MSGS mensagens em FLOOD_JANELA segundos = 1 aviso.
# Cada aviso trava o envio por FLOOD_TRAVA_MIN minuto(s); passou de FLOOD_AVISOS
# avisos no dia, trava por FLOOD_TRAVA_FINAL_H horas.
FLOOD_MAX_MSGS = 8
FLOOD_JANELA = 10
FLOOD_AVISOS = 3
FLOOD_TRAVA_MIN = 1
FLOOD_TRAVA_FINAL_H = 24

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("chat")

PASTA_STATIC = Path(__file__).parent / "static"
PAGINA = (PASTA_STATIC / "index.html").read_text(encoding="utf-8")
SERVICE_WORKER = (PASTA_STATIC / "sw.js").read_text(encoding="utf-8")
MANIFESTO = (PASTA_STATIC / "manifest.webmanifest").read_text(encoding="utf-8")

HELP_USUARIO = """📖 Comandos:

/aceitar Sala Nome
  Coloca Nome na sua sala (só o dono). Numa conversa
  privada, basta /aceitar Sala.

/remover Sala Nome
  Tira Nome da sua sala (só o dono).

/sairsala Sala
  Sai de uma sala em que você está.

/apagarsala Sala
  Apaga sua sala e todas as mensagens dela.

/apagar
  Dentro da sua sala: apaga as mensagens dela.

/help
  Mostra esta lista de comandos."""

HELP_ADMIN = HELP_USUARIO + """

🛡️ Comandos de Admin:

/admin lista
  Mostra o Master e os Admins.

/nome Usuario NovoNome
  Troca o nome de Usuario para NovoNome (o histórico é mantido).

/senha Usuario NovaSenha
  Define uma nova senha para Usuario e desconecta as sessões dele.

/liberar Usuario
  Destrava o envio de quem foi bloqueado por flood.

/tela desfazer Usuario [minutos]
  Desfaz os pixels que Usuario pintou (padrão: última 1 hora).

/tela apagar X Y Largura Altura
  Pinta de branco uma área da Tela de Pixels.

/apagar
  Apaga o histórico da conversa aberta (Mural, privada ou sala).

/apagar Usuario
  Apaga todas as mensagens que Usuario mandou (em todo lugar).

/apagarsala Sala
  Apaga qualquer sala.

Admins não podem usar /nome, /senha, /liberar ou /apagar Usuario
contra o Master ou outros Admins."""

HELP_MASTER = HELP_ADMIN + """

👑 Comandos do Master:

/admin promover Nome
  Torna Nome um Admin.

/admin revogar Nome
  Tira o Admin de Nome.

/admin transferir Nome
  Passa o Master para Nome (você continua Admin).

/apagar total
  Apaga todas as mensagens do chat (mantém usuários).

Sem Master (ou para assumir um vago):

/admin SENHA
  Vira Master, se ainda não houver um.

/admin reset SENHA
  Remove o Master atual (só se ele estiver offline há algum tempo)."""


# ---------------------------------------------------------------
# Segurança: senhas, tokens, limites
# ---------------------------------------------------------------
def _scrypt(senha, salt):
    return hashlib.scrypt(senha.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


# No máximo 4 hashes ao mesmo tempo (~64 MB): muitos logins juntos não derrubam o servidor.
semaforo_scrypt = asyncio.Semaphore(4)


async def _scrypt_limitado(senha, salt):
    async with semaforo_scrypt:
        return await asyncio.to_thread(_scrypt, senha, salt)


async def gerar_hash_senha(senha):
    salt = secrets.token_bytes(16)
    h = await _scrypt_limitado(senha, salt)
    return f"scrypt${salt.hex()}${h.hex()}"


async def conferir_senha(senha, senha_hash):
    try:
        _, salt, esperado = senha_hash.split("$")
    except ValueError:
        return False
    h = await _scrypt_limitado(senha, bytes.fromhex(salt))
    return hmac.compare_digest(h.hex(), esperado)


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def senha_admin_correta(tentativa):
    return bool(SENHA_ADMIN) and hmac.compare_digest(tentativa.encode(), SENHA_ADMIN.encode())


def conferir_senha_admin(usuario_id, tentativa):
    """Confere a senha de admin com proteção contra força bruta.

    Limite por usuário (5 / 15 min) e, no chat todo, 20 erros por hora: passou
    disso, a senha de admin para de funcionar por 1 h para todo mundo (o
    atacante não ganha nada criando várias contas). Erros vão para o log.
    """
    if falhas_admin_global.excedido("admin") or not limite_senha_admin.permitir(usuario_id):
        return False
    if senha_admin_correta(tentativa):
        return True
    falhas_admin_global.registrar("admin")
    info = conexoes.get(usuario_id, {})
    log.warning("senha de admin errada: %s (IP %s)", info.get("apelido"), info.get("ip"))
    if falhas_admin_global.excedido("admin"):
        log.warning("ALERTA: muitas senhas de admin erradas; comandos /admin SENHA bloqueados por 1 hora")
    return False


class LimiteTaxa:
    """Janela deslizante em memória: no máximo `maximo` eventos em `janela` segundos por chave."""

    def __init__(self, maximo, janela):
        self.maximo = maximo
        self.janela = janela
        self.eventos = defaultdict(deque)

    def permitir(self, chave):
        agora = time.monotonic()
        fila = self.eventos[chave]
        while fila and agora - fila[0] > self.janela:
            fila.popleft()
        if len(fila) >= self.maximo:
            return False
        fila.append(agora)
        return True

    def excedido(self, chave):
        """Já atingiu o limite? (não conta um novo evento)"""
        agora = time.monotonic()
        fila = self.eventos.get(chave)
        while fila and agora - fila[0] > self.janela:
            fila.popleft()
        return bool(fila) and len(fila) >= self.maximo

    def registrar(self, chave):
        self.eventos[chave].append(time.monotonic())

    def zerar(self, chave):
        self.eventos.pop(chave, None)

    def limpar(self):
        agora = time.monotonic()
        for chave in [k for k, f in self.eventos.items() if not f or agora - f[-1] > self.janela]:
            del self.eventos[chave]


limite_login = LimiteTaxa(10, 300)                       # por IP
limite_acoes = LimiteTaxa(20, 10)                        # qualquer ação no WebSocket, por usuário
limite_senha_admin = LimiteTaxa(5, 900)                  # tentativas de senha de admin por usuário
limite_senha_sala = LimiteTaxa(5, 900)                   # tentativas de senha de sala por usuário
limite_solicitacao = LimiteTaxa(1, 600)                  # 1 pedido por sala a cada 10 min
detector_flood = LimiteTaxa(FLOOD_MAX_MSGS, FLOOD_JANELA)  # mensagens por usuário
limite_teste_push = LimiteTaxa(5, 300)                   # testes de notificação por usuário
limite_ip = LimiteTaxa(120, 60)                          # requisições à API/WebSocket por IP
limite_ws_ip = LimiteTaxa(20, 60)                        # conexões WebSocket novas por IP
limite_cadastro = LimiteTaxa(3, 3600)                    # contas novas por IP
falhas_login_conta = LimiteTaxa(20, 900)                 # senhas erradas por conta (contra botnet)
falhas_admin_global = LimiteTaxa(20, 3600)               # senhas de admin erradas no chat todo
falhas_sala = LimiteTaxa(30, 3600)                       # senhas erradas por sala
limite_audio_ouvir = LimiteTaxa(60, 60)                  # downloads de áudio por usuário
LIMITES = (limite_login, limite_acoes, limite_senha_admin, limite_senha_sala, limite_solicitacao, detector_flood,
           limite_teste_push, limite_ip, limite_ws_ip, limite_cadastro, falhas_login_conta, falhas_admin_global,
           falhas_sala, limite_audio_ouvir)


def ip_cliente(request):
    # Atrás do Cloudflare: cabeçalho configurado (ex.: CF-Connecting-IP).
    if TRUSTED_IP_HEADER and request.headers.get(TRUSTED_IP_HEADER):
        return request.headers[TRUSTED_IP_HEADER].strip()
    # Atrás do proxy do Easypanel (Traefik), o IP real é o último do X-Forwarded-For.
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[-1].strip()
    return request.remote or "?"


def origem_valida(request):
    origem = request.headers.get("Origin")
    return origem is None or urlparse(origem).netloc == request.host


def requisicao_https(request):
    return request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"


def validar_apelido(apelido):
    if not isinstance(apelido, str) or not APELIDO_VALIDO.match(apelido):
        return f"Nome deve ter de 2 a {MAX_APELIDO} caracteres (letras, números, ponto, hífen ou _), sem espaços."
    return None


def validar_nome_sala(nome):
    if not isinstance(nome, str) or not APELIDO_VALIDO.match(nome):
        return f"Nome da sala deve ter de 2 a {MAX_APELIDO} caracteres (letras, números, ponto, hífen ou _), sem espaços."
    return None


def validar_senha(senha, minimo=MIN_SENHA):
    if not isinstance(senha, str) or not (minimo <= len(senha) <= MAX_SENHA):
        return f"Senha deve ter de {minimo} a {MAX_SENHA} caracteres."
    return None


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else None


def dados_audio(audio_id, duracao_ms, unico, ouvido):
    return {"id": audio_id, "duracao_ms": duracao_ms, "unico": unico, "ouvido": ouvido}


def formatar_msg(m):
    msg = {"remetente": m["remetente"], "texto": m["texto"], "hora": iso(m["enviado_em"])}
    if m.get("audio_id"):
        msg["audio"] = dados_audio(m["audio_id"], m["audio_duracao_ms"], m["audio_unico"], m["audio_ouvido"])
    return msg


def duracao_texto(ms):
    seg = max(1, round((ms or 0) / 1000))
    return f"0:{seg:02d}"


# ---------------------------------------------------------------
# Conexões em memória
# ---------------------------------------------------------------
# usuario_id -> {"apelido": str, "sockets": set[WebSocketResponse], "bloqueado_ate": datetime | None}
conexoes = {}


async def enviar(ws, dados):
    try:
        await ws.send_str(json.dumps(dados))
    except Exception:
        pass


async def enviar_para_usuario(usuario_id, dados):
    info = conexoes.get(usuario_id)
    if info:
        msg = json.dumps(dados)
        await asyncio.gather(*[ws.send_str(msg) for ws in list(info["sockets"])], return_exceptions=True)


async def enviar_para_usuarios(usuario_ids, dados):
    msg = json.dumps(dados)
    sockets = [ws for uid in usuario_ids if uid in conexoes for ws in conexoes[uid]["sockets"]]
    if sockets:
        await asyncio.gather(*[ws.send_str(msg) for ws in sockets], return_exceptions=True)


async def transmitir(dados):
    await enviar_para_usuarios(list(conexoes), dados)


async def desconectar_usuario(usuario_id):
    info = conexoes.get(usuario_id)
    if info:
        for ws in list(info["sockets"]):
            await ws.close(code=4001, message=b"sessao encerrada")


# ---------------------------------------------------------------
# Notificações (Web Push)
# ---------------------------------------------------------------
vapid: webpush.Vapid | None = None
sessao_push: aiohttp.ClientSession | None = None
tarefas_push = set()


def resumir(texto, limite=200):
    texto = " ".join(texto.split())
    return texto if len(texto) <= limite else texto[:limite - 1] + "…"


# O push vai sempre para todos os aparelhos do destinatário. Quem decide se mostra
# é o próprio aparelho (sw.js): se o chat estiver aberto na tela dele, não mostra.
# Assim um app morto/congelado nunca fica sem aviso por o servidor achar que está aberto.
def notificar(usuario_ids, titulo, corpo, chave):
    """Manda push (em segundo plano) para os aparelhos dos usuários."""
    ids = set(usuario_ids)
    if ids and vapid:
        _agendar_push(db.inscricoes_de(ids), titulo, corpo, chave)


def notificar_todos_exceto(usuario_id, titulo, corpo, chave):
    if vapid:
        _agendar_push(db.inscricoes_exceto(usuario_id), titulo, corpo, chave)


def _agendar_push(consulta, titulo, corpo, chave):
    dados = {"titulo": titulo, "corpo": resumir(corpo), "chave": chave}

    async def rodar():
        try:
            inscricoes = await consulta
            await asyncio.gather(*[_enviar_push(i, dados) for i in inscricoes])
        except Exception:
            log.exception("erro ao enviar notificações")

    tarefa = asyncio.create_task(rodar())
    tarefas_push.add(tarefa)
    tarefa.add_done_callback(tarefas_push.discard)


async def _enviar_push(inscricao, dados):
    """Envia e devolve (ok, detalhe) — usado também pelo teste de notificações."""
    servico = urlparse(inscricao["endpoint"]).netloc
    try:
        status = await webpush.enviar(sessao_push, vapid, inscricao, dados)
        log.info("push entregue ao serviço %s (HTTP %s)", servico, status)
        return True, f"aceito pelo serviço de push ({servico}, HTTP {status})"
    except webpush.InscricaoExpirada:
        await db.apagar_inscricao(inscricao["endpoint"])
        log.info("push: inscrição expirada removida (%s)", servico)
        return False, f"inscrição expirada no {servico} — ative as notificações de novo"
    except Exception as erro:
        log.warning("push falhou (%s): %s", servico, erro)
        return False, f"{servico}: {erro}"


async def testar_push(usuario_id, atraso):
    """Manda um push de teste para todos os aparelhos do usuário, ignorando se a tela está aberta."""
    inscricoes = await db.inscricoes_de([usuario_id])
    if not inscricoes:
        await enviar_para_usuario(usuario_id, {"tipo": "push_teste", "aparelhos": 0, "resultados": []})
        return
    if atraso:
        await asyncio.sleep(atraso)
    dados = {"titulo": "🔔 Teste do SalaVip", "corpo": "Se você está vendo isto, as notificações funcionam!", "chave": "teste"}
    resultados = await asyncio.gather(*[_enviar_push(i, dados) for i in inscricoes])
    await enviar_para_usuario(usuario_id, {
        "tipo": "push_teste", "aparelhos": len(inscricoes),
        "resultados": [{"ok": ok, "detalhe": detalhe} for ok, detalhe in resultados],
    })


def endpoint_valido(endpoint):
    if not isinstance(endpoint, str) or len(endpoint) > 1000:
        return False
    u = urlparse(endpoint)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == s or host.endswith("." + s) for s in SERVICOS_PUSH)


async def avisar_sala(sala_id, nome_sala, mensagem):
    """Mensagem de sistema dentro da conversa da sala, para os membros online."""
    await enviar_para_usuarios(await db.membros_da_sala(sala_id), {"tipo": "aviso_sala", "sala": nome_sala, "mensagem": mensagem})


async def anunciar_sala(nome_sala):
    """Atualiza a sala (dono e nº de membros) na lista de todos."""
    for s in await db.listar_salas(0):
        if s["nome"].lower() == nome_sala.lower():
            await transmitir({"tipo": "sala_atualizada", "nome": s["nome"], "dono": s["dono"], "membros": s["membros"]})
            return


async def colocar_na_sala(sala, usuario_id, apelido):
    """Adiciona o membro e manda para ele o histórico da sala. Retorna False se já era membro."""
    if not await db.adicionar_membro(sala["id"], usuario_id):
        return False
    historico = await db.historico_sala(sala["id"], TTL_HORAS)
    await enviar_para_usuario(usuario_id, {
        "tipo": "sala_entrou", "nome": sala["nome"], "historico": [formatar_msg(m) for m in historico],
    })
    await avisar_sala(sala["id"], sala["nome"], f"{apelido} entrou na sala.")
    await anunciar_sala(sala["nome"])
    return True


# ---------------------------------------------------------------
# Tela de Pixels
# ---------------------------------------------------------------
tela_pixels = tela_mod.Tela()


def info_tela(usuario_id):
    return {
        "largura": tela_mod.LARGURA, "altura": tela_mod.ALTURA, "paleta": tela_mod.PALETA,
        "espera_s": tela_mod.ESPERA_S, "espera_restante": round(tela_pixels.espera_restante(usuario_id), 1),
    }


async def tela_imagem(request):
    """A tela inteira: 1 byte por pixel (índice da paleta), comprimida."""
    if not await usuario_da_requisicao(request):
        return web.json_response({"erro": "Não autenticado."}, status=401)
    resposta = web.Response(body=bytes(tela_pixels.pixels), content_type="application/octet-stream",
                            headers={"Cache-Control": "no-store"})
    resposta.enable_compression()
    return resposta


async def tratar_pixel(ws, usuario_id, dados):
    x, y, cor = dados.get("x"), dados.get("y"), dados.get("cor")
    if not tela_mod.Tela.valido(x, y, cor):
        return
    info = conexoes[usuario_id]
    if info.get("bloqueado_ate") and info["bloqueado_ate"] > datetime.now(timezone.utc):
        await enviar(ws, {"tipo": "pixel_espera", "espera": (info["bloqueado_ate"] - datetime.now(timezone.utc)).total_seconds(),
                          "mensagem": "🚫 Você está travado por flood e não pode pintar agora."})
        return
    restante = tela_pixels.pintar(usuario_id, x, y, cor)
    if restante:
        await enviar(ws, {"tipo": "pixel_espera", "espera": round(restante, 1)})
    else:
        await enviar_para_usuario(usuario_id, {"tipo": "pixel_ok", "espera": tela_mod.ESPERA_S})


async def tratar_pixel_info(ws, dados):
    x, y = dados.get("x"), dados.get("y")
    if not tela_mod.Tela.valido(x, y, 0):
        return
    row = await db.quem_pintou(x, y)
    await enviar(ws, {"tipo": "pixel_info", "x": x, "y": y,
                      "apelido": row["apelido"] if row else None, "quando": iso(row["criado_em"]) if row else None})


# ---------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------
@web.middleware
async def limite_por_ip(request, handler):
    """Freia quem martela a API/WebSocket (cada chamada pode consultar o banco)."""
    caminho = request.path
    if caminho.startswith("/api/") or caminho in ("/ws", "/health"):
        ip = ip_cliente(request)
        if not limite_ip.permitir(ip) or (caminho == "/ws" and not limite_ws_ip.permitir(ip)):
            return web.json_response({"erro": "Muitas requisições. Aguarde um pouco."}, status=429,
                                     headers={"Retry-After": "60"})
    return await handler(request)


@web.middleware
async def cabecalhos_seguranca(request, handler):
    resposta = await handler(request)
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("Referrer-Policy", "same-origin")
    resposta.headers.setdefault("X-Frame-Options", "DENY")
    resposta.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=(), payment=()")
    resposta.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if requisicao_https(request):
        resposta.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resposta


HOST_VALIDO = re.compile(r"^[A-Za-z0-9.-]+(:\d+)?$")


def url_base(request):
    """https://dominio atual, para os links absolutos da prévia (WhatsApp, Telegram...)."""
    host = request.host if HOST_VALIDO.match(request.host or "") else "localhost"
    return ("https" if requisicao_https(request) else "http") + "://" + host


async def pagina(request):
    nonce = secrets.token_urlsafe(16)
    html = PAGINA.replace("{{URL_BASE}}", url_base(request)).replace("<script>", f'<script nonce="{nonce}">')
    return web.Response(
        text=html,
        content_type="text/html",
        headers={
            "Cache-Control": "no-cache",
            "Content-Security-Policy": (
                f"default-src 'self'; script-src 'self' 'nonce-{nonce}'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; "
                "connect-src 'self' ws: wss:; object-src 'none'; base-uri 'none'; form-action 'self'; "
                "frame-ancestors 'none'"
            ),
        },
    )


async def service_worker(request):
    return web.Response(text=SERVICE_WORKER, content_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


async def manifesto(request):
    return web.Response(text=MANIFESTO, content_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


async def usuario_da_requisicao(request):
    token = request.cookies.get(NOME_COOKIE)
    return await db.buscar_sessao(hash_token(token)) if token else None


async def push_chave(request):
    return web.json_response({"chave": vapid.publica_b64 if vapid else None})


async def push_inscrever(request):
    if not origem_valida(request):
        return web.json_response({"erro": "Origem inválida."}, status=403)
    sessao = await usuario_da_requisicao(request)
    if not sessao:
        return web.json_response({"erro": "Não autenticado."}, status=401)
    try:
        dados = await request.json()
        endpoint = dados["endpoint"]
        p256dh, auth = dados["keys"]["p256dh"], dados["keys"]["auth"]
        assert endpoint_valido(endpoint)
        assert len(webpush.de_b64url(p256dh)) == 65 and len(webpush.de_b64url(auth)) == 16
    except Exception:
        return web.json_response({"erro": "Inscrição inválida."}, status=400)
    await db.salvar_inscricao(sessao["id"], endpoint, p256dh, auth)
    return web.json_response({"ok": True})


async def push_cancelar(request):
    if not origem_valida(request):
        return web.json_response({"erro": "Origem inválida."}, status=403)
    sessao = await usuario_da_requisicao(request)
    try:
        endpoint = (await request.json())["endpoint"]
    except Exception:
        return web.json_response({"erro": "Requisição inválida."}, status=400)
    if sessao and isinstance(endpoint, str):
        await db.apagar_inscricao(endpoint, sessao["id"])
    return web.json_response({"ok": True})


_saude_cache = {"quando": 0.0, "ok": False}


async def saude(request):
    # Consulta o banco no máximo a cada 5 s, por mais que chamem /health.
    if time.monotonic() - _saude_cache["quando"] > 5:
        try:
            _saude_cache["ok"] = await db.ping()
        except Exception:
            log.exception("health: banco indisponível")
            _saude_cache["ok"] = False
        _saude_cache["quando"] = time.monotonic()
    if not _saude_cache["ok"]:
        return web.json_response({"status": "erro"}, status=503)
    return web.json_response({"status": "ok"})


async def entrar(request):
    """Login; se o apelido ainda não existe, cria a conta."""
    if not origem_valida(request):
        return web.json_response({"erro": "Origem inválida."}, status=403)
    if not limite_login.permitir(ip_cliente(request)):
        return web.json_response({"erro": "Muitas tentativas. Aguarde alguns minutos."}, status=429)
    try:
        dados = await request.json()
    except Exception:
        return web.json_response({"erro": "Requisição inválida."}, status=400)
    apelido = (dados.get("apelido") or "").strip()
    senha = dados.get("senha") or ""
    erro = validar_apelido(apelido) or validar_senha(senha)
    if erro:
        return web.json_response({"erro": erro}, status=400)

    criado = False
    ip = ip_cliente(request)
    conta = apelido.lower()
    if falhas_login_conta.excedido(conta):
        log.warning("login bloqueado: muitas senhas erradas para %s (último IP %s)", apelido, ip)
        return web.json_response({"erro": "Muitas tentativas erradas para este nome. Tente de novo em 15 minutos."}, status=429)
    usuario = await db.buscar_usuario_por_apelido(apelido)
    if usuario:
        if not await conferir_senha(senha, usuario["senha_hash"]):
            falhas_login_conta.registrar(conta)
            return web.json_response({"erro": "Senha incorreta para este nome."}, status=401)
        falhas_login_conta.zerar(conta)
        usuario_id, apelido = usuario["id"], usuario["apelido"]
    else:
        if not limite_cadastro.permitir(ip):
            return web.json_response({"erro": "Muitas contas criadas deste endereço. Tente mais tarde."}, status=429)
        usuario_id = await db.criar_usuario(apelido, await gerar_hash_senha(senha))
        if usuario_id is None:  # criado por outra requisição no mesmo instante
            return web.json_response({"erro": "Esse nome acabou de ser registrado. Tente outro."}, status=409)
        criado = True
        log.info("novo usuário: %s (IP %s)", apelido, ip)

    token = secrets.token_urlsafe(32)
    await db.criar_sessao(hash_token(token), usuario_id, SESSAO_DIAS)
    resposta = web.json_response({"apelido": apelido, "criado": criado})
    resposta.set_cookie(
        NOME_COOKIE, token, max_age=SESSAO_DIAS * 86400, httponly=True,
        samesite="Lax", secure=requisicao_https(request), path="/",
    )
    return resposta


async def sair(request):
    if not origem_valida(request):
        return web.json_response({"erro": "Origem inválida."}, status=403)
    token = request.cookies.get(NOME_COOKIE)
    if token:
        await db.apagar_sessao(hash_token(token))
    resposta = web.json_response({"ok": True})
    resposta.del_cookie(NOME_COOKIE, path="/")
    return resposta


# ---------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------
async def websocket(request):
    if not origem_valida(request):
        return web.Response(status=403, text="Origem inválida.")
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=16 * 1024)
    await ws.prepare(request)

    token = request.cookies.get(NOME_COOKIE)
    sessao = await db.buscar_sessao(hash_token(token)) if token else None
    if not sessao:
        await ws.close(code=4001, message=b"nao autenticado")
        return ws

    usuario_id = sessao["id"]
    if len(conexoes.get(usuario_id, {}).get("sockets", ())) >= MAX_CONEXOES_POR_USUARIO:
        await ws.close(code=4002, message=b"muitas conexoes")
        return ws
    primeira_conexao = usuario_id not in conexoes
    info = conexoes.setdefault(usuario_id, {"apelido": sessao["apelido"], "sockets": set()})
    info["apelido"] = sessao["apelido"]
    info["ip"] = ip_cliente(request)
    info["sockets"].add(ws)
    try:
        await db.atualizar_ultimo_acesso(usuario_id)
        info["bloqueado_ate"] = await db.bloqueio_atual(usuario_id)
        mural, privadas, msgs_salas = await db.carregar_historico(usuario_id, TTL_HORAS)
        historico_privadas = {}
        for m in privadas:
            interlocutor = m["destinatario"] if m["remetente"] == info["apelido"] else m["remetente"]
            historico_privadas.setdefault(interlocutor, []).append(formatar_msg(m))
        historico_salas = {}
        for m in msgs_salas:
            historico_salas.setdefault(m["sala"], []).append(formatar_msg(m))
        usuarios = await db.listar_usuarios()
        await enviar(ws, {
            "tipo": "bemvindo",
            "nome": info["apelido"],
            "papel": await db.papel(usuario_id),
            "ttl_horas": TTL_HORAS,
            "bloqueado_ate": iso(info["bloqueado_ate"]),
            "historico": {
                "mural": [formatar_msg(m) for m in mural],
                "privadas": historico_privadas,
                "salas": historico_salas,
            },
            "nao_lidas": await db.contar_nao_lidas(usuario_id, TTL_HORAS),
            "usuarios": [{"apelido": u["apelido"], "online": u["id"] in conexoes} for u in usuarios],
            "contatos": await db.listar_contatos(usuario_id),
            "salas": [dict(s) for s in await db.listar_salas(usuario_id)],
            "tela": info_tela(usuario_id),
        })
        if primeira_conexao:
            await transmitir({"tipo": "presenca", "apelido": info["apelido"], "online": True})

        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                dados = json.loads(msg.data)
            except ValueError:
                continue
            if not isinstance(dados, dict):
                continue
            await tratar_mensagem(ws, usuario_id, dados)
    except Exception:
        log.exception("erro na conexão de %s", info["apelido"])
    finally:
        info["sockets"].discard(ws)
        if not info["sockets"]:
            conexoes.pop(usuario_id, None)
            try:
                await db.atualizar_ultimo_acesso(usuario_id)
                await transmitir({"tipo": "presenca", "apelido": info["apelido"], "online": False})
            except Exception:
                log.exception("erro ao finalizar conexão")
    return ws


async def pode_enviar(ws, usuario_id):
    """Aplica o bloqueio e o anti-flood. Retorna False (e avisa) se o envio está travado."""
    info = conexoes[usuario_id]
    agora = datetime.now(timezone.utc)
    if info.get("bloqueado_ate") and info["bloqueado_ate"] > agora:
        aviso = {"tipo": "bloqueado", "ate": iso(info["bloqueado_ate"]), "mensagem": "🚫 Seu envio está travado por flood."}
        await (enviar(ws, aviso) if ws else enviar_para_usuario(usuario_id, aviso))
        return False
    if detector_flood.permitir(usuario_id):
        return True

    detector_flood.zerar(usuario_id)
    avisos, ate = await db.registrar_flood(usuario_id, FUSO, FLOOD_AVISOS, FLOOD_TRAVA_MIN, FLOOD_TRAVA_FINAL_H)
    info["bloqueado_ate"] = ate
    if avisos <= FLOOD_AVISOS:
        mensagem = f"⚠️ Aviso {avisos}/{FLOOD_AVISOS}: muitas mensagens seguidas. Envio travado por {FLOOD_TRAVA_MIN} minuto."
    else:
        mensagem = f"🚫 Você passou de {FLOOD_AVISOS} avisos hoje. Envio travado por {FLOOD_TRAVA_FINAL_H} horas."
    log.info("flood: %s (aviso %d), travado até %s", info["apelido"], avisos, ate)
    await enviar_para_usuario(usuario_id, {"tipo": "bloqueado", "ate": iso(ate), "mensagem": mensagem})
    return False


async def tratar_mensagem(ws, usuario_id, dados):
    info = conexoes[usuario_id]
    tipo = dados.get("tipo")

    if tipo == "visibilidade":  # enviado por versões antigas da página; não é mais usado
        return

    if not limite_acoes.permitir(usuario_id):
        await enviar(ws, {"tipo": "erro", "mensagem": "Devagar! Você está fazendo coisas rápido demais."})
        return

    if tipo == "estado_push":
        await enviar(ws, {"tipo": "estado_push", "aparelhos": len(await db.inscricoes_de([usuario_id])),
                          "servidor_ok": vapid is not None})
        return

    if tipo == "marcar_lidas":
        interlocutor = dados.get("interlocutor")
        if isinstance(interlocutor, str):
            alvo = await db.buscar_usuario_por_apelido(interlocutor)
            if alvo:
                await db.marcar_como_lidas(usuario_id, alvo["id"])
        return

    if tipo == "testar_push":
        if not limite_teste_push.permitir(usuario_id):
            await enviar(ws, {"tipo": "erro", "mensagem": "Aguarde um pouco antes de testar de novo."})
            return
        atraso = dados.get("atraso") if isinstance(dados.get("atraso"), int) else 0
        tarefa = asyncio.create_task(testar_push(usuario_id, max(0, min(atraso, 30))))
        tarefas_push.add(tarefa)
        tarefa.add_done_callback(tarefas_push.discard)
        return

    if tipo == "fixar":
        apelido, fixo = dados.get("apelido"), dados.get("fixo")
        if isinstance(apelido, str) and isinstance(fixo, bool):
            alvo = await db.buscar_usuario_por_apelido(apelido)
            if alvo and alvo["id"] != usuario_id:
                await db.fixar_contato(usuario_id, alvo["id"], fixo)
                await enviar_para_usuario(usuario_id, {"tipo": "contatos", "contatos": await db.listar_contatos(usuario_id)})
        return

    if tipo == "pixel":
        await tratar_pixel(ws, usuario_id, dados)
        return

    if tipo == "pixel_info":
        await tratar_pixel_info(ws, dados)
        return

    if tipo == "criar_sala":
        await criar_sala(ws, usuario_id, dados.get("nome"), dados.get("senha"))
        return

    if tipo == "entrar_sala":
        await entrar_sala_com_senha(ws, usuario_id, dados.get("sala"), dados.get("senha"))
        return

    if tipo == "solicitar_sala":
        await solicitar_sala(ws, usuario_id, dados.get("sala"))
        return

    texto = dados.get("texto")
    destino = dados.get("para")
    nome_sala = dados.get("sala")
    if not isinstance(texto, str) or (destino is not None and not isinstance(destino, str)) \
            or (nome_sala is not None and not isinstance(nome_sala, str)):
        return
    texto = texto.strip()
    if not texto:
        return
    if len(texto) > MAX_TEXTO:
        await enviar(ws, {"tipo": "erro", "mensagem": f"Mensagem muito longa (máximo {MAX_TEXTO} caracteres)."})
        return

    if texto.startswith("/"):
        await tratar_comando(ws, usuario_id, texto, destino, nome_sala)
        return

    apelido = info["apelido"]

    # Sala
    if nome_sala is not None:
        sala = await db.buscar_sala(nome_sala)
        if not sala or not await db.eh_membro(sala["id"], usuario_id):
            await enviar(ws, {"tipo": "erro", "mensagem": "Você não está nessa sala."})
            return
        if not await pode_enviar(ws, usuario_id):
            return
        await db.atualizar_ultimo_acesso(usuario_id)
        hora = iso(await db.salvar_mensagem(usuario_id, None, texto, sala["id"]))
        membros = await db.membros_da_sala(sala["id"])
        await enviar_para_usuarios(membros, {
            "tipo": "msg", "sala": sala["nome"], "de": apelido, "texto": texto, "hora": hora,
        })
        notificar([m for m in membros if m != usuario_id], f"💬 {sala['nome']}", f"{apelido}: {texto}", "s:" + sala["nome"])
        return

    # Mural de Recados: só admins escrevem
    if destino is None:
        if await db.papel(usuario_id) < db.ADMIN:
            await enviar(ws, {"tipo": "erro", "mensagem": "📢 Somente Admins podem escrever no Mural de Recados."})
            return
        if not await pode_enviar(ws, usuario_id):
            return
        await db.atualizar_ultimo_acesso(usuario_id)
        hora = await db.salvar_mensagem(usuario_id, None, texto)
        await transmitir({"tipo": "msg", "de": apelido, "texto": texto, "privado": False, "hora": iso(hora)})
        notificar_todos_exceto(usuario_id, "📢 Mural de Recados", f"{apelido}: {texto}", "MURAL")
        return

    # Privada
    alvo = await db.buscar_usuario_por_apelido(destino)
    if not alvo or alvo["id"] == usuario_id:
        await enviar(ws, {"tipo": "erro", "mensagem": "Usuário não encontrado."})
        return
    if not await pode_enviar(ws, usuario_id):
        return
    await db.atualizar_ultimo_acesso(usuario_id)
    await entregar_privada(usuario_id, alvo, texto)


async def entregar_privada(usuario_id, alvo, texto):
    apelido = conexoes[usuario_id]["apelido"]
    hora = iso(await db.salvar_mensagem(usuario_id, alvo["id"], texto))
    await enviar_para_usuario(alvo["id"], {"tipo": "msg", "de": apelido, "texto": texto, "privado": True, "hora": hora})
    await enviar_para_usuario(usuario_id, {"tipo": "msg_enviada", "para": alvo["apelido"], "texto": texto, "privado": True, "hora": hora})
    notificar([alvo["id"]], apelido, texto, "u:" + apelido)


# ---------------------------------------------------------------
# Áudios (até 10 s): privado = ouvir uma vez; Mural = só admins, fica guardado
# ---------------------------------------------------------------
def parece_audio(dados):
    """Confere a assinatura do arquivo: WebM/Matroska, Ogg ou MP4/M4A."""
    return dados[:4] == b"\x1a\x45\xdf\xa3" or dados[:4] == b"OggS" or dados[4:8] == b"ftyp"


async def audio_enviar(request):
    """Recebe o áudio gravado. ?para=Apelido (privado) ou sem `para` (Mural). ?duracao=ms"""
    if not origem_valida(request):
        return web.json_response({"erro": "Origem inválida."}, status=403)
    sessao = await usuario_da_requisicao(request)
    if not sessao:
        return web.json_response({"erro": "Não autenticado."}, status=401)
    usuario_id = sessao["id"]
    if usuario_id not in conexoes:
        return web.json_response({"erro": "Conecte-se ao chat para enviar áudio."}, status=409)
    if not limite_acoes.permitir(usuario_id):
        return web.json_response({"erro": "Devagar! Você está fazendo coisas rápido demais."}, status=429)

    mime = (request.headers.get("Content-Type") or "").strip()
    try:
        duracao = int(request.query.get("duracao", "0"))
    except ValueError:
        duracao = 0
    dados = await request.read()
    if not MIME_AUDIO.match(mime) or len(mime) > 100 or not dados or len(dados) > MAX_AUDIO_BYTES or not parece_audio(dados):
        return web.json_response({"erro": "Áudio inválido."}, status=400)
    if not (300 <= duracao <= MAX_AUDIO_MS + 700):
        return web.json_response({"erro": "O áudio deve ter até 10 segundos."}, status=400)
    duracao = min(duracao, MAX_AUDIO_MS)

    apelido = conexoes[usuario_id]["apelido"]
    destino = request.query.get("para")
    if request.query.get("sala"):
        return web.json_response({"erro": "Áudio não é permitido nas salas."}, status=400)
    if destino is None:
        if await db.papel(usuario_id) < db.ADMIN:
            return web.json_response({"erro": "📢 Só Admins podem mandar áudio no Mural."}, status=403)
        alvo = None
    else:
        alvo = await db.buscar_usuario_por_apelido(destino)
        if not alvo or alvo["id"] == usuario_id:
            return web.json_response({"erro": "Usuário não encontrado."}, status=404)
    if not await pode_enviar(None, usuario_id):
        return web.json_response({"erro": "Envio travado por flood."}, status=429)

    audio_id = secrets.token_urlsafe(18)
    unico = alvo is not None
    texto = f"🎤 Áudio ({duracao_texto(duracao)})"
    hora = iso(await db.salvar_audio(audio_id, usuario_id, alvo["id"] if alvo else None, texto, duracao, unico, mime, dados))
    await db.atualizar_ultimo_acesso(usuario_id)
    audio = dados_audio(audio_id, duracao, unico, False)
    if alvo is None:
        await transmitir({"tipo": "msg", "de": apelido, "texto": texto, "privado": False, "hora": hora, "audio": audio})
        notificar_todos_exceto(usuario_id, "📢 Mural de Recados", f"{apelido}: {texto}", "MURAL")
    else:
        await enviar_para_usuario(alvo["id"], {"tipo": "msg", "de": apelido, "texto": texto, "privado": True, "hora": hora, "audio": audio})
        await enviar_para_usuario(usuario_id, {"tipo": "msg_enviada", "para": alvo["apelido"], "texto": texto, "privado": True, "hora": hora, "audio": audio})
        notificar([alvo["id"]], apelido, texto, "u:" + apelido)
    return web.json_response({"ok": True})


async def audio_ouvir(request):
    sessao = await usuario_da_requisicao(request)
    if not sessao:
        return web.json_response({"erro": "Não autenticado."}, status=401)
    if not limite_audio_ouvir.permitir(sessao["id"]):
        return web.json_response({"erro": "Muitos áudios seguidos. Aguarde um pouco."}, status=429)
    audio_id = request.match_info["id"]
    info = await db.info_audio(audio_id)
    if not info:
        return web.json_response({"erro": "Áudio não encontrado."}, status=404)

    if not info["audio_unico"]:  # Mural: qualquer pessoa logada ouve quantas vezes quiser
        row = await db.ler_audio(audio_id)
        if not row:
            return web.json_response({"erro": "Áudio apagado."}, status=410)
        return web.Response(body=row["dados"], content_type=row["mime"].split(";")[0],
                            headers={"Cache-Control": "private, max-age=86400"})

    # Privado: só quem recebeu, e uma vez só
    if sessao["id"] != info["destinatario_id"]:
        return web.json_response({"erro": "Áudio de ouvir uma vez: só quem recebeu pode ouvir."}, status=403)
    row = await db.consumir_audio(audio_id)
    if not row:
        return web.json_response({"erro": "Esse áudio já foi ouvido."}, status=410)
    evento = {"tipo": "audio_ouvido", "id": audio_id}
    await enviar_para_usuario(info["remetente_id"], evento)
    await enviar_para_usuario(info["destinatario_id"], evento)
    return web.Response(body=row["dados"], content_type=row["mime"].split(";")[0], headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------
# Salas
# ---------------------------------------------------------------
async def criar_sala(ws, usuario_id, nome, senha):
    erro = validar_nome_sala(nome) or validar_senha(senha, MIN_SENHA_SALA)
    if erro:
        await enviar(ws, {"tipo": "erro_sala", "mensagem": erro})
        return
    if await db.contar_salas_do_dono(usuario_id) >= MAX_SALAS_POR_USUARIO:
        await enviar(ws, {"tipo": "erro_sala", "mensagem": f"Você já tem {MAX_SALAS_POR_USUARIO} salas. Apague uma para criar outra."})
        return
    sala_id = await db.criar_sala(nome, await gerar_hash_senha(senha), usuario_id)
    if not sala_id:
        await enviar(ws, {"tipo": "erro_sala", "mensagem": "Já existe uma sala com esse nome."})
        return
    log.info("sala %s criada por %s", nome, conexoes[usuario_id]["apelido"])
    await anunciar_sala(nome)
    await enviar_para_usuario(usuario_id, {"tipo": "sala_entrou", "nome": nome, "historico": [], "criada": True})


async def entrar_sala_com_senha(ws, usuario_id, nome, senha):
    if not isinstance(nome, str) or not isinstance(senha, str):
        return
    sala = await db.buscar_sala(nome)
    if not sala:
        await enviar(ws, {"tipo": "erro_sala", "mensagem": "Sala não encontrada."})
        return
    if await db.eh_membro(sala["id"], usuario_id):
        await enviar(ws, {"tipo": "erro_sala", "mensagem": "Você já está nessa sala."})
        return
    if falhas_sala.excedido(sala["id"]) or not limite_senha_sala.permitir(usuario_id):
        await enviar(ws, {"tipo": "erro_sala", "mensagem": "Muitas tentativas. Aguarde alguns minutos ou peça para entrar."})
        return
    if len(senha) > MAX_SENHA or not await conferir_senha(senha, sala["senha_hash"]):
        falhas_sala.registrar(sala["id"])
        await enviar(ws, {"tipo": "erro_sala", "mensagem": "Senha incorreta."})
        return
    await colocar_na_sala(sala, usuario_id, conexoes[usuario_id]["apelido"])


async def solicitar_sala(ws, usuario_id, nome):
    if not isinstance(nome, str):
        return
    sala = await db.buscar_sala(nome)
    if not sala:
        await enviar(ws, {"tipo": "erro_sala", "mensagem": "Sala não encontrada."})
        return
    if await db.eh_membro(sala["id"], usuario_id):
        await enviar(ws, {"tipo": "erro_sala", "mensagem": "Você já está nessa sala."})
        return
    if not limite_solicitacao.permitir((usuario_id, sala["id"])):
        await enviar(ws, {"tipo": "erro_sala", "mensagem": "Você já pediu para entrar nessa sala. Aguarde a resposta."})
        return
    if not await pode_enviar(ws, usuario_id):
        return
    apelido = conexoes[usuario_id]["apelido"]
    texto = f"📩 Pedido para entrar na sala {sala['nome']}.\nPara aceitar, digite: /aceitar {sala['nome']} {apelido}"
    await entregar_privada(usuario_id, {"id": sala["dono_id"], "apelido": sala["dono"]}, texto)
    await enviar(ws, {"tipo": "solicitacao_enviada", "sala": sala["nome"], "dono": sala["dono"]})


# ---------------------------------------------------------------
# Comandos (interceptados no servidor; comandos inválidos são ignorados)
# ---------------------------------------------------------------
async def tratar_comando(ws, usuario_id, texto, destino, nome_sala):
    partes = texto.split(maxsplit=3)
    cmd = partes[0].lower()

    async def ok(mensagem):
        await enviar(ws, {"tipo": "comando_ok", "mensagem": mensagem})

    # Comandos com a senha do admin: valem para qualquer um
    if cmd == "/admin" and len(partes) >= 2 and partes[1].lower() not in ("promover", "revogar", "transferir", "lista"):
        # /admin reset SENHA
        if partes[1].lower() == "reset":
            if len(partes) < 3 or not conferir_senha_admin(usuario_id, partes[2]):
                return
            master = await db.buscar_master()
            if not master:
                await ok("Não há Master. Use /admin <senha> para assumir.")
            elif master["id"] in conexoes:
                await ok("Master está online. Não é possível resetar.")
            elif datetime.now(timezone.utc) - master["ultimo_acesso"] < TEMPO_MINIMO_RESET:
                await ok("Master esteve online recentemente. Aguarde mais tempo.")
            else:
                await db.remover_master()
                log.info("master %s removido via reset", master["apelido"])
                await ok("Master anterior removido (continua Admin). Use /admin <senha> para assumir.")
            return

        # /admin SENHA
        if not conferir_senha_admin(usuario_id, partes[1]):
            return
        if await db.assumir_master_se_vago(usuario_id):
            log.info("%s agora é master", conexoes[usuario_id]["apelido"])
            await enviar_para_usuario(usuario_id, {"tipo": "papel", "papel": db.MASTER})
            await ok("👑 Você agora é o Master.")
        else:
            await ok("Já existe um Master.")
        return

    meu_papel = await db.papel(usuario_id)

    # Comandos de sala: valem para qualquer um (dono da sala; admins onde indicado)
    if cmd in ("/aceitar", "/remover", "/sairsala", "/apagarsala") or (cmd == "/apagar" and len(partes) == 1 and nome_sala):
        await comando_sala(ok, usuario_id, meu_papel, cmd, partes, destino, nome_sala)
        return

    if cmd == "/help":
        await ok(HELP_MASTER if meu_papel == db.MASTER else HELP_ADMIN if meu_papel >= db.ADMIN else HELP_USUARIO)
        return

    # A partir daqui, só admin ou master
    if meu_papel < db.ADMIN:
        return

    async def buscar_alvo(apelido, exigir_permissao=True):
        """Busca o usuário; admins não podem agir sobre o Master nem sobre outros Admins."""
        alvo = await db.buscar_usuario_por_apelido(apelido)
        if not alvo:
            await ok(f"Usuário {apelido} não encontrado.")
            return None
        if exigir_permissao and alvo["id"] != usuario_id and meu_papel != db.MASTER:
            if await db.papel(alvo["id"]) >= db.ADMIN:
                await ok("Você não pode fazer isso com o Master ou outro Admin.")
                return None
        return alvo

    if cmd == "/admin":
        sub = partes[1].lower() if len(partes) >= 2 else ""
        if sub == "lista":
            admins = await db.listar_admins()
            linhas = [("👑 " if a["is_master"] else "🛡️ ") + a["apelido"] for a in admins]
            await ok("Equipe:\n" + "\n".join(linhas))
            return
        if sub not in ("promover", "revogar", "transferir"):
            return
        if meu_papel != db.MASTER:
            await ok("Só o Master pode promover, revogar ou transferir.")
            return
        if len(partes) < 3:
            await ok(f"Uso: /admin {sub} Nome")
            return
        alvo = await buscar_alvo(partes[2])
        if not alvo:
            return
        nome = alvo["apelido"]
        if alvo["id"] == usuario_id:
            await ok("Você já é o Master.")
            return
        alvo_papel = await db.papel(alvo["id"])

        if sub == "promover":
            if alvo_papel >= db.ADMIN:
                await ok(f"{nome} já é Admin.")
                return
            await db.definir_admin(alvo["id"], True)
            log.info("%s promovido a admin", nome)
            await enviar_para_usuario(alvo["id"], {"tipo": "papel", "papel": db.ADMIN})
            await enviar_para_usuario(alvo["id"], {"tipo": "sistema", "mensagem": "🛡️ Você agora é Admin. Digite /help para ver os comandos."})
            await ok(f"{nome} agora é Admin.")
        elif sub == "revogar":
            if alvo_papel < db.ADMIN:
                await ok(f"{nome} não é Admin.")
                return
            await db.definir_admin(alvo["id"], False)
            log.info("admin de %s revogado", nome)
            await enviar_para_usuario(alvo["id"], {"tipo": "papel", "papel": db.USUARIO})
            await enviar_para_usuario(alvo["id"], {"tipo": "sistema", "mensagem": "Você não é mais Admin."})
            await ok(f"Admin de {nome} revogado.")
        else:  # transferir
            await db.transferir_master(alvo["id"])
            log.info("master transferido para %s", nome)
            await enviar_para_usuario(alvo["id"], {"tipo": "papel", "papel": db.MASTER})
            await enviar_para_usuario(usuario_id, {"tipo": "papel", "papel": db.ADMIN})
            await enviar_para_usuario(alvo["id"], {"tipo": "sistema", "mensagem": "👑 Você agora é o Master. Digite /help para ver os comandos."})
            await ok(f"Master transferido para {nome}. Você continua Admin.")

    elif cmd == "/nome":
        if len(partes) < 3:
            await ok("Uso: /nome Usuario NovoNome")
            return
        alvo = await buscar_alvo(partes[1])
        novo = partes[2]
        if not alvo:
            return
        if erro := validar_apelido(novo):
            await ok(erro)
        elif not await db.trocar_apelido(alvo["id"], novo):
            await ok(f"O nome {novo} já está em uso.")
        else:
            if alvo["id"] in conexoes:
                conexoes[alvo["id"]]["apelido"] = novo
            await transmitir({"tipo": "renomeado", "de": alvo["apelido"], "para": novo})
            await ok(f"Nome de {alvo['apelido']} alterado para {novo}.")

    elif cmd == "/senha":
        if len(partes) < 3:
            await ok("Uso: /senha Usuario NovaSenha")
            return
        alvo = await buscar_alvo(partes[1])
        if not alvo:
            return
        if erro := validar_senha(partes[2]):
            await ok(erro)
        else:
            await db.trocar_senha(alvo["id"], await gerar_hash_senha(partes[2]))
            log.info("senha de %s redefinida por %s", alvo["apelido"], conexoes[usuario_id]["apelido"])
            if alvo["id"] != usuario_id:
                await desconectar_usuario(alvo["id"])
            await ok(f"Senha de {alvo['apelido']} redefinida. As sessões dele foram encerradas.")

    elif cmd == "/tela":
        partes_tela = texto.split()
        sub = partes_tela[1].lower() if len(partes_tela) >= 2 else ""
        if sub == "desfazer" and len(partes_tela) >= 3:
            alvo = await buscar_alvo(partes_tela[2])
            if not alvo:
                return
            try:
                minutos = max(1, min(int(partes_tela[3]), 30 * 24 * 60)) if len(partes_tela) >= 4 else 60
            except ValueError:
                await ok("Uso: /tela desfazer Usuario [minutos]")
                return
            await tela_pixels.descarregar(transmitir)  # garante que o histórico está gravado
            linhas = await db.pixels_para_desfazer(alvo["id"], minutos)
            alteracoes = [(r["x"], r["y"], r["anterior"] if r["anterior"] is not None
                           else tela_mod.INICIAL[r["y"] * tela_mod.LARGURA + r["x"]]) for r in linhas]
            tela_pixels.aplicar(alteracoes, usuario_id)
            log.info("tela: %d pixels de %s desfeitos por %s", len(alteracoes), alvo["apelido"], conexoes[usuario_id]["apelido"])
            await ok(f"🎨 {len(alteracoes)} pixels de {alvo['apelido']} desfeitos (últimos {minutos} min).")
        elif sub == "apagar" and len(partes_tela) == 6:
            try:
                x, y, larg, alt = (int(v) for v in partes_tela[2:6])
            except ValueError:
                await ok("Uso: /tela apagar X Y Largura Altura")
                return
            x2, y2 = min(tela_mod.LARGURA, x + larg), min(tela_mod.ALTURA, y + alt)
            x, y = max(0, x), max(0, y)
            alteracoes = [(px, py, tela_mod.BRANCO) for py in range(y, y2) for px in range(x, x2)]
            tela_pixels.aplicar(alteracoes, usuario_id)
            log.info("tela: área %dx%d apagada por %s", x2 - x, y2 - y, conexoes[usuario_id]["apelido"])
            await ok(f"🎨 Área apagada ({len(alteracoes)} pixels).")
        else:
            await ok("Uso: /tela desfazer Usuario [minutos]  ou  /tela apagar X Y Largura Altura")

    elif cmd == "/liberar":
        if len(partes) < 2:
            await ok("Uso: /liberar Usuario")
            return
        alvo = await buscar_alvo(partes[1])
        if not alvo:
            return
        await db.liberar_bloqueio(alvo["id"])
        detector_flood.zerar(alvo["id"])
        if alvo["id"] in conexoes:
            conexoes[alvo["id"]]["bloqueado_ate"] = None
        await enviar_para_usuario(alvo["id"], {"tipo": "desbloqueado", "mensagem": "✅ Seu envio foi liberado por um Admin."})
        log.info("%s liberado por %s", alvo["apelido"], conexoes[usuario_id]["apelido"])
        await ok(f"{alvo['apelido']} liberado.")

    elif cmd == "/apagar":
        eu = conexoes[usuario_id]["apelido"]
        if len(partes) == 1:
            if destino is None:
                await db.apagar_mural()
                await transmitir({"tipo": "apagado", "escopo": "mural"})
                await ok("Mural de Recados apagado.")
                return
            alvo = await buscar_alvo(destino, exigir_permissao=False)
            if not alvo:
                return
            await db.apagar_conversa_privada(usuario_id, alvo["id"])
            await enviar_para_usuario(usuario_id, {"tipo": "apagado", "escopo": "privada", "com": alvo["apelido"]})
            await enviar_para_usuario(alvo["id"], {"tipo": "apagado", "escopo": "privada", "com": eu})
            await enviar_para_usuario(alvo["id"], {"tipo": "sistema", "mensagem": "Conversa apagada pelo Admin."})
            await ok(f"Conversa com {alvo['apelido']} apagada.")
        elif partes[1].lower() == "total":
            if meu_papel != db.MASTER:
                await ok("Só o Master pode apagar tudo.")
                return
            await db.apagar_tudo()
            await transmitir({"tipo": "apagado", "escopo": "total"})
            await transmitir({"tipo": "sistema", "mensagem": "Todas as mensagens foram apagadas pelo Admin."})
            await ok("Todas as mensagens foram apagadas.")
        else:
            alvo = await buscar_alvo(partes[1])
            if not alvo:
                return
            await db.apagar_mensagens_de(alvo["id"])
            await transmitir({"tipo": "apagado", "escopo": "usuario", "usuario": alvo["apelido"]})
            await ok(f"Mensagens de {alvo['apelido']} apagadas.")


async def comando_sala(ok, usuario_id, meu_papel, cmd, partes, destino, nome_sala):
    eu = conexoes[usuario_id]["apelido"]

    # /apagar dentro de uma sala: dono ou admin
    if cmd == "/apagar":
        sala = await db.buscar_sala(nome_sala)
        if not sala or (sala["dono_id"] != usuario_id and meu_papel < db.ADMIN):
            return
        await db.apagar_mensagens_da_sala(sala["id"])
        await enviar_para_usuarios(await db.membros_da_sala(sala["id"]), {"tipo": "apagado", "escopo": "sala", "sala": sala["nome"]})
        await ok(f"Mensagens da sala {sala['nome']} apagadas.")
        return

    if len(partes) < 2:
        await ok(f"Uso: {cmd} Sala" + (" Nome" if cmd in ("/aceitar", "/remover") else ""))
        return
    sala = await db.buscar_sala(partes[1])
    if not sala:
        await ok(f"Sala {partes[1]} não encontrada.")
        return
    dono = sala["dono_id"] == usuario_id

    if cmd == "/aceitar":
        if not dono:
            await ok("Só quem criou a sala pode aceitar pessoas.")
            return
        # Sem Nome: numa conversa privada, aceita a pessoa da conversa.
        nome = partes[2] if len(partes) >= 3 else destino
        if not nome:
            await ok(f"Uso: /aceitar {sala['nome']} Nome")
            return
        alvo = await db.buscar_usuario_por_apelido(nome)
        if not alvo:
            await ok(f"Usuário {nome} não encontrado.")
            return
        if not await colocar_na_sala(sala, alvo["id"], alvo["apelido"]):
            await ok(f"{alvo['apelido']} já está na sala {sala['nome']}.")
            return
        await enviar_para_usuario(alvo["id"], {"tipo": "sistema", "mensagem": f"✅ {eu} colocou você na sala {sala['nome']}."})
        notificar([alvo["id"]], f"💬 {sala['nome']}", f"✅ {eu} colocou você na sala.", "s:" + sala["nome"])
        log.info("%s aceito na sala %s", alvo["apelido"], sala["nome"])
        await ok(f"{alvo['apelido']} agora está na sala {sala['nome']}.")

    elif cmd == "/remover":
        if not dono and meu_papel < db.ADMIN:
            await ok("Só quem criou a sala pode remover pessoas.")
            return
        if len(partes) < 3:
            await ok(f"Uso: /remover {sala['nome']} Nome")
            return
        alvo = await db.buscar_usuario_por_apelido(partes[2])
        if not alvo or alvo["id"] == sala["dono_id"]:
            await ok("Não é possível remover essa pessoa.")
            return
        if not await db.remover_membro(sala["id"], alvo["id"]):
            await ok(f"{alvo['apelido']} não está na sala {sala['nome']}.")
            return
        await enviar_para_usuario(alvo["id"], {"tipo": "sala_saiu", "nome": sala["nome"], "mensagem": f"Você foi removido da sala {sala['nome']}."})
        await avisar_sala(sala["id"], sala["nome"], f"{alvo['apelido']} foi removido da sala.")
        await anunciar_sala(sala["nome"])
        await ok(f"{alvo['apelido']} removido da sala {sala['nome']}.")

    elif cmd == "/sairsala":
        if dono:
            await ok("Você é o dono. Para encerrar a sala use /apagarsala " + sala["nome"])
            return
        if not await db.remover_membro(sala["id"], usuario_id):
            await ok(f"Você não está na sala {sala['nome']}.")
            return
        await enviar_para_usuario(usuario_id, {"tipo": "sala_saiu", "nome": sala["nome"], "mensagem": f"Você saiu da sala {sala['nome']}."})
        await avisar_sala(sala["id"], sala["nome"], f"{eu} saiu da sala.")
        await anunciar_sala(sala["nome"])

    elif cmd == "/apagarsala":
        if not dono and meu_papel < db.ADMIN:
            await ok("Só quem criou a sala pode apagá-la.")
            return
        await db.apagar_sala(sala["id"])
        log.info("sala %s apagada por %s", sala["nome"], eu)
        await transmitir({"tipo": "sala_apagada", "nome": sala["nome"]})
        await ok(f"Sala {sala['nome']} apagada.")


# ---------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------
async def manutencao(app):
    async def loop():
        while True:
            await asyncio.sleep(300)
            try:
                apagadas = await db.apagar_expiradas(TTL_HORAS)
                if apagadas:
                    log.info("%d mensagens expiradas apagadas", apagadas)
                await db.limpar_sessoes_expiradas()
                await db.limpar_log_tela()
                tela_pixels.limpar_esperas()
                for limite in LIMITES:
                    limite.limpar()
            except Exception:
                log.exception("erro na manutenção")

    async def loop_tela():
        while True:
            await asyncio.sleep(0.25)
            try:
                await tela_pixels.descarregar(transmitir)
            except Exception:
                log.exception("erro ao atualizar a tela de pixels")

    tarefas = [asyncio.create_task(loop()), asyncio.create_task(loop_tela())]
    yield
    for tarefa in tarefas:
        tarefa.cancel()


async def ao_iniciar(app):
    global vapid, sessao_push
    await db.conectar(DATABASE_URL)
    log.info("banco conectado")
    await tela_pixels.carregar()
    privada = VAPID_PRIVATE_KEY or await db.config_ou_padrao(
        "vapid_privada", webpush.Vapid.gerar(VAPID_SUBJECT).privada_b64())
    vapid = webpush.Vapid.de_privada_b64(privada, VAPID_SUBJECT)
    sessao_push = aiohttp.ClientSession()
    await db.apagar_expiradas(TTL_HORAS)
    if not SENHA_ADMIN:
        log.warning("ADMIN_PASSWORD não definida: ninguém conseguirá virar admin")
    elif len(SENHA_ADMIN) < 12 or SENHA_ADMIN.isdigit():
        log.warning("ADMIN_PASSWORD fraca: use 12+ caracteres misturando letras, números e símbolos")


async def ao_encerrar(app):
    for info in list(conexoes.values()):
        for ws in list(info["sockets"]):
            await ws.close(code=1001, message=b"servidor reiniciando")
    if tarefas_push:
        await asyncio.wait(tarefas_push, timeout=5)
    if sessao_push:
        await sessao_push.close()
    try:  # grava o que falta da tela antes de fechar o banco
        tela_pixels.para_enviar.clear()
        await tela_pixels.descarregar(transmitir)
        await tela_pixels.salvar()
    except Exception:
        log.exception("erro ao salvar a tela de pixels")
    await db.fechar()


def criar_app():
    app = web.Application(middlewares=[limite_por_ip, cabecalhos_seguranca], client_max_size=MAX_AUDIO_BYTES + 16 * 1024)
    app.router.add_get("/", pagina)
    app.router.add_get("/health", saude)
    app.router.add_get("/sw.js", service_worker)
    app.router.add_get("/manifest.webmanifest", manifesto)
    app.router.add_static("/icones", PASTA_STATIC / "icones")
    app.router.add_get("/api/push/chave", push_chave)
    app.router.add_post("/api/push/inscrever", push_inscrever)
    app.router.add_post("/api/push/cancelar", push_cancelar)
    app.router.add_post("/api/audio", audio_enviar)
    app.router.add_get("/api/tela", tela_imagem)
    app.router.add_get(r"/api/audio/{id:[A-Za-z0-9_-]{16,64}}", audio_ouvir)
    app.router.add_post("/api/entrar", entrar)
    app.router.add_post("/api/sair", sair)
    app.router.add_get("/ws", websocket)
    app.on_startup.append(ao_iniciar)
    app.on_shutdown.append(ao_encerrar)
    app.cleanup_ctx.append(manutencao)
    return app


if __name__ == "__main__":
    if not DATABASE_URL:
        raise SystemExit("Defina a variável de ambiente DATABASE_URL (ex.: postgresql://usuario:senha@host:5432/banco)")
    log.info("chat ouvindo em http://0.0.0.0:%d", PORTA)
    web.run_app(criar_app(), host="0.0.0.0", port=PORTA, access_log=None, print=None)
