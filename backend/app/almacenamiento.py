"""Archivos (logos, fotos, adjuntos) fuera de la base.

Por ahora solo hay almacenamiento en disco local, servido en /archivos.
El de S3 se agrega cuando se elija proveedor; la interfaz es la misma.
"""

from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import get_settings


class Almacenamiento(Protocol):
    def guardar(self, clave: str, contenido: bytes, tipo_mime: str) -> None: ...

    def borrar(self, clave: str) -> None: ...

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

    def url(self, clave: str) -> str:
        return f"{self.url_base}/{clave}"


@lru_cache
def get_almacenamiento() -> Almacenamiento:
    return AlmacenamientoLocal(Path(get_settings().carpeta_archivos))
