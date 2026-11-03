"""Reglas de clave y límite de intentos fallidos (traído de sgi-platform).

El límite se guarda en la base (`intento_fallido`): vale con varias instancias
del servidor y no se pierde al reiniciar. Usa el reloj de la base, el mismo para todos.
"""

import ipaddress
import secrets
import string
import threading
import unicodedata
from functools import lru_cache

from fastapi import HTTPException, Request
from sqlalchemy import text

from app.config import get_settings

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
    """Máximo de fallos por clave dentro de una ventana deslizante, guardado en la base.

    Usa su propia conexión: un fallo queda registrado aunque la petición haga rollback."""

    # Cada cuántos registros se borran los fallos viejos (más de un día).
    LIMPIAR_CADA = 200

    def __init__(self, ambito: str, maximo: int, segundos: int):
        self.ambito = ambito
        self.maximo = maximo
        self.segundos = segundos
        self._cuenta = 0
        self._lock = threading.Lock()

    def fallos(self, clave: str) -> int:
        from app.db import get_engine

        with get_engine().connect() as conn:
            return conn.execute(text(
                "SELECT count(*) FROM intento_fallido WHERE ambito = :a AND clave = :c "
                "AND momento > now() - make_interval(secs => :s)"),
                {"a": self.ambito, "c": clave[:300], "s": self.segundos}).scalar_one()

    def hay_cupo(self, clave: str) -> bool:
        return self.fallos(clave) < self.maximo

    def registrar(self, clave: str) -> None:
        from app.db import get_engine

        with self._lock:
            self._cuenta += 1
            limpiar = self._cuenta % self.LIMPIAR_CADA == 0
        with get_engine().begin() as conn:
            conn.execute(text("INSERT INTO intento_fallido (ambito, clave, momento) VALUES (:a, :c, now())"),
                         {"a": self.ambito, "c": clave[:300]})
            if limpiar:
                conn.execute(text("DELETE FROM intento_fallido WHERE momento < now() - interval '1 day'"))

    def limpiar(self) -> None:
        from app.db import get_engine

        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM intento_fallido WHERE ambito = :a"), {"a": self.ambito})


# Bloqueado o con clave errónea, la respuesta es la misma.
# Por cuenta: 5 fallos cada 15 minutos.
FALLOS_CUENTA = LimitadorVentana("cuenta", maximo=5, segundos=15 * 60)
# Por IP, mucho más alto: todo el personal de un colegio sale por la misma IP
# (el wifi del colegio) y el primer día con claves temporales se equivocan muchos.
FALLOS_IP = LimitadorVentana("ip", maximo=50, segundos=15 * 60)


@lru_cache
def _redes_confianza() -> tuple:
    return tuple(ipaddress.ip_network(r.strip(), strict=False)
                 for r in get_settings().proxies_confianza.split(",") if r.strip())


def _es_de_confianza(ip: str) -> bool:
    try:
        direccion = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(direccion in red for red in _redes_confianza())


def ip_cliente(request: Request) -> str:
    """IP real de quien hace la petición.

    X-Forwarded-For solo se lee si la conexión viene de un proxy de confianza
    (PROXIES_CONFIANZA); si no, cualquiera podría inventarse una IP. Se recorre
    de derecha a izquierda saltando los proxies propios: la primera IP que no
    es de confianza es la del cliente (las de más a la izquierda las puede
    escribir el propio cliente).
    """
    directa = request.client.host if request.client else "?"
    if not _es_de_confianza(directa):
        return directa
    cadena = [ip.strip() for ip in request.headers.get("x-forwarded-for", "").split(",") if ip.strip()]
    for ip in reversed(cadena):
        if not _es_de_confianza(ip):
            return ip
    return cadena[0] if cadena else directa


def permitir_intento(cuenta: str, ip: str) -> bool:
    return FALLOS_CUENTA.hay_cupo(cuenta) and FALLOS_IP.hay_cupo(ip)


def registrar_fallo(cuenta: str, ip: str) -> None:
    FALLOS_CUENTA.registrar(cuenta)
    FALLOS_IP.registrar(ip)


def limpiar_limites() -> None:
    FALLOS_CUENTA.limpiar()
    FALLOS_IP.limpiar()
