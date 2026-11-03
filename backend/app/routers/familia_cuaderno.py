"""Cuaderno de control, lado de la familia: lo que le llegó, firmar, responder,
justificar faltas y pedir permisos de salida.

Todo dentro del colegio por cuya dirección entró (`SesionFamilia.apoderado`) y solo
con el acceso activo: un padre pendiente de aprobación aún no ve el cuaderno.
"""

from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app import cuaderno
from app.comun import guardar
from app.db import get_db
from app.deps import SesionFamilia, familia_sesion, modulo_encendido
from app.fechas import hoy_lima
from app.models import (AdjuntoCuaderno, Alumno, AlumnoApoderado, DestinoCuaderno, EntradaCuaderno, MensajeCuaderno,
                        Usuario)
from app.routers.cuaderno import EntradaIn, crear_entrada

privado = APIRouter(prefix="/familia/cuaderno", tags=["familia"],
                  dependencies=[Depends(modulo_encendido("cuaderno"))])

# Lo que puede pedir el padre: hasta este tiempo atrás (justificación) o adelante.
DIAS_ATRAS = 60
DIAS_ADELANTE = 60


def familia_activa(s: SesionFamilia = Depends(familia_sesion)) -> SesionFamilia:
    if s.apoderado.estado_acceso != "activo":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu cuenta espera la aprobación del colegio")
    return s


def _mia(db: Session, s: SesionFamilia, entrada_id: int) -> EntradaCuaderno:
    """Solo las entradas que le llegaron a este apoderado; cualquier otra da 404."""
    e = db.scalar(select(EntradaCuaderno).where(
        EntradaCuaderno.colegio_id == s.colegio.id, EntradaCuaderno.id == entrada_id, cuaderno.publicada(),
        EntradaCuaderno.id.in_(select(DestinoCuaderno.entrada_id).where(
            DestinoCuaderno.colegio_id == s.colegio.id, DestinoCuaderno.apoderado_id == s.apoderado.id))))
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontrado")
    return e


def _hijos(db: Session, s: SesionFamilia) -> dict[int, str]:
    return {i: n for i, n in db.execute(
        select(Alumno.id, Alumno.nombres)
        .join(AlumnoApoderado, and_(AlumnoApoderado.colegio_id == Alumno.colegio_id,
                                    AlumnoApoderado.alumno_id == Alumno.id))
        .where(Alumno.colegio_id == s.colegio.id, AlumnoApoderado.apoderado_id == s.apoderado.id, Alumno.activo))}


@privado.get("")
def listar(s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)) -> dict:
    cid, apo = s.colegio.id, s.apoderado.id
    filas = db.execute(
        select(EntradaCuaderno, func.array_agg(DestinoCuaderno.alumno_id), func.max(DestinoCuaderno.visto_en),
               func.max(DestinoCuaderno.firmado_en))
        .join(DestinoCuaderno, and_(DestinoCuaderno.colegio_id == EntradaCuaderno.colegio_id,
                                    DestinoCuaderno.entrada_id == EntradaCuaderno.id))
        .where(EntradaCuaderno.colegio_id == cid, DestinoCuaderno.apoderado_id == apo, cuaderno.publicada())
        .group_by(EntradaCuaderno.id).order_by(EntradaCuaderno.id.desc()).limit(100)).all()
    ids = [e.id for e, *_ in filas]
    respuestas = dict(db.execute(select(MensajeCuaderno.entrada_id, func.count())
                                 .where(MensajeCuaderno.colegio_id == cid, MensajeCuaderno.entrada_id.in_(ids))
                                 .group_by(MensajeCuaderno.entrada_id)).all()) if ids else {}
    adjuntos = cuaderno.adjuntos_de(db, cid, ids)
    hijos = _hijos(db, s)
    categorias = cuaderno.categorias_de(db, cid)
    nombres = dict(db.execute(select(Alumno.id, Alumno.nombres).where(
        Alumno.colegio_id == cid, Alumno.id.in_({a for _, al, _, _ in filas for a in al}))).all()) if filas else {}
    return {
        "hijos": [{"id": i, "nombres": n} for i, n in sorted(hijos.items(), key=lambda x: x[1])],
        "entradas": [{
            **cuaderno.entrada_basica(e, categorias), "alumnos": sorted({nombres.get(a, "") for a in al}),
            "visto": visto is not None, "firmado_en": cuaderno.iso(firmado),
            "respuestas": respuestas.get(e.id, 0), "adjuntos": len(adjuntos.get(e.id, [])),
        } for e, al, visto, firmado in filas],
    }


@privado.get("/{entrada_id}")
def detalle(entrada_id: int, s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)) -> dict:
    """Abrirla la marca como vista."""
    cid = s.colegio.id
    e = _mia(db, s, entrada_id)
    mis = db.scalars(select(DestinoCuaderno).where(DestinoCuaderno.colegio_id == cid,
                                                   DestinoCuaderno.entrada_id == e.id,
                                                   DestinoCuaderno.apoderado_id == s.apoderado.id)).all()
    ahora = datetime.now(UTC)
    for d in mis:
        d.visto_en = d.visto_en or ahora
    db.commit()
    personal = dict(db.execute(select(Usuario.id, Usuario.nombres + " " + Usuario.apellidos)
                               .where(Usuario.colegio_id == cid)).all())
    mensajes = db.scalars(select(MensajeCuaderno).where(MensajeCuaderno.colegio_id == cid,
                                                        MensajeCuaderno.entrada_id == e.id)
                          .order_by(MensajeCuaderno.id)).all()
    nombres = db.scalars(select(Alumno.nombres + " " + Alumno.apellidos)
                         .where(Alumno.colegio_id == cid, Alumno.id.in_({d.alumno_id for d in mis}))).all()
    return {
        **cuaderno.entrada_basica(e, cuaderno.categorias_de(db, cid)), "alumnos": sorted(nombres),
        "firmado_en": cuaderno.iso(max((d.firmado_en for d in mis if d.firmado_en), default=None)),
        "autor": personal.get(e.creado_por_id) if e.creado_por_id else None,
        "adjuntos": cuaderno.adjuntos_de(db, cid, [e.id]).get(e.id, []),
        "mensajes": [{"id": m.id, "cuerpo": m.cuerpo, "creado_en": cuaderno.iso(m.creado_en),
                      "de_familia": m.de_familia, "mio": m.apoderado_id == s.apoderado.id,
                      "autor": ("Tú" if m.apoderado_id == s.apoderado.id else "Familia") if m.de_familia
                      else personal.get(m.usuario_id, "Colegio")} for m in mensajes],
    }


