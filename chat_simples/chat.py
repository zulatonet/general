import asyncio
import json
import os
import sqlite3
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import websockets

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat.db")
PORTA_WEB = 8082
PORTA_WS = 8081
SENHA_ADMIN = "1350"
TEMPO_MINIMO_RESET = timedelta(hours=1)

# ---------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT UNIQUE NOT NULL,
            apelido TEXT NOT NULL,
            criado_em TEXT NOT NULL,
            ultimo_acesso TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            remetente TEXT NOT NULL,
            destinatario TEXT,
            texto TEXT NOT NULL,
            enviado_em TEXT NOT NULL,
            lida INTEGER DEFAULT 0
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_msg_geral ON mensagens(destinatario, enviado_em)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_msg_priv ON mensagens(remetente, destinatario, enviado_em)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_msg_nao_lidas ON mensagens(destinatario, lida)")
    conn.commit()
    conn.close()

def salvar_mensagem(remetente, destinatario, texto):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO mensagens (remetente, destinatario, texto, enviado_em, lida) VALUES (?, ?, ?, ?, ?)",
        (remetente, destinatario, texto, datetime.now().isoformat(timespec="seconds"), 0)
    )
    conn.commit()
    conn.close()

def carregar_historico(apelido):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT remetente, texto, enviado_em FROM mensagens
        WHERE destinatario IS NULL
        ORDER BY id DESC LIMIT 50
    """)
    geral = [{"remetente": r[0], "texto": r[1], "hora": r[2]} for r in reversed(c.fetchall())]
    c.execute("""
        SELECT remetente, destinatario, texto, enviado_em FROM mensagens
        WHERE (destinatario = ? OR remetente = ?) AND destinatario IS NOT NULL
        ORDER BY id ASC LIMIT 500
    """, (apelido, apelido))
    privadas = {}
    for r in c.fetchall():
        remetente, destinatario, texto, hora = r
        interlocutor = destinatario if remetente == apelido else remetente
        privadas.setdefault(interlocutor, []).append({
            "remetente": remetente, "destinatario": destinatario, "texto": texto, "hora": hora
        })
    conn.close()
    return {"geral": geral, "privadas": privadas}

def contar_nao_lidas(apelido):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT remetente, COUNT(*) FROM mensagens
        WHERE destinatario = ? AND lida = 0
        GROUP BY remetente
    """, (apelido,))
    resultado = {r[0]: r[1] for r in c.fetchall()}
    conn.close()
    return resultado

def marcar_como_lidas(destinatario, remetente):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE mensagens SET lida = 1 WHERE destinatario = ? AND remetente = ? AND lida = 0",
        (destinatario, remetente)
    )
    conn.commit()
    conn.close()

