"""Sala de Bate-Papo: página + WebSocket numa única porta (aiohttp + PostgreSQL)."""
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

from aiohttp import WSMsgType, web

import db

# ---------------------------------------------------------------
# Configuração (variáveis de ambiente)
# ---------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SENHA_ADMIN = os.environ.get("ADMIN_PASSWORD", "")
PORTA = int(os.environ.get("PORT", "8080"))
TEMPO_MINIMO_RESET = timedelta(minutes=int(os.environ.get("ADMIN_RESET_MINUTES", "60")))
SESSAO_DIAS = int(os.environ.get("SESSION_DAYS", "30"))
NOME_COOKIE = "chat_sessao"

MAX_APELIDO = 20
MIN_SENHA = 6
MAX_SENHA = 128
MAX_TEXTO = 2000
APELIDO_VALIDO = re.compile(r"^[\w.-]{2,%d}$" % MAX_APELIDO)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("chat")

PAGINA = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")

HELP_ADMIN = """📖 Comandos de Admin:

/admin lista
  Mostra o Master e os Admins.

/nome Usuario NovoNome
  Troca o nome de Usuario para NovoNome (o histórico é mantido).

/senha Usuario NovaSenha
  Define uma nova senha para Usuario e desconecta as sessões dele.

/apagar
  Apaga o histórico da conversa aberta (Geral ou privada).

/apagar Usuario
  Apaga todas as mensagens que Usuario mandou (em todo lugar).

/help
  Mostra esta lista de comandos.

Admins não podem usar /nome, /senha ou /apagar Usuario
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


async def gerar_hash_senha(senha):
    salt = secrets.token_bytes(16)
    h = await asyncio.to_thread(_scrypt, senha, salt)
    return f"scrypt${salt.hex()}${h.hex()}"


async def conferir_senha(senha, senha_hash):
    try:
        _, salt, esperado = senha_hash.split("$")
    except ValueError:
        return False
    h = await asyncio.to_thread(_scrypt, senha, bytes.fromhex(salt))
    return hmac.compare_digest(h.hex(), esperado)


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def senha_admin_correta(tentativa):
    return bool(SENHA_ADMIN) and hmac.compare_digest(tentativa.encode(), SENHA_ADMIN.encode())


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

    def limpar(self):
        agora = time.monotonic()
        for chave in [k for k, f in self.eventos.items() if not f or agora - f[-1] > self.janela]:
            del self.eventos[chave]


limite_login = LimiteTaxa(10, 300)           # por IP
limite_mensagens = LimiteTaxa(20, 10)        # por usuário
limite_senha_admin = LimiteTaxa(5, 900)      # tentativas de senha de admin por usuário


def ip_cliente(request):
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


def validar_senha(senha):
    if not isinstance(senha, str) or not (MIN_SENHA <= len(senha) <= MAX_SENHA):
        return f"Senha deve ter de {MIN_SENHA} a {MAX_SENHA} caracteres."
    return None


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------
# Conexões em memória
# ---------------------------------------------------------------
# usuario_id -> {"apelido": str, "sockets": set[WebSocketResponse]}
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


async def transmitir(dados):
    msg = json.dumps(dados)
    sockets = [ws for info in conexoes.values() for ws in info["sockets"]]
    if sockets:
        await asyncio.gather(*[ws.send_str(msg) for ws in sockets], return_exceptions=True)


async def enviar_lista_usuarios():
    usuarios = await db.listar_usuarios()
    lista = [{"apelido": u["apelido"], "online": u["id"] in conexoes} for u in usuarios]
    await transmitir({"tipo": "usuarios", "usuarios": lista})


async def desconectar_usuario(usuario_id):
    info = conexoes.get(usuario_id)
    if info:
        for ws in list(info["sockets"]):
            await ws.close(code=4001, message=b"sessao encerrada")


# ---------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------
@web.middleware
async def cabecalhos_seguranca(request, handler):
    resposta = await handler(request)
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("Referrer-Policy", "same-origin")
    resposta.headers.setdefault("X-Frame-Options", "DENY")
    return resposta


async def pagina(request):
    return web.Response(
        text=PAGINA,
        content_type="text/html",
        headers={
            "Cache-Control": "no-cache",
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' ws: wss:; frame-ancestors 'none'"
            ),
        },
    )


async def saude(request):
    try:
        await db.ping()
    except Exception:
        log.exception("health: banco indisponível")
        return web.json_response({"status": "erro"}, status=503)
    return web.json_response({"status": "ok", "online": len(conexoes)})


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
    usuario = await db.buscar_usuario_por_apelido(apelido)
    if usuario:
        if not await conferir_senha(senha, usuario["senha_hash"]):
            return web.json_response({"erro": "Senha incorreta para este nome."}, status=401)
        usuario_id, apelido = usuario["id"], usuario["apelido"]
    else:
        usuario_id = await db.criar_usuario(apelido, await gerar_hash_senha(senha))
        if usuario_id is None:  # criado por outra requisição no mesmo instante
            return web.json_response({"erro": "Esse nome acabou de ser registrado. Tente outro."}, status=409)
        criado = True
        log.info("novo usuário: %s", apelido)

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
    info = conexoes.setdefault(usuario_id, {"apelido": sessao["apelido"], "sockets": set()})
    info["apelido"] = sessao["apelido"]
    info["sockets"].add(ws)
    try:
        await db.atualizar_ultimo_acesso(usuario_id)
        geral, privadas = await db.carregar_historico(usuario_id)
        historico_privadas = {}
        for m in privadas:
            interlocutor = m["destinatario"] if m["remetente"] == info["apelido"] else m["remetente"]
            historico_privadas.setdefault(interlocutor, []).append(
                {"remetente": m["remetente"], "texto": m["texto"], "hora": iso(m["enviado_em"])}
            )
        await enviar(ws, {
            "tipo": "bemvindo",
            "nome": info["apelido"],
            "historico": {
                "geral": [{"remetente": m["remetente"], "texto": m["texto"], "hora": iso(m["enviado_em"])} for m in geral],
                "privadas": historico_privadas,
            },
            "nao_lidas": await db.contar_nao_lidas(usuario_id),
        })
        await enviar_lista_usuarios()

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
                await enviar_lista_usuarios()
            except Exception:
                log.exception("erro ao finalizar conexão")
    return ws


async def tratar_mensagem(ws, usuario_id, dados):
    info = conexoes[usuario_id]
    tipo = dados.get("tipo")

    if tipo == "marcar_lidas":
        interlocutor = dados.get("interlocutor")
        if isinstance(interlocutor, str):
            alvo = await db.buscar_usuario_por_apelido(interlocutor)
            if alvo:
                await db.marcar_como_lidas(usuario_id, alvo["id"])
        return

    texto = dados.get("texto")
    destino = dados.get("para")
    if not isinstance(texto, str) or (destino is not None and not isinstance(destino, str)):
        return
    texto = texto.strip()
    if not texto:
        return
    if not limite_mensagens.permitir(usuario_id):
        await enviar(ws, {"tipo": "erro", "mensagem": "Devagar! Você está enviando mensagens rápido demais."})
        return
    if len(texto) > MAX_TEXTO:
        await enviar(ws, {"tipo": "erro", "mensagem": f"Mensagem muito longa (máximo {MAX_TEXTO} caracteres)."})
        return

    if texto.startswith("/"):
        await tratar_comando(ws, usuario_id, texto, destino)
        return

    await db.atualizar_ultimo_acesso(usuario_id)
    apelido = info["apelido"]
    if destino is None:
        hora = await db.salvar_mensagem(usuario_id, None, texto)
        await transmitir({"tipo": "msg", "de": apelido, "texto": texto, "privado": False, "hora": iso(hora)})
        return

    alvo = await db.buscar_usuario_por_apelido(destino)
    if not alvo or alvo["id"] == usuario_id:
        await enviar(ws, {"tipo": "erro", "mensagem": "Usuário não encontrado."})
        return
    hora = iso(await db.salvar_mensagem(usuario_id, alvo["id"], texto))
    await enviar_para_usuario(alvo["id"], {"tipo": "msg", "de": apelido, "texto": texto, "privado": True, "hora": hora})
    await enviar_para_usuario(usuario_id, {"tipo": "msg_enviada", "para": alvo["apelido"], "texto": texto, "privado": True, "hora": hora})


# ---------------------------------------------------------------
# Comandos (interceptados no servidor; comandos inválidos são ignorados)
# ---------------------------------------------------------------
async def tratar_comando(ws, usuario_id, texto, destino):
    partes = texto.split(maxsplit=3)
    cmd = partes[0].lower()

    async def ok(mensagem):
        await enviar(ws, {"tipo": "comando_ok", "mensagem": mensagem})

    # Comandos com a senha do admin: valem para qualquer um
    if cmd == "/admin" and len(partes) >= 2 and partes[1].lower() not in ("promover", "revogar", "transferir", "lista"):
        # /admin reset SENHA
        if partes[1].lower() == "reset":
            if len(partes) < 3 or not limite_senha_admin.permitir(usuario_id) or not senha_admin_correta(partes[2]):
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
        if not limite_senha_admin.permitir(usuario_id) or not senha_admin_correta(partes[1]):
            return
        if await db.assumir_master_se_vago(usuario_id):
            log.info("%s agora é master", conexoes[usuario_id]["apelido"])
            await ok("👑 Você agora é o Master.")
        else:
            await ok("Já existe um Master.")
        return

    # A partir daqui, só admin ou master
    meu_papel = await db.papel(usuario_id)
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

    if cmd == "/help":
        await ok(HELP_MASTER if meu_papel == db.MASTER else HELP_ADMIN)

    elif cmd == "/admin":
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
            await enviar_para_usuario(alvo["id"], {"tipo": "sistema", "mensagem": "🛡️ Você agora é Admin. Digite /help para ver os comandos."})
            await ok(f"{nome} agora é Admin.")
        elif sub == "revogar":
            if alvo_papel < db.ADMIN:
                await ok(f"{nome} não é Admin.")
                return
            await db.definir_admin(alvo["id"], False)
            log.info("admin de %s revogado", nome)
            await enviar_para_usuario(alvo["id"], {"tipo": "sistema", "mensagem": "Você não é mais Admin."})
            await ok(f"Admin de {nome} revogado.")
        else:  # transferir
            await db.transferir_master(alvo["id"])
            log.info("master transferido para %s", nome)
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
            await enviar_lista_usuarios()
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

    elif cmd == "/apagar":
        eu = conexoes[usuario_id]["apelido"]
        if len(partes) == 1:
            if destino is None:
                await db.apagar_conversa_geral()
                await transmitir({"tipo": "apagado", "escopo": "geral"})
                await ok("Histórico do Geral apagado.")
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


# ---------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------
async def manutencao(app):
    async def loop():
        while True:
            await asyncio.sleep(3600)
            try:
                await db.limpar_sessoes_expiradas()
                for limite in (limite_login, limite_mensagens, limite_senha_admin):
                    limite.limpar()
            except Exception:
                log.exception("erro na manutenção")

    tarefa = asyncio.create_task(loop())
    yield
    tarefa.cancel()


async def ao_iniciar(app):
    await db.conectar(DATABASE_URL)
    log.info("banco conectado")
    if not SENHA_ADMIN:
        log.warning("ADMIN_PASSWORD não definida: ninguém conseguirá virar admin")


async def ao_encerrar(app):
    for info in list(conexoes.values()):
        for ws in list(info["sockets"]):
            await ws.close(code=1001, message=b"servidor reiniciando")
    await db.fechar()


def criar_app():
    app = web.Application(middlewares=[cabecalhos_seguranca], client_max_size=64 * 1024)
    app.router.add_get("/", pagina)
    app.router.add_get("/health", saude)
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
