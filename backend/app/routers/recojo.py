"""Recojo seguro, lado del colegio: la lista de autorizados de cada alumno (secretaría, permiso `recojo`) y
el registro de quién recogió al alumno desde la portería (permiso de marcar asistencia)."""

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import recojo, validacion
from app.almacenamiento import get_almacenamiento_privado
from app.comun import obtener
from app.configuracion import anotar
from app.db import get_db
from app.deps import Sesion, puede, requerir_permiso, usuario_actual
from app.fechas import hoy_lima
from app.models import Alumno, AlumnoApoderado, Apoderado, AutorizacionRecojoDia, AutorizadoRecojo

log = logging.getLogger(__name__)
router = APIRouter(prefix="/recojo", tags=["recojo"])
ver = requerir_permiso("recojo")
editar = requerir_permiso("recojo", "editar")
marcar = requerir_permiso("asistencia", "editar")


def porteria(s: Sesion = Depends(marcar)) -> Sesion:
    """La portería registra quién lo recogió con su permiso de marcar, si el colegio usa recojo seguro."""
    if not s.colegio.modulo_activo("recojo"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Este módulo no está activo en el colegio")
    return s


class PersonaIn(BaseModel):
    nombres: str
    apellidos: str
    tipo_documento: str = "DNI"
    numero_documento: str
    parentesco: str = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def _normalizar(self):
        self.tipo_documento = validacion.tipo_documento(self.tipo_documento)
        self.numero_documento = validacion.documento(self.tipo_documento, self.numero_documento)
        self.nombres = validacion.nombre(self.nombres)
        self.apellidos = validacion.nombre(self.apellidos)
        self.parentesco = " ".join(self.parentesco.split())
        if not self.parentesco:
            raise ValueError("Indica el parentesco")
        return self


class AutorizadoIn(PersonaIn):
    celular: str | None = None
    activo: bool = True

    _celular = field_validator("celular")(classmethod(lambda cls, v: validacion.celular(v)))

    def campos(self) -> dict:
        return self.model_dump(exclude={"activo"})


def nombre(x) -> str:
    return f"{x.apellidos}, {x.nombres}"


# --- Ficha del alumno ------------------------------------------------------------------------

@router.get("/alumnos/{alumno_id}")
def ficha(alumno_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    a = obtener(db, Alumno, cid, alumno_id, "Alumno")
    hoy = hoy_lima()
    apoderados = db.execute(
        select(Apoderado, AlumnoApoderado.parentesco)
        .join(AlumnoApoderado, (AlumnoApoderado.colegio_id == Apoderado.colegio_id)
              & (AlumnoApoderado.apoderado_id == Apoderado.id))
        .where(Apoderado.colegio_id == cid, AlumnoApoderado.alumno_id == a.id).order_by(Apoderado.apellidos))
    autorizados = db.scalars(select(AutorizadoRecojo).where(
        AutorizadoRecojo.colegio_id == cid, AutorizadoRecojo.alumno_id == a.id)
        .order_by(AutorizadoRecojo.activo.desc(), AutorizadoRecojo.apellidos))
    del_dia = db.scalars(select(AutorizacionRecojoDia).where(
        AutorizacionRecojoDia.colegio_id == cid, AutorizacionRecojoDia.alumno_id == a.id,
        AutorizacionRecojoDia.fecha >= hoy, AutorizacionRecojoDia.anulada_en.is_(None))
        .order_by(AutorizacionRecojoDia.fecha))
    return {
        "alumno_id": a.id, "max_autorizados": recojo.MAX_AUTORIZADOS,
        "apoderados": [{"id": ap.id, "nombres": ap.nombres, "apellidos": ap.apellidos, "parentesco": p,
                        "tipo_documento": ap.tipo_documento, "numero_documento": ap.numero_documento}
                       for ap, p in apoderados],
        "autorizados": [recojo.autorizado_dict(x) for x in autorizados],
        "del_dia": [recojo.del_dia_dict(x) for x in del_dia],
    }


@router.post("/alumnos/{alumno_id}/autorizados", status_code=201)
def crear(alumno_id: int, datos: AutorizadoIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    a = obtener(db, Alumno, s.colegio.id, alumno_id, "Alumno")
    x = recojo.crear_autorizado(db, s.colegio.id, a.id, datos.campos(), usuario_id=s.usuario.id)
    anotar(db, s, "crear", "recojo", "autorizado", x,
           f"Autorizó a {nombre(x)} ({x.parentesco}) a recoger a {nombre(a)}")
    return recojo.autorizado_dict(x)


@router.put("/autorizados/{autorizado_id}")
def editar_autorizado(autorizado_id: int, datos: AutorizadoIn, s: Sesion = Depends(editar),
                      db: Session = Depends(get_db)) -> dict:
    x = obtener(db, AutorizadoRecojo, s.colegio.id, autorizado_id, "Autorizado")
    que = recojo.editar_autorizado(db, x, datos.campos(), datos.activo)
    a = db.get(Alumno, x.alumno_id)
    anotar(db, s, "editar", "recojo", "autorizado", x, f"{que} a {nombre(x)} en la lista de recojo de {nombre(a)}")
    return recojo.autorizado_dict(x)


@router.put("/autorizados/{autorizado_id}/foto")
async def subir_foto(autorizado_id: int, archivo: UploadFile | None = File(None), s: Sesion = Depends(editar),
                     db: Session = Depends(get_db)) -> dict:
    x = obtener(db, AutorizadoRecojo, s.colegio.id, autorizado_id, "Autorizado")
    tipo, contenido = await recojo.leer_foto(archivo)
    anterior = recojo.guardar_foto(x, tipo, contenido)
    try:
        anotar(db, s, "editar", "recojo", "autorizado", x, f"Foto de {nombre(x)} (lista de recojo)")
    except Exception:
        get_almacenamiento_privado().borrar(x.foto_clave)
        raise
    if anterior:
        get_almacenamiento_privado().borrar(anterior)
    return recojo.autorizado_dict(x)


def ve_fotos(s: Sesion = Depends(usuario_actual)) -> Sesion:
    """La foto la ve quien lleva la lista (recojo › ver) y la portería (asistencia › editar)."""
    if not s.colegio.modulo_activo("recojo"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Este módulo no está activo en el colegio")
    if not (puede(s, "recojo") or puede(s, "asistencia", "editar")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso para este módulo")
    return s


def foto_respuesta(x: AutorizadoRecojo) -> Response:
    contenido = get_almacenamiento_privado().leer(x.foto_clave) if x.foto_clave else None
    if contenido is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sin foto")
    return Response(contenido, media_type=x.foto_tipo, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/autorizados/{autorizado_id}/foto")
def foto(autorizado_id: int, s: Sesion = Depends(ve_fotos), db: Session = Depends(get_db)) -> Response:
    return foto_respuesta(obtener(db, AutorizadoRecojo, s.colegio.id, autorizado_id, "Autorizado"))


# --- Portería: quién lo recogió --------------------------------------------------------------------

class RecojoIn(BaseModel):
    # La marcación de salida a la que corresponde (su id_cliente). Un reenvío o una corrección la reemplaza.
    marcacion: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    tipo: Literal["apoderado", "autorizado", "del_dia", "otro"]
    persona_id: int | None = None
    # Solo para "otro" (alguien fuera de la lista).
    nombres: str | None = None
    apellidos: str | None = None
    tipo_documento: str | None = "DNI"
    numero_documento: str | None = None

    @model_validator(mode="after")
    def _segun_tipo(self):
        if self.tipo in ("apoderado", "autorizado", "del_dia") and self.persona_id is None:
            raise ValueError("Indica a la persona de la lista")
        if self.tipo == "otro":
            self.tipo_documento = validacion.tipo_documento(self.tipo_documento)
            self.numero_documento = validacion.documento(self.tipo_documento, self.numero_documento or "")
            self.nombres = validacion.nombre(self.nombres or "")
            self.apellidos = validacion.nombre(self.apellidos or "")
        return self


class LoteRecojoIn(BaseModel):
    recojos: list[RecojoIn] = Field(min_length=1, max_length=500)


@router.post("/registros")
def registrar(datos: LoteRecojoIn, s: Sesion = Depends(porteria), db: Session = Depends(get_db)) -> dict:
    """Cada uno se confirma por separado, como las marcaciones: un lote que llega de una portería sin internet
    no se pierde entero por uno malo. "esperando": la salida aún no llegó; la portería lo reintenta."""
    resultados = []
    ahora = datetime.now(UTC)
    for r in datos.recojos:
        try:
            resultado = recojo.registrar(db, s.colegio.id, recojo.DatosRecojo(**r.model_dump()), s.usuario.id,
                                         quien=s.usuario, ahora=ahora)
            db.commit()
        except Exception:
            db.rollback()
            log.exception("Recojo de la marcación %s", r.marcacion)
            resultado = {"marcacion": r.marcacion, "estado": "error", "mensaje": "No se pudo guardar; se reintentará"}
        resultados.append(resultado)
    return {"resultados": resultados}