def registrar_usuario(device_id, apelido):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    agora = datetime.now().isoformat(timespec="seconds")
    c.execute("SELECT id FROM usuarios WHERE device_id = ?", (device_id,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE usuarios SET apelido = ?, ultimo_acesso = ? WHERE device_id = ?",
                  (apelido, agora, device_id))
    else:
        c.execute("INSERT INTO usuarios (device_id, apelido, criado_em, ultimo_acesso) VALUES (?, ?, ?, ?)",
                  (device_id, apelido, agora, agora))
    conn.commit()
    conn.close()

def listar_todos_usuarios():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT device_id, apelido FROM usuarios ORDER BY apelido")
    resultado = [{"device_id": r[0], "apelido": r[1]} for r in c.fetchall()]
    conn.close()
    return resultado

def buscar_apelido_por_device(device_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT apelido FROM usuarios WHERE device_id = ?", (device_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def buscar_usuario(apelido):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT device_id, is_admin FROM usuarios WHERE apelido = ?", (apelido,))
    row = c.fetchone()
    conn.close()
    return row

def buscar_admin():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT device_id, apelido, ultimo_acesso FROM usuarios WHERE is_admin = 1 LIMIT 1")
    row = c.fetchone()
    conn.close()
    return row

def is_admin(device_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT is_admin FROM usuarios WHERE device_id = ?", (device_id,))
    row = c.fetchone()
    conn.close()
    return bool(row and row[0])

def existe_admin():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM usuarios WHERE is_admin = 1")
    row = c.fetchone()
    conn.close()
    return row[0] > 0

def tornar_admin(device_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE usuarios SET is_admin = 0")
    c.execute("UPDATE usuarios SET is_admin = 1 WHERE device_id = ?", (device_id,))
    conn.commit()
    conn.close()

def remover_admin():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE usuarios SET is_admin = 0")
    conn.commit()
    conn.close()

def atualizar_ultimo_acesso(device_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    agora = datetime.now().isoformat(timespec="seconds")
    c.execute("UPDATE usuarios SET ultimo_acesso = ? WHERE device_id = ?", (agora, device_id))
    conn.commit()
    conn.close()

def apagar_conversa_geral():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM mensagens WHERE destinatario IS NULL")
    conn.commit()
    conn.close()

def apagar_conversa_privada(a, b):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        DELETE FROM mensagens
        WHERE (remetente = ? AND destinatario = ?)
           OR (remetente = ? AND destinatario = ?)
    """, (a, b, b, a))
    conn.commit()
    conn.close()

def apagar_mensagens_de(apelido):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM mensagens WHERE remetente = ?", (apelido,))
    conn.commit()
    conn.close()

def apagar_tudo():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM mensagens")
    conn.commit()
    conn.close()

def trocar_apelido(device_id, novo_apelido):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE usuarios SET apelido = ? WHERE device_id = ?", (novo_apelido, device_id))
    conn.commit()
    conn.close()

# ---------------------------------------------------------------
# Texto do /help
# ---------------------------------------------------------------
HELP_TEXTO = """📖 Comandos disponíveis:

/admin 1350
  Vira Admin (só se ainda não houver um).

/admin transferir Nome
  Transfere a patente de Admin para Nome.

/admin reset 1350
  Remove o Admin atual (só se ele estiver offline há mais de 1h).

/nome Usuario NovoNome
  Troca o nome de Usuario para NovoNome.

/apagar
  Apaga o histórico da conversa aberta (Geral ou privada).

/apagar Usuario
  Apaga todas as mensagens que Usuario mandou (em todo lugar).

/apagar total
  Apaga todas as mensagens do chat (mantém usuários).

/help
  Mostra esta lista de comandos."""

# ---------------------------------------------------------------
# Página HTML
# ---------------------------------------------------------------
def gerar_html():
    return """<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Sala de Bate-Papo</title>
<style>
* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
html, body { margin: 0; padding: 0; height: 100%; overflow: hidden; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  background: #1e1e2f; color: #eee;
  display: flex; flex-direction: column;
  font-size: 16px;
}
#topo { padding: 10px 12px; background: #0a0a12; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; flex-shrink: 0; }
#meunome { font-weight: bold; font-size: 15px; display: flex; align-items: center; gap: 6px; }
#corpo { flex: 1; display: flex; overflow: hidden; min-height: 0; }
#sidebar { width: 150px; background: #14141f; padding: 8px; overflow-y: auto; flex-shrink: 0; }
#sidebar h3 { margin: 0 0 8px 0; font-size: 13px; color: #888; text-transform: uppercase; }
.usuario { padding: 10px 8px; cursor: pointer; border-radius: 8px; margin-bottom: 4px; font-size: 14px; word-break: break-word; line-height: 1.2; user-select: none; display: flex; align-items: center; gap: 6px; }
.usuario:active { background: #2a2a3f; }
.usuario.selecionado { background: #4a4a8f; }
.usuario.geral { background: #2a5a3f; }
.usuario.geral.selecionado { background: #3a8a5f; }
.bolinha { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.bolinha.online { background: #4caf50; box-shadow: 0 0 6px #4caf50; }
.bolinha.offline { background: #f44336; }
.badge-nao-lidas { background: #ff5252; color: white; font-size: 11px; font-weight: bold; border-radius: 10px; padding: 1px 6px; margin-left: auto; }
#chat { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
#chat-titulo { padding: 8px 12px; background: #0a0a12; font-size: 14px; color: #aac; border-bottom: 1px solid #222; flex-shrink: 0; }
#mensagens { flex: 1; padding: 12px; overflow-y: auto; }
.msg { margin-bottom: 8px; padding: 10px 14px; border-radius: 12px; max-width: 85%; font-size: 16px; line-height: 1.4; word-break: break-word; }
.msg.enviada { background: #4a4a8f; margin-left: auto; }
.msg.recebida { background: #2a2a3f; }
.msg.sistema { background: #333; color: #aaa; font-size: 13px; text-align: center; margin: 8px auto; max-width: 100%; }
.msg.confirmacao { background: #2a5a3f; color: #cfc; font-size: 13px; text-align: left; margin: 8px auto; max-width: 100%; white-space: pre-wrap; font-family: monospace; }
.msg .nome { font-weight: bold; font-size: 13px; color: #aac; margin-bottom: 2px; }
.msg .hora { font-size: 11px; color: #999; margin-top: 4px; }
#form { display: flex; padding: 8px; background: #14141f; gap: 6px; flex-shrink: 0; }
#texto { flex: 1; padding: 12px; border-radius: 8px; border: 1px solid #333; font-size: 16px; background: #1e1e2f; color: #eee; min-width: 0; }
#texto:disabled { opacity: 0.5; }
#enviar { padding: 12px 16px; border: none; border-radius: 8px; background: #4a4a8f; color: white; cursor: pointer; font-size: 16px; font-weight: bold; }
#enviar:disabled { opacity: 0.5; }
#modal-nome {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(0,0,0,0.8); display: flex; align-items: center; justify-content: center;
  z-index: 9999;
}
#modal-nome .caixa {
  background: #2a2a3f; padding: 30px; border-radius: 16px; max-width: 90%;
  width: 400px; text-align: center;
}
#modal-nome h2 { margin-bottom: 20px; font-size: 20px; }
#modal-nome input {
  width: 100%; padding: 12px; border-radius: 8px; border: 1px solid #444;
  font-size: 16px; background: #1e1e2f; color: #eee; margin-bottom: 12px;
}
#modal-nome button {
  width: 100%; padding: 12px; border: none; border-radius: 8px;
  background: #4a4a8f; color: white; font-size: 16px; font-weight: bold; cursor: pointer;
}
#modal-nome .erro { color: #ff6b6b; font-size: 13px; min-height: 18px; margin-bottom: 8px; }
.escondido { display: none !important; }
</style>
</head>
<body>
<div id="modal-nome">
  <div class="caixa">
    <h2>Escolha seu nome</h2>
    <div class="erro" id="modal-erro"></div>
    <input id="modal-input" placeholder="Seu nome" maxlength="20" autocomplete="off">
    <button id="modal-btn">Entrar</button>
  </div>
</div>

<div id="topo">
<div id="meunome"><span class="bolinha online"></span><span id="nome-texto">Conectando...</span></div>
</div>
<div id="corpo">
<div id="sidebar">
<h3>Usuários</h3>
<div id="lista"></div>
</div>
<div id="chat">
<div id="chat-titulo">📢 Geral</div>
<div id="mensagens"></div>
<div id="form">
<input id="texto" placeholder="Escolha uma sala..." disabled autocomplete="off">
<button id="enviar" disabled>Enviar</button>
</div>
</div>
</div>
<script>
let deviceId = localStorage.getItem("chat_device_id");
if (!deviceId) {
  deviceId = "dev_" + Math.random().toString(36).substring(2) + Date.now().toString(36);
  localStorage.setItem("chat_device_id", deviceId);
}
let nomeSalvo = localStorage.getItem("chat_nome") || "";

let ws = null;
let meuNome = "";
let selecionado = "GERAL";
let conversas = { "GERAL": [] };
let naoLidas = {};

function conectar() {
  const protocolo = location.protocol === "https:" ? "wss:" : "ws:";
  let wsUrl;
  if (location.port === "8082") {
    wsUrl = "ws://" + location.hostname + ":8081/chat/ws";
  } else {
    wsUrl = protocolo + "//" + location.host + "/chat/ws";
  }
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    ws.send(JSON.stringify({tipo: "identificar", device_id: deviceId, apelido: nomeSalvo || null}));
  };

  ws.onmessage = (event) => {
    const dados = JSON.parse(event.data);
    if (dados.tipo === "bemvindo") {
      meuNome = dados.nome;
      localStorage.setItem("chat_nome", meuNome);
      document.getElementById("nome-texto").textContent = "Voce e: " + meuNome;
      document.getElementById("modal-nome").classList.add("escondido");
      if (dados.historico) {
        conversas["GERAL"] = dados.historico.geral.map(m => ({
          remetente: m.remetente, texto: m.texto, hora: m.hora,
          classe: m.remetente === meuNome ? "enviada" : "recebida"
        }));
        for (const [interlocutor, msgs] of Object.entries(dados.historico.privadas || {})) {
          conversas[interlocutor] = msgs.map(m => ({
            remetente: m.remetente, texto: m.texto, hora: m.hora,
            classe: m.remetente === meuNome ? "enviada" : "recebida"
          }));
        }
      }
      if (dados.nao_lidas) {
        for (const [interlocutor, qtd] of Object.entries(dados.nao_lidas)) {
          naoLidas[interlocutor] = qtd;
        }
      }
      renderizarUsuarios();
      renderizarConversa();
    } else if (dados.tipo === "erro") {
      const modal = document.getElementById("modal-nome");
      if (!modal.classList.contains("escondido")) {
        document.getElementById("modal-erro").textContent = dados.mensagem;
      } else {
        adicionarSistema(dados.mensagem);
      }
    } else if (dados.tipo === "usuarios") {
      renderizarUsuarios(dados.usuarios);
    } else if (dados.tipo === "msg") {
      const interlocutor = dados.privado ? dados.de : "GERAL";
      if (!conversas[interlocutor]) conversas[interlocutor] = [];
      conversas[interlocutor].push({ remetente: dados.de, texto: dados.texto, hora: dados.hora, classe: "recebida" });
      if (selecionado === interlocutor) {
        renderizarConversa();
        if (dados.privado) ws.send(JSON.stringify({tipo: "marcar_lidas", interlocutor: interlocutor}));
      } else if (dados.privado) {
        naoLidas[interlocutor] = (naoLidas[interlocutor] || 0) + 1;
        tocarSom();
        renderizarUsuarios();
      }
    } else if (dados.tipo === "msg_enviada") {
      const interlocutor = dados.privado ? dados.para : "GERAL";
      if (!conversas[interlocutor]) conversas[interlocutor] = [];
      conversas[interlocutor].push({ remetente: meuNome, texto: dados.texto, hora: dados.hora, classe: "enviada" });
      if (selecionado === interlocutor) renderizarConversa();
    } else if (dados.tipo === "sistema") {
      adicionarSistema(dados.mensagem);
    } else if (dados.tipo === "comando_ok") {
      adicionarConfirmacao(dados.mensagem);
    }
  };
}

if (nomeSalvo) {
  conectar();
} else {
  document.getElementById("modal-nome").classList.remove("escondido");
}

document.getElementById("modal-btn").onclick = () => {
  const nome = document.getElementById("modal-input").value.trim();
  if (nome) {
    nomeSalvo = nome;
    localStorage.setItem("chat_nome", nome);
    conectar();
  }
};
document.getElementById("modal-input").addEventListener("keypress", (e) => {
  if (e.key === "Enter") document.getElementById("modal-btn").click();
});

const AudioCtx = window.AudioContext || window.webkitAudioContext;
let audioCtx = null;
function tocarSom() {
  try {
    if (!audioCtx) audioCtx = new AudioCtx();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sine"; osc.frequency.value = 880; gain.gain.value = 0.2;
    osc.connect(gain); gain.connect(audioCtx.destination);
    osc.start(); osc.stop(audioCtx.currentTime + 0.2);
  } catch (e) {}
}

function adicionarSistema(texto) {
  if (!conversas[selecionado]) conversas[selecionado] = [];
  conversas[selecionado].push({ remetente: "", texto: texto, hora: "", classe: "sistema" });
  renderizarConversa();
}

function adicionarConfirmacao(texto) {
  if (!conversas[selecionado]) conversas[selecionado] = [];
  conversas[selecionado].push({ remetente: "", texto: texto, hora: "", classe: "confirmacao" });
  renderizarConversa();
}

let ultimosUsuarios = [];

function renderizarUsuarios(usuarios) {
  if (usuarios) ultimosUsuarios = usuarios;
  const lista = document.getElementById("lista");
  lista.innerHTML = "";
  const divGeral = document.createElement("div");
  divGeral.className = "usuario geral" + (selecionado === "GERAL" ? " selecionado" : "");
  divGeral.innerHTML = '<span>📢</span><span>Geral</span>';
  divGeral.onclick = () => selecionar("GERAL");
  lista.appendChild(divGeral);
  const ordenados = [...ultimosUsuarios].sort((a, b) => {
    if (a.online !== b.online) return a.online ? -1 : 1;
    return a.apelido.localeCompare(b.apelido);
  });
  ordenados.filter(u => u.apelido !== meuNome).forEach(u => {
    const div = document.createElement("div");
    div.className = "usuario" + (u.apelido === selecionado ? " selecionado" : "");
    const bolinha = document.createElement("span");
    bolinha.className = "bolinha " + (u.online ? "online" : "offline");
    const nomeSpan = document.createElement("span");
    nomeSpan.textContent = u.apelido;
    div.appendChild(bolinha); div.appendChild(nomeSpan);
    if (naoLidas[u.apelido]) {
      const badge = document.createElement("span");
      badge.className = "badge-nao-lidas";
      badge.textContent = naoLidas[u.apelido];
      div.appendChild(badge);
    }
    div.onclick = () => selecionar(u.apelido);
    lista.appendChild(div);
  });
}

function selecionar(nome) {
  selecionado = nome;
  delete naoLidas[nome];
  document.getElementById("chat-titulo").textContent = nome === "GERAL" ? "📢 Geral" : "👤 " + nome;
  document.getElementById("texto").disabled = false;
  document.getElementById("enviar").disabled = false;
  document.getElementById("texto").placeholder = nome === "GERAL" ? "Mensagem para todos..." : "Mensagem para " + nome + "...";
  if (nome !== "GERAL") {
    ws.send(JSON.stringify({tipo: "marcar_lidas", interlocutor: nome}));
  }
  renderizarUsuarios();
  renderizarConversa();
  document.getElementById("texto").focus();
}

function renderizarConversa() {
  const container = document.getElementById("mensagens");
  container.innerHTML = "";
  const msgs = conversas[selecionado] || [];
  msgs.forEach(m => adicionarMensagemAoContainer(container, m.remetente, m.texto, m.classe, m.hora));
  container.scrollTop = container.scrollHeight;
}

function adicionarMensagemAoContainer(container, remetente, texto, classe, hora) {
  const div = document.createElement("div");
  div.className = "msg " + classe;
  if (remetente) {
    const n = document.createElement("div");
    n.className = "nome"; n.textContent = remetente;
    div.appendChild(n);
  }
  const c = document.createElement("div"); c.textContent = texto;
  div.appendChild(c);
  if (hora) {
    const h = document.createElement("div");
    h.className = "hora"; h.textContent = hora.slice(11, 16);
    div.appendChild(h);
  }
  container.appendChild(div);
}

function enviarMensagem() {
  const input = document.getElementById("texto");
  if (input.value.trim() && selecionado) {
    ws.send(JSON.stringify({para: selecionado === "GERAL" ? null : selecionado, texto: input.value}));
    input.value = "";
    input.focus();
  }
}

document.getElementById("enviar").onclick = enviarMensagem;
document.getElementById("texto").addEventListener("keypress", (e) => { if (e.key === "Enter") enviarMensagem(); });
</script>
</body>
</html>"""

# ---------------------------------------------------------------
# Servidor HTTP da página
# ---------------------------------------------------------------
class PaginaHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(gerar_html().encode("utf-8"))
    def log_message(self, format, *args):
        pass

def rodar_http():
    HTTPServer(("0.0.0.0", PORTA_WEB), PaginaHandler).serve_forever()

# ---------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------
clientes = {}

def nome_aleatorio():
    import random
    ADJ = ["Veloz", "Sombrio", "Dourado", "Selvagem", "Fantasma", "Errante", "Silencioso", "Radiante", "Feroz", "Misterioso"]
    SUB = ["Lobo", "Falcao", "Tigre", "Corvo", "Dragao", "Viajante", "Andarilho", "Cometa", "Fenix", "Nomade"]
    return f"{random.choice(ADJ)}{random.choice(SUB)}{random.randint(10,99)}"

def apelido_unico():
    apelidos_em_uso = {v["apelido"] for v in clientes.values()}
    nome = nome_aleatorio()
    while nome in apelidos_em_uso:
        nome = nome_aleatorio()
    return nome

async def enviar_lista_usuarios():
    todos = listar_todos_usuarios()
    online_ids = set(clientes.keys())
    lista = []
    vistos = set()
    for u in todos:
        lista.append({"apelido": u["apelido"], "online": u["device_id"] in online_ids})
        vistos.add(u["apelido"])
    for dev_id, info in clientes.items():
        if info["apelido"] not in vistos:
            lista.append({"apelido": info["apelido"], "online": True})
    msg = json.dumps({"tipo": "usuarios", "usuarios": lista})
    if clientes:
        await asyncio.gather(*[v["ws"].send(msg) for v in clientes.values()], return_exceptions=True)

async def handler(websocket):
    device_id = None
    apelido = None
    try:
        primeira = await websocket.recv()
        dados = json.loads(primeira)
        if dados.get("tipo") != "identificar":
            await websocket.close(); return
        device_id = dados.get("device_id")
        apelido_pedido = dados.get("apelido")
        if not device_id:
            await websocket.close(); return
        apelido_registrado = buscar_apelido_por_device(device_id)
        if apelido_registrado:
            apelido = apelido_registrado
        elif apelido_pedido:
            apelido = apelido_pedido
        else:
            apelido = apelido_unico()
        apelidos_em_uso = {v["apelido"]: k for k, v in clientes.items()}
        if apelido in apelidos_em_uso and apelidos_em_uso[apelido] != device_id:
            apelido = apelido_unico()
        clientes[device_id] = {"ws": websocket, "apelido": apelido}
        registrar_usuario(device_id, apelido)
        historico = carregar_historico(apelido)
        nao_lidas = contar_nao_lidas(apelido)
        await websocket.send(json.dumps({
            "tipo": "bemvindo",
            "nome": apelido,
            "historico": historico,
            "nao_lidas": nao_lidas
        }))
        await enviar_lista_usuarios()

        async for mensagem in websocket:
            dados = json.loads(mensagem)
            tipo = dados.get("tipo")
            if tipo == "marcar_lidas":
                interlocutor = dados.get("interlocutor")
                if interlocutor:
                    marcar_como_lidas(apelido, interlocutor)
            elif tipo == "identificar":
                pass
            else:
                destino = dados.get("para")
                texto = dados.get("texto", "").strip()
                if not texto: continue

                # -------------------------------------------------
                # COMANDOS
                # -------------------------------------------------
                if texto.startswith("/"):
                    partes = texto.split(maxsplit=3)
                    cmd = partes[0].lower()

                    # /help
                    if cmd == "/help":
                        if is_admin(device_id):
                            await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": HELP_TEXTO}))
                        continue

                    # /admin ...
                    if cmd == "/admin":
                        if len(partes) >= 2:
                            sub = partes[1].lower()
                            # /admin reset SENHA
                            if sub == "reset" and len(partes) >= 3 and partes[2] == SENHA_ADMIN:
                                admin_info = buscar_admin()
                                if admin_info:
                                    admin_online = admin_info[0] in clientes
                                    if admin_online:
                                        await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Admin esta online. Nao e possivel resetar."}))
                                    else:
                                        try:
                                            ultimo = datetime.fromisoformat(admin_info[2])
                                            if datetime.now() - ultimo < TEMPO_MINIMO_RESET:
                                                await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Admin esteve online recentemente. Aguarde mais tempo."}))
                                            else:
                                                remover_admin()
                                                await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Admin anterior removido. Use /admin " + SENHA_ADMIN + " para assumir."}))
                                        except Exception:
                                            remover_admin()
                                            await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Admin anterior removido. Use /admin " + SENHA_ADMIN + " para assumir."}))
                                else:
                                    await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Nao ha admin. Use /admin " + SENHA_ADMIN + " para assumir."}))
                                continue

                            # /admin transferir Nome
                            if sub == "transferir" and len(partes) >= 3:
                                if not is_admin(device_id):
                                    continue
                                alvo_nome = partes[2]
                                info = buscar_usuario(alvo_nome)
                                if info:
                                    tornar_admin(info[0])
                                    await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Admin transferido para " + alvo_nome + "."}))
                                else:
                                    await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Usuario " + alvo_nome + " nao encontrado."}))
                                continue

                            # /admin SENHA (virar admin)
                            if sub == SENHA_ADMIN:
                                if not existe_admin():
                                    tornar_admin(device_id)
                                    await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Voce agora e o Admin."}))
                                else:
                                    await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Ja existe um Admin."}))
                                continue
                        continue

                    # A partir daqui, só admin
                    if not is_admin(device_id):
                        continue

                    # /nome Usuario NovoNome
                    if cmd == "/nome":
                        if len(partes) >= 3:
                            alvo = partes[1]
                            novo_nome = partes[2].strip()[:20]
                            if novo_nome:
                                info = buscar_usuario(alvo)
                                if info:
                                    trocar_apelido(info[0], novo_nome)
                                    for dev, inf in clientes.items():
                                        if inf["apelido"] == alvo:
                                            inf["apelido"] = novo_nome
                                    await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Nome de " + alvo + " alterado para " + novo_nome + "."}))
                                    await enviar_lista_usuarios()
                                else:
                                    await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Usuario " + alvo + " nao encontrado."}))
                            else:
                                await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Nome invalido."}))
                        else:
                            await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Uso: /nome Usuario NovoNome"}))
                        continue

                    # /apagar ...
                    if cmd == "/apagar":
                        if len(partes) == 1:
                            if destino is None:
                                apagar_conversa_geral()
                                await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Historico do Geral apagado."}))
                            else:
                                apagar_conversa_privada(apelido, destino)
                                await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Conversa com " + destino + " apagada."}))
                                for dev, inf in clientes.items():
                                    if inf["apelido"] == destino:
                                        await inf["ws"].send(json.dumps({"tipo": "sistema", "mensagem": "Conversa apagada pelo Admin."}))
                        elif len(partes) == 2 and partes[1].lower() == "total":
                            apagar_tudo()
                            await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Todas as mensagens foram apagadas."}))
                            for dev, inf in clientes.items():
                                await inf["ws"].send(json.dumps({"tipo": "sistema", "mensagem": "Todas as mensagens foram apagadas pelo Admin."}))
                        else:
                            alvo = partes[1]
                            apagar_mensagens_de(alvo)
                            await websocket.send(json.dumps({"tipo": "comando_ok", "mensagem": "Mensagens de " + alvo + " apagadas."}))
                        continue

                    continue

                # -------------------------------------------------
                # MENSAGENS NORMAIS
                # -------------------------------------------------
                atualizar_ultimo_acesso(device_id)
                hora = datetime.now().isoformat(timespec="seconds")
                if destino is None:
                    salvar_mensagem(apelido, None, texto)
                    msg = json.dumps({"tipo": "msg", "de": apelido, "texto": texto, "privado": False, "hora": hora})
                    if clientes:
                        await asyncio.gather(*[v["ws"].send(msg) for v in clientes.values()], return_exceptions=True)
                else:
                    destino_ws = None
                    for dev, info in clientes.items():
                        if info["apelido"] == destino:
                            destino_ws = info["ws"]; break
                    salvar_mensagem(apelido, destino, texto)
                    if destino_ws:
                        await destino_ws.send(json.dumps({"tipo": "msg", "de": apelido, "texto": texto, "privado": True, "hora": hora}))
                    await websocket.send(json.dumps({"tipo": "msg_enviada", "para": destino, "texto": texto, "privado": True, "hora": hora}))
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if device_id and device_id in clientes:
            del clientes[device_id]
        await enviar_lista_usuarios()

async def main_ws():
    async with websockets.serve(handler, "0.0.0.0", PORTA_WS):
        await asyncio.Future()

if __name__ == "__main__":
    init_db()
    Thread(target=rodar_http, daemon=True).start()
    print(f"Página em http://0.0.0.0:{PORTA_WEB}")
    print(f"WebSocket em ws://0.0.0.0:{PORTA_WS}")
    asyncio.run(main_ws())