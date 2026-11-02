"""Claves y tokens.

Hay dos tipos de token que no se pueden intercambiar:
- "colegio": personal de un colegio; lleva `col` (colegio_id).
- "plataforma": personal de Tikray Labs; solo sirve en /plataforma.

Cada tipo se firma con una llave distinta derivada de SECRET_KEY y lleva su
propia audiencia, así que un token de un tipo nunca valida como el otro.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from pwdlib import PasswordHash

from app.config import get_settings

TipoToken = Literal["colegio", "plataforma"]
ALGORITMO = "HS256"

_hasher = PasswordHash.recommended()


def hashear_clave(clave: str) -> str:
    return _hasher.hash(clave)


def verificar_clave(clave: str, clave_hash: str) -> bool:
    return _hasher.verify(clave, clave_hash)


# Hash de referencia para gastar el mismo tiempo cuando el usuario no existe.
_HASH_FALSO = _hasher.hash(secrets.token_urlsafe(16))


def verificar_clave_o_simular(clave: str, clave_hash: str | None) -> bool:
    if clave_hash is None:
        _hasher.verify(clave, _HASH_FALSO)
        return False
    return verificar_clave(clave, clave_hash)


def _llave(tipo: TipoToken) -> bytes:
    secreto = get_settings().secret_key.encode()
    return hmac.new(secreto, f"token-{tipo}".encode(), hashlib.sha256).digest()


def emitir_token(tipo: TipoToken, sub: int, version_sesion: int, minutos: int, **extra) -> str:
    ahora = datetime.now(UTC)
    datos = {
        "sub": str(sub),
        "aud": tipo,
        "ver": version_sesion,
        "iat": ahora,
        "exp": ahora + timedelta(minutes=minutos),
        **extra,
    }
    return jwt.encode(datos, _llave(tipo), algorithm=ALGORITMO)


def leer_token(tipo: TipoToken, token: str) -> dict | None:
    try:
        return jwt.decode(
            token, _llave(tipo), algorithms=[ALGORITMO], audience=tipo,
            options={"require": ["sub", "aud", "exp", "ver"]},
        )
    except jwt.PyJWTError:
        return None
