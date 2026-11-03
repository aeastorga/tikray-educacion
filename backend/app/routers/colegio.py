import secrets

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.almacenamiento import get_almacenamiento
from app.db import get_db
from app.deps import Sesion, colegio_del_host, requerir_permiso
from app.models import Colegio

publico = APIRouter(prefix="/publico", tags=["colegio"])
privado = APIRouter(prefix="/colegio", tags=["colegio"])

COLOR = r"^#[0-9a-fA-F]{6}$"
LOGO_MAX_BYTES = 200 * 1024
EXTENSIONES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


class Imagen(BaseModel):
    nombre: str
    logo_url: str | None
    color_primario: str
    color_secundario: str
    menu_claro: bool


class CambioImagen(BaseModel):
    color_primario: str = Field(pattern=COLOR)
    color_secundario: str = Field(pattern=COLOR)
    menu_claro: bool | None = None  # sin enviar: queda como está


def _imagen(c: Colegio) -> Imagen:
    return Imagen(
        nombre=c.nombre,
        logo_url=get_almacenamiento().url(c.logo_clave) if c.logo_clave else None,
        color_primario=c.color_primario, color_secundario=c.color_secundario, menu_claro=c.menu_claro,
    )


def tipo_real(contenido: bytes) -> str | None:
    """Tipo según la firma del archivo, no según lo que diga el navegador. Nunca SVG."""
    if contenido.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contenido.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(contenido) >= 12 and contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "image/webp"
    return None


@publico.get("/colegio")
def imagen_publica(colegio: Colegio = Depends(colegio_del_host)) -> Imagen:
    """Lo que necesita la pantalla de ingreso antes de iniciar sesión."""
    return _imagen(colegio)


@privado.put("/imagen")
def cambiar_imagen(
    datos: CambioImagen,
    s: Sesion = Depends(requerir_permiso("configuracion", "editar")),
    db: Session = Depends(get_db),
) -> Imagen:
    s.colegio.color_primario = datos.color_primario.upper()
    s.colegio.color_secundario = datos.color_secundario.upper()
    if datos.menu_claro is not None:
        s.colegio.menu_claro = datos.menu_claro
    db.commit()
    return _imagen(s.colegio)


@privado.put("/logo")
def subir_logo(
    archivo: UploadFile = File(...),
    s: Sesion = Depends(requerir_permiso("configuracion", "editar")),
    db: Session = Depends(get_db),
) -> Imagen:
    # Se lee como mucho el máximo + 1 byte: basta para saber si se pasa.
    contenido = archivo.file.read(LOGO_MAX_BYTES + 1)
    if not contenido:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El archivo está vacío")
    if len(contenido) > LOGO_MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "El logo pesa más de 200 KB")
    mime = tipo_real(contenido)
    if mime is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Solo se aceptan imágenes PNG, JPG o WEBP")

    almacen = get_almacenamiento()
    anterior = s.colegio.logo_clave
    # Nombre nuevo en cada subida: así ninguna caché sirve el logo viejo.
    clave = f"colegios/{s.colegio.id}/logo-{secrets.token_urlsafe(12)}.{EXTENSIONES[mime]}"
    almacen.guardar(clave, contenido, mime)
    s.colegio.logo_clave = clave
    db.commit()
    if anterior:
        almacen.borrar(anterior)
    return _imagen(s.colegio)


@privado.delete("/logo")
def quitar_logo(
    s: Sesion = Depends(requerir_permiso("configuracion", "editar")), db: Session = Depends(get_db),
) -> Imagen:
    anterior = s.colegio.logo_clave
    if anterior is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El colegio no tiene logo")
    s.colegio.logo_clave = None
    db.commit()
    get_almacenamiento().borrar(anterior)
    return _imagen(s.colegio)
