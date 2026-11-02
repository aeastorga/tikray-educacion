"""Reglas de clave y límite de intentos fallidos (traído de sgi-platform).

El límite vive en memoria: vale para una sola instancia y se reinicia con el
servidor. Si se escala a varias instancias, pasa a la base o a Redis.
"""

import secrets
import string
import threading
import time
import unicodedata
from collections import deque

from fastapi import HTTPException

MIN_CARACTERES = 8

_REGLAS = [
    ("Al menos 8 caracteres", lambda pw: len(pw) >= MIN_CARACTERES),
    ("Una mayúscula", lambda pw: any(unicodedata.category(c) == "Lu" for c in pw)),
    ("Una minúscula", lambda pw: any(unicodedata.category(c) == "Ll" for c in pw)),
    ("Un número", lambda pw: any(unicodedata.category(c) == "Nd" for c in pw)),
    ("Sin espacios al inicio ni al final", lambda pw: pw == pw.strip()),
]


def motivos_clave(pw: str) -> list[str]:
    """Reglas que `pw` no cumple (lista vacía = válida)."""
    return [texto for texto, cumple in _REGLAS if not cumple(pw or "")]


def exigir_clave_valida(pw: str, campo: str = "clave_nueva") -> None:
    motivos = motivos_clave(pw)
    if motivos:
        raise HTTPException(422, {"campo": campo, "mensaje": "La clave no cumple los requisitos",
                                  "motivos": motivos})


def generar_clave_temporal(largo: int = 10) -> str:
    # Sin caracteres que se confunden al dictarla (0/O, 1/l/I).
    alfabeto = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    while True:
        pw = "".join(secrets.choice(alfabeto) for _ in range(largo))
        if not motivos_clave(pw):
            return pw


class LimitadorVentana:
    """Máximo de fallos por clave dentro de una ventana deslizante."""

    def __init__(self, maximo: int, segundos: int):
        self.maximo = maximo
        self.segundos = segundos
        self._marcas: dict[str, deque] = {}
        self._lock = threading.Lock()

    def _vigentes(self, clave: str, ahora: float) -> deque:
        marcas = self._marcas.setdefault(clave, deque())
        while marcas and ahora - marcas[0] >= self.segundos:
            marcas.popleft()
        return marcas

    def hay_cupo(self, clave: str) -> bool:
        with self._lock:
            return len(self._vigentes(clave, time.monotonic())) < self.maximo

    def registrar(self, clave: str) -> None:
        ahora = time.monotonic()
        with self._lock:
            self._vigentes(clave, ahora).append(ahora)
            # Limpieza ocasional para que el diccionario no crezca sin fin.
            if len(self._marcas) > 10000:
                for k in [k for k, v in self._marcas.items() if not v or ahora - v[-1] >= self.segundos]:
                    del self._marcas[k]

    def limpiar(self) -> None:
        with self._lock:
            self._marcas.clear()


# 5 fallos cada 15 minutos. Bloqueado o con clave errónea, la respuesta es la misma.
FALLOS_INGRESO = LimitadorVentana(maximo=5, segundos=15 * 60)
FALLOS_PLATAFORMA = LimitadorVentana(maximo=5, segundos=15 * 60)
