"""Archivos (logos, fotos, adjuntos) fuera de la base.

Por ahora solo hay almacenamiento en disco local. El público (logos) se sirve en
/archivos; el privado (adjuntos del cuaderno) no se sirve directo: lo entrega una
ruta que revisa la sesión. El de S3 (con un bucket privado) se agrega cuando se
elija proveedor; la interfaz es la misma.
"""

from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import get_settings


class Almacenamiento(Protocol):
    def guardar(self, clave: str, contenido: bytes, tipo_mime: str) -> None: ...

    def borrar(self, clave: str) -> None: ...

    def leer(self, clave: str) -> bytes | None: ...

    def url(self, clave: str) -> str: ...


class AlmacenamientoLocal:
    def __init__(self, carpeta: Path, url_base: str = "/archivos"):
        self.carpeta = carpeta
        self.url_base = url_base

    def guardar(self, clave: str, contenido: bytes, tipo_mime: str) -> None:
        ruta = self.carpeta / clave
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(contenido)

    def borrar(self, clave: str) -> None:
        (self.carpeta / clave).unlink(missing_ok=True)

    def leer(self, clave: str) -> bytes | None:
        ruta = self.carpeta / clave
        return ruta.read_bytes() if ruta.is_file() else None

    def url(self, clave: str) -> str:
        return f"{self.url_base}/{clave}"


@lru_cache
def get_almacenamiento() -> Almacenamiento:
    return AlmacenamientoLocal(Path(get_settings().carpeta_archivos))


@lru_cache
def get_almacenamiento_privado() -> Almacenamiento:
    return AlmacenamientoLocal(Path(get_settings().carpeta_privada), url_base="")
