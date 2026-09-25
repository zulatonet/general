"""Acesso ao banco PostgreSQL (Supabase, Neon, Postgres do Easypanel etc.).

As mensagens referenciam usuários por ID, não por apelido: trocar o apelido
mantém o histórico e ninguém "herda" conversas de outro ao escolher o mesmo nome.

Tipos de mensagem (tabela `mensagens`):
- Mural (Geral): destinatario_id IS NULL e sala_id IS NULL — não expira.
- Privada:      destinatario_id preenchido — expira (PRIVATE_TTL_HOURS).
- Sala:         sala_id preenchido — expira (PRIVATE_TTL_HOURS).
"""
from urllib.parse import urlparse

import asyncpg

pool: asyncpg.Pool | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id            SERIAL PRIMARY KEY,
    apelido       TEXT NOT NULL,
    senha_hash    TEXT NOT NULL,
    is_admin      BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultimo_acesso TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_apelido ON usuarios (lower(apelido));
-- Vários admins; só um master (quem assumiu com /admin SENHA).
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS is_master BOOLEAN NOT NULL DEFAULT FALSE;
DROP INDEX IF EXISTS idx_usuarios_um_admin;
UPDATE usuarios SET is_master = TRUE
    WHERE is_admin AND NOT EXISTS (SELECT 1 FROM usuarios WHERE is_master);
CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_um_master ON usuarios (is_master) WHERE is_master;
-- Anti-flood: avisos do dia e bloqueio de envio.
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS avisos_flood INTEGER NOT NULL DEFAULT 0;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS avisos_dia DATE;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS bloqueado_ate TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS sessoes (
    token_hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    criado_em  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expira_em  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessoes_usuario ON sessoes (usuario_id);

CREATE TABLE IF NOT EXISTS salas (
    id         SERIAL PRIMARY KEY,
    nome       TEXT NOT NULL,
    senha_hash TEXT NOT NULL,
    dono_id    INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    criado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_salas_nome ON salas (lower(nome));

CREATE TABLE IF NOT EXISTS sala_membros (
    sala_id    INTEGER NOT NULL REFERENCES salas(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    entrou_em  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sala_id, usuario_id)
);
CREATE INDEX IF NOT EXISTS idx_sala_membros_usuario ON sala_membros (usuario_id);

CREATE TABLE IF NOT EXISTS contatos (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    contato_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, contato_id)
);

CREATE TABLE IF NOT EXISTS mensagens (
    id              BIGSERIAL PRIMARY KEY,
    remetente_id    INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    destinatario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
    texto           TEXT NOT NULL,
    enviado_em      TIMESTAMPTZ NOT NULL DEFAULT now(),
    lida            BOOLEAN NOT NULL DEFAULT FALSE
);
ALTER TABLE mensagens ADD COLUMN IF NOT EXISTS sala_id INTEGER REFERENCES salas(id) ON DELETE CASCADE;
DROP INDEX IF EXISTS idx_msg_geral;
CREATE INDEX IF NOT EXISTS idx_msg_mural ON mensagens (id) WHERE destinatario_id IS NULL AND sala_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_msg_priv ON mensagens (remetente_id, destinatario_id, id);
CREATE INDEX IF NOT EXISTS idx_msg_dest ON mensagens (destinatario_id, id);
CREATE INDEX IF NOT EXISTS idx_msg_sala ON mensagens (sala_id, id) WHERE sala_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_msg_nao_lidas ON mensagens (destinatario_id) WHERE NOT lida;
CREATE INDEX IF NOT EXISTS idx_msg_expira ON mensagens (enviado_em) WHERE destinatario_id IS NOT NULL OR sala_id IS NOT NULL;

-- Áudios (até 10 s). O arquivo fica em `audios`, ligado à mensagem: apagar a
-- mensagem (expiração, /apagar) apaga o áudio junto. No privado o áudio é de
-- ouvir uma vez: ao ser ouvido, o arquivo é apagado e a mensagem fica "ouvido".
ALTER TABLE mensagens ADD COLUMN IF NOT EXISTS audio_id TEXT;
ALTER TABLE mensagens ADD COLUMN IF NOT EXISTS audio_duracao_ms INTEGER;
ALTER TABLE mensagens ADD COLUMN IF NOT EXISTS audio_unico BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE mensagens ADD COLUMN IF NOT EXISTS audio_ouvido BOOLEAN NOT NULL DEFAULT FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_audio ON mensagens (audio_id) WHERE audio_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS audios (
    id          TEXT PRIMARY KEY,
    mensagem_id BIGINT NOT NULL REFERENCES mensagens(id) ON DELETE CASCADE,
    mime        TEXT NOT NULL,
    dados       BYTEA NOT NULL,
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audios_mensagem ON audios (mensagem_id);

-- Configurações geradas pelo próprio chat (ex.: chaves VAPID do push).
CREATE TABLE IF NOT EXISTS config (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

-- Aparelhos inscritos para receber notificações (Web Push).
CREATE TABLE IF NOT EXISTS push_inscricoes (
    endpoint   TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    p256dh     TEXT NOT NULL,
    auth       TEXT NOT NULL,
    criado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_push_usuario ON push_inscricoes (usuario_id);

-- Bloqueia a API REST pública do Supabase (anon/authenticated) nestas tabelas.
-- O chat conecta como dono das tabelas, que não é afetado pelo RLS.
ALTER TABLE usuarios     ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessoes      ENABLE ROW LEVEL SECURITY;
ALTER TABLE salas        ENABLE ROW LEVEL SECURITY;
ALTER TABLE sala_membros ENABLE ROW LEVEL SECURITY;
ALTER TABLE contatos     ENABLE ROW LEVEL SECURITY;
ALTER TABLE mensagens    ENABLE ROW LEVEL SECURITY;
ALTER TABLE config       ENABLE ROW LEVEL SECURITY;
ALTER TABLE audios       ENABLE ROW LEVEL SECURITY;
ALTER TABLE push_inscricoes ENABLE ROW LEVEL SECURITY;
"""

# Mensagem "viva": do Mural, ou privada/sala dentro da validade ($ttl em horas).
FILTRO_VALIDADE = "(m.enviado_em > now() - make_interval(hours => {p}))"


def _ssl_para(dsn):
    """Exige conexão criptografada com bancos externos (ex.: Supabase).

    Respeita `sslmode` se vier na DATABASE_URL. Bancos locais ou na rede interna
    do Easypanel (host sem ponto, ex.: "salavip_db") ficam como estão.
    """
    if "sslmode=" in dsn:
        return None
    host = (urlparse(dsn).hostname or "").lower()
    if not host or host in ("localhost", "127.0.0.1", "::1") or "." not in host:
        return None
    return "require"


async def conectar(dsn):
    global pool
    # statement_cache_size=0: compatível com poolers em modo transação
    # (ex.: Supabase na porta 6543 / PgBouncer).
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, statement_cache_size=0, ssl=_ssl_para(dsn))
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)


async def fechar():
    if pool:
        await pool.close()


async def ping():
    return await pool.fetchval("SELECT 1") == 1


# ---------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------
async def buscar_usuario_por_apelido(apelido):
    return await pool.fetchrow(
        "SELECT id, apelido, senha_hash, is_admin FROM usuarios WHERE lower(apelido) = lower($1)",
        apelido,
    )


async def criar_usuario(apelido, senha_hash):
    """Retorna o id do novo usuário, ou None se o apelido já existir."""
    return await pool.fetchval(
        """INSERT INTO usuarios (apelido, senha_hash) VALUES ($1, $2)
           ON CONFLICT DO NOTHING RETURNING id""",
        apelido, senha_hash,
    )


async def listar_usuarios():
    return await pool.fetch("SELECT id, apelido FROM usuarios ORDER BY lower(apelido)")


async def atualizar_ultimo_acesso(usuario_id):
    await pool.execute("UPDATE usuarios SET ultimo_acesso = now() WHERE id = $1", usuario_id)


async def trocar_apelido(usuario_id, novo_apelido):
    """Retorna False se o novo apelido já estiver em uso."""
    try:
        await pool.execute("UPDATE usuarios SET apelido = $1 WHERE id = $2", novo_apelido, usuario_id)
        return True
    except asyncpg.UniqueViolationError:
        return False


async def trocar_senha(usuario_id, senha_hash):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE usuarios SET senha_hash = $1 WHERE id = $2", senha_hash, usuario_id)
        await conn.execute("DELETE FROM sessoes WHERE usuario_id = $1", usuario_id)


# ---------------------------------------------------------------
# Sessões
# ---------------------------------------------------------------
async def criar_sessao(token_hash, usuario_id, dias):
    await pool.execute(
        "INSERT INTO sessoes (token_hash, usuario_id, expira_em) VALUES ($1, $2, now() + make_interval(days => $3))",
        token_hash, usuario_id, dias,
    )


async def buscar_sessao(token_hash):
    return await pool.fetchrow(
        """SELECT u.id, u.apelido FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id
           WHERE s.token_hash = $1 AND s.expira_em > now()""",
        token_hash,
    )


async def apagar_sessao(token_hash):
    await pool.execute("DELETE FROM sessoes WHERE token_hash = $1", token_hash)


async def limpar_sessoes_expiradas():
    await pool.execute("DELETE FROM sessoes WHERE expira_em <= now()")


# ---------------------------------------------------------------
# Anti-flood
# ---------------------------------------------------------------
async def bloqueio_atual(usuario_id):
    """Retorna o fim do bloqueio de envio, se ainda estiver valendo."""
    return await pool.fetchval(
        "SELECT bloqueado_ate FROM usuarios WHERE id = $1 AND bloqueado_ate > now()", usuario_id
    )


async def registrar_flood(usuario_id, fuso, max_avisos, minutos_trava, horas_trava_final):
    """Conta um aviso no dia (no fuso informado) e trava o envio.

    Até `max_avisos` avisos no dia: trava por `minutos_trava`.
    Passou disso: trava por `horas_trava_final`.
    Retorna (avisos_no_dia, bloqueado_ate).
    """
    row = await pool.fetchrow(
        """WITH hoje AS (SELECT (now() AT TIME ZONE $2)::date AS d)
           UPDATE usuarios SET
             avisos_flood = CASE WHEN avisos_dia = hoje.d THEN avisos_flood + 1 ELSE 1 END,
             avisos_dia = hoje.d,
             bloqueado_ate = now() + CASE
               WHEN (CASE WHEN avisos_dia = hoje.d THEN avisos_flood + 1 ELSE 1 END) > $3
               THEN make_interval(hours => $5) ELSE make_interval(mins => $4) END
           FROM hoje WHERE id = $1
           RETURNING avisos_flood, bloqueado_ate""",
        usuario_id, fuso, max_avisos, minutos_trava, horas_trava_final,
    )
    return row["avisos_flood"], row["bloqueado_ate"]


async def liberar_bloqueio(usuario_id):
    await pool.execute(
        "UPDATE usuarios SET bloqueado_ate = NULL, avisos_flood = 0 WHERE id = $1", usuario_id
    )


# ---------------------------------------------------------------
# Admin e Master
# ---------------------------------------------------------------
# Papéis: 0 = usuário, 1 = admin, 2 = master (admin com poder total).
USUARIO, ADMIN, MASTER = 0, 1, 2


async def papel(usuario_id):
    row = await pool.fetchrow("SELECT is_admin, is_master FROM usuarios WHERE id = $1", usuario_id)
    if not row:
        return USUARIO
    return MASTER if row["is_master"] else ADMIN if row["is_admin"] else USUARIO


async def buscar_master():
    return await pool.fetchrow("SELECT id, apelido, ultimo_acesso FROM usuarios WHERE is_master LIMIT 1")


async def listar_admins():
    return await pool.fetch("SELECT apelido, is_master FROM usuarios WHERE is_admin ORDER BY is_master DESC, lower(apelido)")


async def assumir_master_se_vago(usuario_id):
    """Torna master só se ainda não houver um. Retorna True se conseguiu."""
    try:
        resultado = await pool.execute(
            """UPDATE usuarios SET is_admin = TRUE, is_master = TRUE
               WHERE id = $1 AND NOT EXISTS (SELECT 1 FROM usuarios WHERE is_master)""",
            usuario_id,
        )
    except asyncpg.UniqueViolationError:
        return False
    return resultado == "UPDATE 1"


async def transferir_master(usuario_id):
    """Passa o master para usuario_id; o master anterior continua admin."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE usuarios SET is_master = FALSE WHERE is_master")
        await conn.execute("UPDATE usuarios SET is_admin = TRUE, is_master = TRUE WHERE id = $1", usuario_id)


async def remover_master():
    """Tira o master (ele continua admin comum)."""
    await pool.execute("UPDATE usuarios SET is_master = FALSE WHERE is_master")


async def definir_admin(usuario_id, admin):
    await pool.execute(
        "UPDATE usuarios SET is_admin = $1 WHERE id = $2 AND NOT is_master", admin, usuario_id
    )


# ---------------------------------------------------------------
# Contatos (fixados)
# ---------------------------------------------------------------
async def listar_contatos(usuario_id):
    rows = await pool.fetch(
        """SELECT u.apelido FROM contatos c JOIN usuarios u ON u.id = c.contato_id
           WHERE c.usuario_id = $1 ORDER BY lower(u.apelido)""",
        usuario_id,
    )
    return [r["apelido"] for r in rows]


async def fixar_contato(usuario_id, contato_id, fixo):
    if fixo:
        await pool.execute(
            "INSERT INTO contatos (usuario_id, contato_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            usuario_id, contato_id,
        )
    else:
        await pool.execute("DELETE FROM contatos WHERE usuario_id = $1 AND contato_id = $2", usuario_id, contato_id)


# ---------------------------------------------------------------
# Salas
# ---------------------------------------------------------------
async def criar_sala(nome, senha_hash, dono_id):
    """Cria a sala com o dono como membro. Retorna o id, ou None se o nome existir."""
    async with pool.acquire() as conn, conn.transaction():
        sala_id = await conn.fetchval(
            "INSERT INTO salas (nome, senha_hash, dono_id) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING RETURNING id",
            nome, senha_hash, dono_id,
        )
        if sala_id:
            await conn.execute("INSERT INTO sala_membros (sala_id, usuario_id) VALUES ($1, $2)", sala_id, dono_id)
        return sala_id


async def contar_salas_do_dono(dono_id):
    return await pool.fetchval("SELECT COUNT(*) FROM salas WHERE dono_id = $1", dono_id)


async def buscar_sala(nome):
    return await pool.fetchrow(
        """SELECT s.id, s.nome, s.senha_hash, s.dono_id, u.apelido AS dono
           FROM salas s JOIN usuarios u ON u.id = s.dono_id WHERE lower(s.nome) = lower($1)""",
        nome,
    )


async def listar_salas(usuario_id):
    return await pool.fetch(
        """SELECT s.nome, u.apelido AS dono,
                  (SELECT COUNT(*) FROM sala_membros sm WHERE sm.sala_id = s.id) AS membros,
                  EXISTS (SELECT 1 FROM sala_membros sm WHERE sm.sala_id = s.id AND sm.usuario_id = $1) AS membro
           FROM salas s JOIN usuarios u ON u.id = s.dono_id
           ORDER BY lower(s.nome)""",
        usuario_id,
    )


async def eh_membro(sala_id, usuario_id):
    return bool(await pool.fetchval(
        "SELECT 1 FROM sala_membros WHERE sala_id = $1 AND usuario_id = $2", sala_id, usuario_id
    ))


async def adicionar_membro(sala_id, usuario_id):
    """Retorna False se já era membro."""
    resultado = await pool.execute(
        "INSERT INTO sala_membros (sala_id, usuario_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        sala_id, usuario_id,
    )
    return resultado == "INSERT 0 1"


async def remover_membro(sala_id, usuario_id):
    resultado = await pool.execute(
        "DELETE FROM sala_membros WHERE sala_id = $1 AND usuario_id = $2", sala_id, usuario_id
    )
    return resultado == "DELETE 1"


async def membros_da_sala(sala_id):
    rows = await pool.fetch("SELECT usuario_id FROM sala_membros WHERE sala_id = $1", sala_id)
    return [r["usuario_id"] for r in rows]


async def apagar_sala(sala_id):
    await pool.execute("DELETE FROM salas WHERE id = $1", sala_id)


# ---------------------------------------------------------------
# Mensagens
# ---------------------------------------------------------------
async def salvar_mensagem(remetente_id, destinatario_id, texto, sala_id=None):
    return await pool.fetchval(
        """INSERT INTO mensagens (remetente_id, destinatario_id, sala_id, texto)
           VALUES ($1, $2, $3, $4) RETURNING enviado_em""",
        remetente_id, destinatario_id, sala_id, texto,
    )


async def carregar_historico(usuario_id, ttl_horas, limite_mural=50, limite_privadas=500, limite_salas=500):
    mural = await pool.fetch(
        """SELECT * FROM (
             SELECT m.id, u.apelido AS remetente, m.texto, m.enviado_em, m.audio_id, m.audio_duracao_ms, m.audio_unico, m.audio_ouvido
             FROM mensagens m JOIN usuarios u ON u.id = m.remetente_id
             WHERE m.destinatario_id IS NULL AND m.sala_id IS NULL ORDER BY m.id DESC LIMIT $1
           ) t ORDER BY id""",
        limite_mural,
    )
    privadas = await pool.fetch(
        f"""SELECT * FROM (
              SELECT m.id, r.apelido AS remetente, d.apelido AS destinatario, m.texto, m.enviado_em, m.audio_id, m.audio_duracao_ms, m.audio_unico, m.audio_ouvido
              FROM mensagens m
              JOIN usuarios r ON r.id = m.remetente_id
              JOIN usuarios d ON d.id = m.destinatario_id
              WHERE (m.remetente_id = $1 OR m.destinatario_id = $1) AND {FILTRO_VALIDADE.format(p="$3")}
              ORDER BY m.id DESC LIMIT $2
            ) t ORDER BY id""",
        usuario_id, limite_privadas, ttl_horas,
    )
    salas = await pool.fetch(
        f"""SELECT * FROM (
              SELECT m.id, s.nome AS sala, u.apelido AS remetente, m.texto, m.enviado_em, m.audio_id, m.audio_duracao_ms, m.audio_unico, m.audio_ouvido
              FROM mensagens m
              JOIN salas s ON s.id = m.sala_id
              JOIN sala_membros sm ON sm.sala_id = m.sala_id AND sm.usuario_id = $1
              JOIN usuarios u ON u.id = m.remetente_id
              WHERE {FILTRO_VALIDADE.format(p="$3")}
              ORDER BY m.id DESC LIMIT $2
            ) t ORDER BY id""",
        usuario_id, limite_salas, ttl_horas,
    )
    return mural, privadas, salas


async def historico_sala(sala_id, ttl_horas, limite=200):
    return await pool.fetch(
        f"""SELECT * FROM (
              SELECT m.id, u.apelido AS remetente, m.texto, m.enviado_em, m.audio_id, m.audio_duracao_ms, m.audio_unico, m.audio_ouvido
              FROM mensagens m JOIN usuarios u ON u.id = m.remetente_id
              WHERE m.sala_id = $1 AND {FILTRO_VALIDADE.format(p="$3")}
              ORDER BY m.id DESC LIMIT $2
            ) t ORDER BY id""",
        sala_id, limite, ttl_horas,
    )


async def contar_nao_lidas(usuario_id, ttl_horas):
    rows = await pool.fetch(
        f"""SELECT u.apelido, COUNT(*) FROM mensagens m JOIN usuarios u ON u.id = m.remetente_id
            WHERE m.destinatario_id = $1 AND NOT m.lida AND {FILTRO_VALIDADE.format(p="$2")}
            GROUP BY u.apelido""",
        usuario_id, ttl_horas,
    )
    return {r[0]: r[1] for r in rows}


async def marcar_como_lidas(destinatario_id, remetente_id):
    await pool.execute(
        "UPDATE mensagens SET lida = TRUE WHERE destinatario_id = $1 AND remetente_id = $2 AND NOT lida",
        destinatario_id, remetente_id,
    )


async def apagar_expiradas(ttl_horas):
    """Apaga privadas e de salas mais velhas que ttl_horas. Retorna quantas."""
    resultado = await pool.execute(
        """DELETE FROM mensagens
           WHERE (destinatario_id IS NOT NULL OR sala_id IS NOT NULL)
             AND enviado_em <= now() - make_interval(hours => $1)""",
        ttl_horas,
    )
    return int(resultado.split()[-1])


async def apagar_mural():
    await pool.execute("DELETE FROM mensagens WHERE destinatario_id IS NULL AND sala_id IS NULL")


async def apagar_conversa_privada(a, b):
    await pool.execute(
        """DELETE FROM mensagens
           WHERE (remetente_id = $1 AND destinatario_id = $2) OR (remetente_id = $2 AND destinatario_id = $1)""",
        a, b,
    )


async def apagar_mensagens_da_sala(sala_id):
    await pool.execute("DELETE FROM mensagens WHERE sala_id = $1", sala_id)


async def apagar_mensagens_de(usuario_id):
    await pool.execute("DELETE FROM mensagens WHERE remetente_id = $1", usuario_id)


async def apagar_tudo():
    await pool.execute("DELETE FROM mensagens")


# ---------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------
async def config_ou_padrao(chave, padrao):
    """Lê a configuração; se não existir, grava `padrao` (quem gravar primeiro vence)."""
    await pool.execute("INSERT INTO config (chave, valor) VALUES ($1, $2) ON CONFLICT DO NOTHING", chave, padrao)
    return await pool.fetchval("SELECT valor FROM config WHERE chave = $1", chave)


# ---------------------------------------------------------------
# Push (notificações)
# ---------------------------------------------------------------
MAX_APARELHOS = 10


async def salvar_inscricao(usuario_id, endpoint, p256dh, auth):
    """Liga o aparelho ao usuário (se era de outro, passa a ser deste). Guarda no máximo MAX_APARELHOS."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO push_inscricoes (endpoint, usuario_id, p256dh, auth) VALUES ($1, $2, $3, $4)
               ON CONFLICT (endpoint) DO UPDATE
               SET usuario_id = EXCLUDED.usuario_id, p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth, criado_em = now()""",
            endpoint, usuario_id, p256dh, auth,
        )
        await conn.execute(
            """DELETE FROM push_inscricoes WHERE usuario_id = $1 AND endpoint NOT IN (
                 SELECT endpoint FROM push_inscricoes WHERE usuario_id = $1 ORDER BY criado_em DESC LIMIT $2)""",
            usuario_id, MAX_APARELHOS,
        )


async def apagar_inscricao(endpoint, usuario_id=None):
    if usuario_id is None:
        await pool.execute("DELETE FROM push_inscricoes WHERE endpoint = $1", endpoint)
    else:
        await pool.execute("DELETE FROM push_inscricoes WHERE endpoint = $1 AND usuario_id = $2", endpoint, usuario_id)


async def inscricoes_de(usuario_ids):
    return await pool.fetch(
        "SELECT usuario_id, endpoint, p256dh, auth FROM push_inscricoes WHERE usuario_id = ANY($1::int[])",
        list(usuario_ids),
    )


async def inscricoes_exceto(usuario_id):
    return await pool.fetch(
        "SELECT usuario_id, endpoint, p256dh, auth FROM push_inscricoes WHERE usuario_id <> $1", usuario_id
    )


# ---------------------------------------------------------------
# Áudios
# ---------------------------------------------------------------
async def salvar_audio(audio_id, remetente_id, destinatario_id, texto, duracao_ms, unico, mime, dados):
    """Grava a mensagem de áudio e o arquivo juntos. Retorna enviado_em."""
    async with pool.acquire() as conn, conn.transaction():
        msg = await conn.fetchrow(
            """INSERT INTO mensagens (remetente_id, destinatario_id, texto, audio_id, audio_duracao_ms, audio_unico)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id, enviado_em""",
            remetente_id, destinatario_id, texto, audio_id, duracao_ms, unico,
        )
        await conn.execute(
            "INSERT INTO audios (id, mensagem_id, mime, dados) VALUES ($1, $2, $3, $4)",
            audio_id, msg["id"], mime, dados,
        )
        return msg["enviado_em"]


async def info_audio(audio_id):
    """Dados da mensagem do áudio (existe mesmo depois de ouvido) e se o arquivo ainda existe."""
    return await pool.fetchrow(
        """SELECT m.remetente_id, m.destinatario_id, m.sala_id, m.audio_unico,
                  EXISTS (SELECT 1 FROM audios a WHERE a.id = m.audio_id) AS disponivel
           FROM mensagens m WHERE m.audio_id = $1""",
        audio_id,
    )


async def ler_audio(audio_id):
    return await pool.fetchrow("SELECT mime, dados FROM audios WHERE id = $1", audio_id)


async def consumir_audio(audio_id):
    """Entrega o áudio de ouvir-uma-vez e apaga o arquivo. Só um pedido consegue (None para os outros)."""
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow("DELETE FROM audios WHERE id = $1 RETURNING mime, dados", audio_id)
        if row:
            await conn.execute("UPDATE mensagens SET audio_ouvido = TRUE WHERE audio_id = $1", audio_id)
        return row