@privado.post("/{entrada_id}/firmar")
def firmar(entrada_id: int, s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)) -> dict:
    e = _mia(db, s, entrada_id)
    if not cuaderno.requiere_firma(e):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esta entrada no pide firma")
    momento = cuaderno.firmar(db, e, s.apoderado.id)
    db.commit()
    return {"firmado_en": momento.isoformat()}


class RespuestaIn(BaseModel):
    cuerpo: str = Field(min_length=1, max_length=4000)


@privado.post("/{entrada_id}/respuestas", status_code=201)
def responder(entrada_id: int, d: RespuestaIn, s: SesionFamilia = Depends(familia_activa),
              db: Session = Depends(get_db)) -> dict:
    e = _mia(db, s, entrada_id)
    m = MensajeCuaderno(colegio_id=s.colegio.id, entrada_id=e.id, apoderado_id=s.apoderado.id, de_familia=True,
                        cuerpo=d.cuerpo.strip())
    db.add(m)
    guardar(db)
    return {"id": m.id}


@privado.get("/adjuntos/{adjunto_id}")
def adjunto(adjunto_id: int, s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)):
    adj = db.scalar(select(AdjuntoCuaderno).where(AdjuntoCuaderno.colegio_id == s.colegio.id,
                                                  AdjuntoCuaderno.id == adjunto_id))
    if adj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Archivo no encontrado")
    _mia(db, s, adj.entrada_id)
    return cuaderno.respuesta_adjunto(adj)


# --- Lo que pide el padre ------------------------------------------------------------------

def _crear_del_padre(db: Session, s: SesionFamilia, d: EntradaIn) -> tuple[EntradaCuaderno, list[int]]:
    cid = s.colegio.id
    if d.alumno_id not in _hijos(db, s):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alumno no encontrado")
    hoy = hoy_lima()
    if (d.desde - hoy).days > DIAS_ADELANTE or (hoy - d.desde).days > DIAS_ATRAS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "La fecha está fuera de lo permitido")
    if d.tipo == "permiso_salida" and d.desde < hoy:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El permiso de salida es para hoy o un día próximo")
    destino = cuaderno.Destino("alumno", alumno_id=d.alumno_id,
                               seccion_id=cuaderno.seccion_de(db, cid, d.alumno_id))
    e = crear_entrada(db, cid, d, destino, apoderado_id=s.apoderado.id)
    apoderados = cuaderno.guardar_destinos(db, e, [d.alumno_id])
    cuaderno.firmar(db, e, s.apoderado.id)  # quien la escribió ya la vio
    # El otro apoderado del alumno se entera; quien la envió, no.
    cuaderno.avisar(db, e, [a for a in apoderados if a != s.apoderado.id], cuaderno.texto_aviso(db, e))
    return e, apoderados


class JustificacionIn(BaseModel):
    alumno_id: int
    desde: date
    hasta: date | None = None
    motivo: str = Field(min_length=1, max_length=200)
    detalle: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def _fechas(self):
        self.hasta = self.hasta or self.desde
        if self.hasta < self.desde:
            raise ValueError("La fecha final es anterior a la inicial")
        if (self.hasta - self.desde).days > 31:
            raise ValueError("Justifica como máximo un mes a la vez")
        return self


@privado.post("/justificaciones", status_code=201)
async def justificar(datos: str = Form(...), archivos: list[UploadFile] | None = File(None),
                     s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)) -> dict:
    """Formulario con `datos` (JSON) y hasta 5 `archivos` (certificado médico, constancia)."""
    try:
        j = JustificacionIn.model_validate_json(datos)
    except ValidationError as err:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            str(err.errors()[0]["msg"]).removeprefix("Value error, ")) from None
    adjuntos = await cuaderno.leer_adjuntos(archivos)
    d = EntradaIn(tipo="justificacion", alumno_id=j.alumno_id, titulo=j.motivo, cuerpo=j.detalle,
                  desde=j.desde, hasta=j.hasta)
    e, _ = _crear_del_padre(db, s, d)
    claves = cuaderno.guardar_adjuntos(db, e, adjuntos)
    try:
        guardar(db)
    except Exception:
        cuaderno.borrar_archivos(claves)
        raise
    return {"id": e.id, "estado": e.estado}


class PermisoIn(BaseModel):
    alumno_id: int
    fecha: date
    hora: time
    recoge: str = Field(min_length=1, max_length=120)
    motivo: str = Field(min_length=1, max_length=200)


@privado.post("/permisos-salida", status_code=201)
def pedir_permiso(p: PermisoIn, s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)) -> dict:
    d = EntradaIn(tipo="permiso_salida", alumno_id=p.alumno_id, titulo=p.motivo, desde=p.fecha, hora_salida=p.hora,
                  recoge=p.recoge)
    e, _ = _crear_del_padre(db, s, d)
    guardar(db)
    return {"id": e.id, "estado": e.estado}
