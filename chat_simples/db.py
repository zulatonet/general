"""Acesso ao banco PostgreSQL (Supabase, Neon, Postgres do Easypanel etc.).

As mensagens referenciam usuários por ID, não por apelido: trocar o apelido
mantém o histórico e ninguém "herda" conversas de outro ao escolher o mesmo nome.
"""
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
CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_um_admin ON usuarios (is_admin) WHERE is_admin;

CREATE TABLE IF NOT EXISTS sessoes (
    token_hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    criado_em  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expira_em  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessoes_usuario ON sessoes (usuario_id);

CREATE TABLE IF NOT EXISTS mensagens (
    id              BIGSERIAL PRIMARY KEY,
    remetente_id    INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    destinatario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
    texto           TEXT NOT NULL,
    enviado_em      TIMESTAMPTZ NOT NULL DEFAULT now(),
    lida            BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_msg_geral ON mensagens (id) WHERE destinatario_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_msg_priv ON mensagens (remetente_id, destinatario_id, id);
CREATE INDEX IF NOT EXISTS idx_msg_dest ON mensagens (destinatario_id, id);
CREATE INDEX IF NOT EXISTS idx_msg_nao_lidas ON mensagens (destinatario_id) WHERE NOT lida;
"""


async def conectar(dsn):
    global pool
    # statement_cache_size=0: compatível com poolers em modo transação
    # (ex.: Supabase na porta 6543 / PgBouncer).
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, statement_cache_size=0)
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
# Admin
# ---------------------------------------------------------------
async def buscar_admin():
    return await pool.fetchrow("SELECT id, apelido, ultimo_acesso FROM usuarios WHERE is_admin LIMIT 1")


async def is_admin(usuario_id):
    return bool(await pool.fetchval("SELECT is_admin FROM usuarios WHERE id = $1", usuario_id))


async def tornar_admin(usuario_id):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE usuarios SET is_admin = FALSE WHERE is_admin")
        await conn.execute("UPDATE usuarios SET is_admin = TRUE WHERE id = $1", usuario_id)


async def assumir_admin_se_vago(usuario_id):
    """Torna admin só se ainda não houver um. Retorna True se conseguiu."""
    try:
        resultado = await pool.execute(
            """UPDATE usuarios SET is_admin = TRUE
               WHERE id = $1 AND NOT EXISTS (SELECT 1 FROM usuarios WHERE is_admin)""",
            usuario_id,
        )
    except asyncpg.UniqueViolationError:
        return False
    return resultado == "UPDATE 1"


async def remover_admin():
    await pool.execute("UPDATE usuarios SET is_admin = FALSE WHERE is_admin")


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
# Mensagens
# ---------------------------------------------------------------
async def salvar_mensagem(remetente_id, destinatario_id, texto):
    return await pool.fetchval(
        "INSERT INTO mensagens (remetente_id, destinatario_id, texto) VALUES ($1, $2, $3) RETURNING enviado_em",
        remetente_id, destinatario_id, texto,
    )


async def carregar_historico(usuario_id, limite_geral=50, limite_privadas=500):
    geral = await pool.fetch(
        """SELECT * FROM (
             SELECT m.id, u.apelido AS remetente, m.texto, m.enviado_em
             FROM mensagens m JOIN usuarios u ON u.id = m.remetente_id
             WHERE m.destinatario_id IS NULL ORDER BY m.id DESC LIMIT $1
           ) t ORDER BY id""",
        limite_geral,
    )
    privadas = await pool.fetch(
        """SELECT * FROM (
             SELECT m.id, r.apelido AS remetente, d.apelido AS destinatario, m.texto, m.enviado_em
             FROM mensagens m
             JOIN usuarios r ON r.id = m.remetente_id
             JOIN usuarios d ON d.id = m.destinatario_id
             WHERE m.remetente_id = $1 OR m.destinatario_id = $1
             ORDER BY m.id DESC LIMIT $2
           ) t ORDER BY id""",
        usuario_id, limite_privadas,
    )
    return geral, privadas


async def contar_nao_lidas(usuario_id):
    rows = await pool.fetch(
        """SELECT u.apelido, COUNT(*) FROM mensagens m JOIN usuarios u ON u.id = m.remetente_id
           WHERE m.destinatario_id = $1 AND NOT m.lida GROUP BY u.apelido""",
        usuario_id,
    )
    return {r[0]: r[1] for r in rows}


async def marcar_como_lidas(destinatario_id, remetente_id):
    await pool.execute(
        "UPDATE mensagens SET lida = TRUE WHERE destinatario_id = $1 AND remetente_id = $2 AND NOT lida",
        destinatario_id, remetente_id,
    )


async def apagar_conversa_geral():
    await pool.execute("DELETE FROM mensagens WHERE destinatario_id IS NULL")


async def apagar_conversa_privada(a, b):
    await pool.execute(
        """DELETE FROM mensagens
           WHERE (remetente_id = $1 AND destinatario_id = $2) OR (remetente_id = $2 AND destinatario_id = $1)""",
        a, b,
    )


async def apagar_mensagens_de(usuario_id):
    await pool.execute("DELETE FROM mensagens WHERE remetente_id = $1", usuario_id)


async def apagar_tudo():
    await pool.execute("DELETE FROM mensagens")
