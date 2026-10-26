"""Envio de Web Push (notificações com o app fechado), sem serviços externos.

Implementa:
- RFC 8291: criptografia do conteúdo (aes128gcm) para a inscrição do navegador;
- RFC 8292: identificação do servidor (VAPID, JWT assinado com ES256).

O navegador (Chrome, Firefox, Safari) entrega o push pelo serviço dele
(Google, Mozilla, Apple). O conteúdo vai criptografado de ponta a ponta:
só o aparelho inscrito consegue ler.
"""
import base64
import json
import os
import time
from urllib.parse import urlparse

import aiohttp
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def b64url(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode()


def de_b64url(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _ponto_publico(chave_publica) -> bytes:
    return chave_publica.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _hkdf(salt, info, tamanho, ikm):
    return HKDF(algorithm=hashes.SHA256(), length=tamanho, salt=salt, info=info).derive(ikm)


# ---------------------------------------------------------------
# Chaves VAPID
# ---------------------------------------------------------------
class Vapid:
    def __init__(self, chave_privada: ec.EllipticCurvePrivateKey, assunto: str):
        self.chave = chave_privada
        self.assunto = assunto
        self.publica_b64 = b64url(_ponto_publico(chave_privada.public_key()))

    @classmethod
    def gerar(cls, assunto):
        return cls(ec.generate_private_key(ec.SECP256R1()), assunto)

    @classmethod
    def de_privada_b64(cls, privada_b64, assunto):
        """Aceita a chave privada no formato base64url de 32 bytes (padrão das ferramentas web-push)."""
        d = int.from_bytes(de_b64url(privada_b64), "big")
        return cls(ec.derive_private_key(d, ec.SECP256R1()), assunto)

    def privada_b64(self):
        return b64url(self.chave.private_numbers().private_value.to_bytes(32, "big"))

    def cabecalho_autorizacao(self, endpoint):
        u = urlparse(endpoint)
        cabecalho = {"typ": "JWT", "alg": "ES256"}
        dados = {"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": self.assunto}
        parte = b64url(json.dumps(cabecalho, separators=(",", ":")).encode()) + "." + \
            b64url(json.dumps(dados, separators=(",", ":")).encode())
        r, s = decode_dss_signature(self.chave.sign(parte.encode(), ec.ECDSA(hashes.SHA256())))
        assinatura = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return f"vapid t={parte}.{b64url(assinatura)}, k={self.publica_b64}"


# ---------------------------------------------------------------
# Criptografia do conteúdo (RFC 8291, aes128gcm)
# ---------------------------------------------------------------
def criptografar(conteudo: bytes, p256dh_b64: str, auth_b64: str) -> bytes:
    ua_publica_bytes = de_b64url(p256dh_b64)
    segredo_auth = de_b64url(auth_b64)
    ua_publica = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_publica_bytes)

    efemera = ec.generate_private_key(ec.SECP256R1())
    as_publica = _ponto_publico(efemera.public_key())
    segredo_ecdh = efemera.exchange(ec.ECDH(), ua_publica)

    ikm = _hkdf(segredo_auth, b"WebPush: info\x00" + ua_publica_bytes + as_publica, 32, segredo_ecdh)
    salt = os.urandom(16)
    cek = _hkdf(salt, b"Content-Encoding: aes128gcm\x00", 16, ikm)
    nonce = _hkdf(salt, b"Content-Encoding: nonce\x00", 12, ikm)

    cifrado = AESGCM(cek).encrypt(nonce, conteudo + b"\x02", None)  # \x02 = último registro
    tamanho_registro = 4096
    cabecalho = salt + tamanho_registro.to_bytes(4, "big") + bytes([len(as_publica)]) + as_publica
    return cabecalho + cifrado


# ---------------------------------------------------------------
# Envio
# ---------------------------------------------------------------
class InscricaoExpirada(Exception):
    """O serviço de push disse que a inscrição não existe mais (404/410)."""


async def enviar(sessao: aiohttp.ClientSession, vapid: Vapid, inscricao: dict, dados: dict, ttl=86400):
    """Envia um push. `inscricao` = {"endpoint", "p256dh", "auth"}. Levanta InscricaoExpirada se for o caso."""
    corpo = criptografar(json.dumps(dados).encode(), inscricao["p256dh"], inscricao["auth"])
    cabecalhos = {
        "Authorization": vapid.cabecalho_autorizacao(inscricao["endpoint"]),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
        "Urgency": "high",
    }
    async with sessao.post(inscricao["endpoint"], data=corpo, headers=cabecalhos,
                           timeout=aiohttp.ClientTimeout(total=10)) as resp:
        if resp.status in (404, 410):
            raise InscricaoExpirada()
        if resp.status >= 400:
            raise RuntimeError(f"push recusado: HTTP {resp.status} {(await resp.text())[:200]}")
        return resp.status
