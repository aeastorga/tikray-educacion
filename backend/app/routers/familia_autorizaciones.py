"""Autorizaciones, lado de la familia: las que van a sus hijos (pendientes arriba) y responder "Autorizo" o
"No autorizo" por cada hijo, con un comentario opcional. Con el módulo apagado, 403.

- A2/A3: cada respuesta es una fila nueva con fecha, hora y quién respondió; vale la última.
- A4: después de la fecha límite (o si el colegio la cerró o anuló) ya no se responde.
- A6: responde solo el apoderado que recibe los avisos de ese hijo (y con la cuenta activa).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app import autorizaciones as reglas
from app.configuracion import registrar
from app.db import get_db
from app.deps import SesionFamilia, modulo_encendido
from app.fechas import hoy_lima
from app.models import Alumno, AlumnoApoderado, AlumnoAutorizacion, Autorizacion, RespuestaAutorizacion
from app.routers.autorizaciones import respuesta_adjunto
from app.routers.familia_cuaderno import familia_activa

privado = APIRouter(prefix="/familia/autorizaciones", tags=["familia"],
                    dependencies=[Depends(modulo_encendido("autorizaciones"))])


class RespuestaIn(BaseModel):
    alumno_id: int
    autoriza: bool
    comentario: str | None = Field(None, max_length=300)

    @field_validator("comentario")
    @classmethod
    def _comentario(cls, v: str | None) -> str | None:
        v = " ".join((v or "").split())
        return v or None


def _hijos(db: Session, s: SesionFamilia) -> dict[int, tuple[Alumno, bool]]:
    """{alumno_id: (alumno, recibe_avisos)} de sus hijos activos."""
    return {a.id: (a, recibe) for a, recibe in db.execute(
        select(Alumno, AlumnoApoderado.recibe_avisos)
        .join(AlumnoApoderado, and_(AlumnoApoderado.colegio_id == Alumno.colegio_id,
                                    AlumnoApoderado.alumno_id == Alumno.id))
        .where(Alumno.colegio_id == s.colegio.id, AlumnoApoderado.apoderado_id == s.apoderado.id, Alumno.activo)
        .order_by(Alumno.nombres))}


def _de_sus_hijos(db: Session, s: SesionFamilia, hijos: dict, autorizacion_id: int | None = None) -> dict:
    """{autorizacion: [alumno_id, ...]} de las publicadas (o cerradas o anuladas) que van a sus hijos."""
    q = (select(Autorizacion, AlumnoAutorizacion.alumno_id)
         .join(AlumnoAutorizacion, and_(AlumnoAutorizacion.colegio_id == Autorizacion.colegio_id,
                                        AlumnoAutorizacion.autorizacion_id == Autorizacion.id))
         .where(Autorizacion.colegio_id == s.colegio.id, Autorizacion.publicada_en.is_not(None),
                AlumnoAutorizacion.alumno_id.in_(list(hijos) or [-1])))
    if autorizacion_id is not None:
        q = q.where(Autorizacion.id == autorizacion_id)
    r: dict[Autorizacion, list[int]] = {}
    for a, alumno_id in db.execute(q):
        r.setdefault(a, []).append(alumno_id)
    return r


def _mia(db: Session, s: SesionFamilia, autorizacion_id: int) -> tuple[Autorizacion, list[int], dict]:
    """Solo las que van a sus hijos; cualquier otra da 404."""
    hijos = _hijos(db, s)
    r = _de_sus_hijos(db, s, hijos, autorizacion_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Autorización no encontrada")
    [(a, alumnos)] = r.items()
    return a, alumnos, hijos


def _dict(a: Autorizacion, alumnos: list[int], hijos: dict, vig: dict, hoy, apoderado_id: int) -> dict:
    abierta = reglas.abierta(a, hoy)
    filas = []
    for al in sorted(alumnos, key=lambda i: hijos[i][0].nombres):
        alumno, recibe = hijos[al]
        r = vig.get((a.id, al))
        filas.append({"alumno_id": al, "nombre": alumno.nombres.split()[0],
                      "respuesta": reglas.respuesta_dict(r) | {"mia": r.apoderado_id == apoderado_id} if r else None,
                      "puede_responder": abierta and recibe})
    return {"id": a.id, "titulo": a.titulo, "descripcion": a.descripcion,
            "fecha_actividad": a.fecha_actividad.isoformat() if a.fecha_actividad else None,
            "fecha_limite": a.fecha_limite.isoformat(), "estado": reglas.estado(a, hoy),
            "anulado_motivo": a.anulado_motivo,
            "adjunto": {"nombre": a.adjunto_nombre, "tipo": a.adjunto_tipo} if a.adjunto_clave else None,
            "hijos": filas, "pendiente": any(f["puede_responder"] and f["respuesta"] is None for f in filas)}


@privado.get("")
def lista(s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)) -> list[dict]:
    """Las pendientes arriba (por fecha límite), luego las abiertas y al final las cerradas y anuladas."""
    hoy = hoy_lima()
    hijos = _hijos(db, s)
    de_hijos = _de_sus_hijos(db, s, hijos)
    vig = reglas.vigentes(db, s.colegio.id, [a.id for a in de_hijos])
    salida = [_dict(a, alumnos, hijos, vig, hoy, s.apoderado.id) for a, alumnos in de_hijos.items()]
    orden = {"publicada": 0, "cerrada": 1, "anulada": 1}
    salida.sort(key=lambda d: (not d["pendiente"], orden[d["estado"]],
                               d["fecha_limite"] if d["estado"] == "publicada" else "",
                               -d["id"]))
    return salida


@privado.post("/{autorizacion_id}/respuestas")
def responder(autorizacion_id: int, datos: RespuestaIn, s: SesionFamilia = Depends(familia_activa),
              db: Session = Depends(get_db)) -> dict:
    hoy = hoy_lima()
    a, alumnos, hijos = _mia(db, s, autorizacion_id)
    if datos.alumno_id not in alumnos:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esta autorización no es para ese alumno")
    if not reglas.abierta(a, hoy):
        motivo = {"cerrada": "Ya pasó la fecha límite o el colegio la cerró", "anulada": "El colegio la anuló"}
        raise HTTPException(status.HTTP_409_CONFLICT, motivo.get(reglas.estado(a, hoy), "No se puede responder"))
    if not hijos[datos.alumno_id][1] or not reglas.puede_responder(db, s.colegio.id, s.apoderado.id, datos.alumno_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Responde el apoderado que recibe los avisos de este alumno")
    ap = s.apoderado
    nombre = f"{ap.nombres} {ap.apellidos}".strip()
    r = RespuestaAutorizacion(colegio_id=s.colegio.id, autorizacion_id=a.id, alumno_id=datos.alumno_id,
                              apoderado_id=ap.id, apoderado_nombre=nombre[:160],
                              apoderado_documento=ap.numero_documento, autoriza=datos.autoriza,
                              comentario=datos.comentario)
    db.add(r)
    db.flush()
    alumno = hijos[datos.alumno_id][0]
    registrar(db, s.colegio.id, f"{nombre} (apoderado)", "crear", "autorizaciones", "respuesta", r.id,
              f"{'Autorizó' if datos.autoriza else 'No autorizó'} «{a.titulo}» por {alumno.nombres} {alumno.apellidos}")
    db.commit()
    vig = reglas.vigentes(db, s.colegio.id, [a.id])
    return _dict(a, alumnos, hijos, vig, hoy, ap.id)


@privado.get("/{autorizacion_id}/adjunto")
def adjunto(autorizacion_id: int, s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)):
    a, _, _ = _mia(db, s, autorizacion_id)
    return respuesta_adjunto(a)
