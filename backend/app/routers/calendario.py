"""Calendario escolar, lado del colegio (permiso `calendario`): eventos por año escolar, a quién van,
anularlos con motivo, la vista de mes (con los días sin clases de Estructura) y el PDF del mes."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session

from app import calendario, pdf
from app.comun import obtener
from app.configuracion import anotar
from app.db import get_db
from app.deps import Sesion, requerir_permiso
from app.fechas import hoy_lima
from app.models import AnioEscolar, DestinoEvento, EventoCalendario, Grado, Nivel, Seccion
from app.models.calendario import TIPOS_EVENTO
from app.routers.importacion import imagen_pdf

router = APIRouter(prefix="/calendario", tags=["calendario"])
ver = requerir_permiso("calendario")
editar = requerir_permiso("calendario", "editar")


class EventoIn(BaseModel):
    titulo: str = Field(max_length=120)
    descripcion: str | None = Field(None, max_length=1000)
    inicio: date
    fin: date | None = None  # vacío: un solo día
    hora: time | None = None
    tipo: Literal[TIPOS_EVENTO]  # type: ignore[valid-type]
    alcance: Literal["colegio", "niveles", "secciones"] = "colegio"
    niveles: list[int] = Field(default_factory=list, max_length=50)
    secciones: list[int] = Field(default_factory=list, max_length=300)
    avisar: bool = False

    @field_validator("titulo")
    @classmethod
    def _titulo(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Escribe el título")
        return v

    @field_validator("descripcion")
    @classmethod
    def _descripcion(cls, v: str | None) -> str | None:
        v = (v or "").strip()  # conserva los saltos de línea
        return v or None

    @model_validator(mode="after")
    def _reglas(self):
        self.fin = self.fin or self.inicio
        if self.fin < self.inicio:
            raise ValueError("La fecha de fin no puede ser antes del inicio")
        if (self.fin - self.inicio).days > 366:
            raise ValueError("Un evento puede durar hasta un año")
        if self.alcance == "niveles" and not self.niveles:
            raise ValueError("Elige al menos un nivel")
        if self.alcance == "secciones" and not self.secciones:
            raise ValueError("Elige al menos una sección")
        if self.alcance != "niveles":
            self.niveles = []
        if self.alcance != "secciones":
            self.secciones = []
        self.niveles, self.secciones = sorted(set(self.niveles)), sorted(set(self.secciones))
        return self


class AnularIn(BaseModel):
    motivo: str = Field(max_length=200)

    @field_validator("motivo")
    @classmethod
    def _motivo(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Escribe el motivo")
        return v


def _anio_activo(db: Session, cid: int) -> AnioEscolar:
    anio = db.scalar(select(AnioEscolar).where(AnioEscolar.colegio_id == cid, AnioEscolar.activo))
    if anio is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Primero crea y activa el año escolar en Estructura")
    return anio


def _revisar_destinos(db: Session, cid: int, anio_id: int, datos: EventoIn) -> None:
    """Los niveles deben ser de este colegio; las secciones, de este colegio y del año del evento."""
    if datos.niveles:
        hay = set(db.scalars(select(Nivel.id).where(Nivel.colegio_id == cid, Nivel.id.in_(datos.niveles))))
        if hay != set(datos.niveles):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Algún nivel no existe")
    if datos.secciones:
        hay = set(db.scalars(select(Seccion.id).where(Seccion.colegio_id == cid, Seccion.anio_id == anio_id,
                                                      Seccion.id.in_(datos.secciones))))
        if hay != set(datos.secciones):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Alguna sección no existe en el año escolar")


def _guardar_destinos(db: Session, e: EventoCalendario, datos: EventoIn) -> None:
    db.execute(delete(DestinoEvento).where(DestinoEvento.colegio_id == e.colegio_id,
                                           DestinoEvento.evento_id == e.id))
    db.add_all([DestinoEvento(colegio_id=e.colegio_id, evento_id=e.id, nivel_id=n) for n in datos.niveles]
               + [DestinoEvento(colegio_id=e.colegio_id, evento_id=e.id, seccion_id=s) for s in datos.secciones])


def _respuesta(db: Session, cid: int, eventos: list[EventoCalendario]) -> list[dict]:
    dest = calendario.destinos(db, cid, eventos)
    niveles, secciones = calendario.nombres_destinos(db, cid)
    return [calendario.evento_dict(e, dest[e.id], calendario.para_quien(e, dest[e.id], niveles, secciones))
            for e in eventos]


def _resumen(e: EventoCalendario) -> str:
    return f"{calendario.NOMBRE_TIPO[e.tipo]} «{e.titulo}» {calendario.fecha_texto(e.inicio, e.fin)}"


# --- Lectura -----------------------------------------------------------------------------------------

@router.get("/opciones")
def opciones(s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    """Tipos, niveles y secciones del año activo para elegir a quién va un evento."""
    cid = s.colegio.id
    anio = db.scalar(select(AnioEscolar).where(AnioEscolar.colegio_id == cid, AnioEscolar.activo))
    niveles = [{"id": i, "nombre": n} for i, n in db.execute(
        select(Nivel.id, Nivel.nombre).where(Nivel.colegio_id == cid).order_by(Nivel.orden, Nivel.nombre))]
    secciones = []
    if anio:
        secciones = [{"id": i, "nombre": f"{g} {sn}", "nivel_id": nid} for i, g, sn, nid in db.execute(
            select(Seccion.id, Grado.nombre, Seccion.nombre, Grado.nivel_id)
            .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
            .join(Nivel, and_(Nivel.colegio_id == Grado.colegio_id, Nivel.id == Grado.nivel_id))
            .where(Seccion.colegio_id == cid, Seccion.anio_id == anio.id)
            .order_by(Nivel.orden, Grado.orden, Seccion.nombre))]
    return {"anio": anio.anio if anio else None, "hoy": hoy_lima().isoformat(),
            "tipos": [{"id": t, "nombre": calendario.NOMBRE_TIPO[t]} for t in TIPOS_EVENTO],
            "niveles": niveles, "secciones": secciones}


@router.get("/mes")
def mes(mes: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"), s: Sesion = Depends(ver),
        db: Session = Depends(get_db)) -> dict:
    """Eventos que tocan el mes (también los anulados) y los días sin clases."""
    cid = s.colegio.id
    desde = calendario.primer_dia_mes(mes)
    hasta = calendario.ultimo_dia_mes(desde)
    return {"mes": desde.strftime("%Y-%m"), "hoy": hoy_lima().isoformat(),
            "eventos": _respuesta(db, cid, calendario.eventos_entre(db, cid, desde, hasta)),
            "sin_clases": calendario.sin_clases(db, cid, desde, hasta)}


@router.get("/proximos")
def proximos(limite: int = Query(30, ge=1, le=100), s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    """Los siguientes eventos sin anular y los días sin clases de los próximos 90 días."""
    cid, hoy = s.colegio.id, hoy_lima()
    return {"hoy": hoy.isoformat(), "eventos": _respuesta(db, cid, calendario.proximos(db, cid, hoy, limite)),
            "sin_clases": calendario.sin_clases(db, cid, hoy, hoy + timedelta(days=90))}


@router.get("/mes.pdf")
def mes_pdf(mes: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"), s: Sesion = Depends(ver),
            db: Session = Depends(get_db)) -> Response:
    """C6: el mes en una hoja A4 apaisada (para imprimir o mandar por WhatsApp). Sin los anulados."""
    cid = s.colegio.id
    desde = calendario.primer_dia_mes(mes)
    hasta = calendario.ultimo_dia_mes(desde)
    eventos = [e for e in calendario.eventos_entre(db, cid, desde, hasta) if e.anulado_en is None]
    dest = calendario.destinos(db, cid, eventos)
    niveles, secciones = calendario.nombres_destinos(db, cid)
    contenido = pdf.calendario_mes(imagen_pdf(s.colegio), desde, [
        pdf.EventoMes(inicio=e.inicio, fin=e.fin, hora=e.hora.strftime("%H:%M") if e.hora else None,
                      titulo=e.titulo, tipo=calendario.NOMBRE_TIPO[e.tipo],
                      para=calendario.para_quien(e, dest[e.id], niveles, secciones))
        for e in eventos], [(date.fromisoformat(d["fecha"]), d["motivo"])
                            for d in calendario.sin_clases(db, cid, desde, hasta)])
    return Response(contenido, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="calendario-{desde:%Y-%m}.pdf"'})


# --- Cambios -------------------------------------------------------------------------------------------

@router.post("/eventos", status_code=201)
def crear(datos: EventoIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    anio = _anio_activo(db, cid)
    _revisar_destinos(db, cid, anio.id, datos)
    e = EventoCalendario(colegio_id=cid, anio_id=anio.id, titulo=datos.titulo, descripcion=datos.descripcion,
                         inicio=datos.inicio, fin=datos.fin, hora=datos.hora, tipo=datos.tipo,
                         alcance=datos.alcance, avisar=datos.avisar, creado_por_id=s.usuario.id)
    db.add(e)
    db.flush()
    _guardar_destinos(db, e, datos)
    db.flush()
    avisados = calendario.al_guardar(db, e, s.colegio)
    extra = f" · aviso a {avisados} familia{'s' if avisados != 1 else ''}" if e.avisar else ""
    anotar(db, s, "crear", "calendario", "evento", e, _resumen(e) + extra)
    return _respuesta(db, cid, [e])[0] | {"avisos": avisados}


@router.put("/eventos/{evento_id}")
def editar_evento(evento_id: int, datos: EventoIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    e = obtener(db, EventoCalendario, cid, evento_id, "Evento")
    if e.anulado_en is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "El evento está anulado")
    _revisar_destinos(db, cid, e.anio_id, datos)
    if datos.inicio != e.inicio:
        e.recordatorio_en = None  # otra fecha: el recordatorio vuelve a tocar (si aún falta)
    for campo in ("titulo", "descripcion", "inicio", "fin", "hora", "tipo", "alcance", "avisar"):
        setattr(e, campo, getattr(datos, campo))
    _guardar_destinos(db, e, datos)
    db.flush()
    avisados = calendario.al_guardar(db, e, s.colegio)
    extra = f" · aviso a {avisados} familia{'s' if avisados != 1 else ''}" if avisados else ""
    anotar(db, s, "editar", "calendario", "evento", e, _resumen(e) + extra)
    return _respuesta(db, cid, [e])[0] | {"avisos": avisados}


@router.post("/eventos/{evento_id}/anular")
def anular(evento_id: int, datos: AnularIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    e = obtener(db, EventoCalendario, cid, evento_id, "Evento")
    if e.anulado_en is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "El evento ya está anulado")
    e.anulado_en, e.anulado_motivo, e.anulado_por_id = datetime.now(UTC), datos.motivo, s.usuario.id
    calendario.quitar_pendientes(db, e, "evento anulado")
    anotar(db, s, "anular", "calendario", "evento", e, f"Anuló {_resumen(e)}: {datos.motivo}")
    return _respuesta(db, cid, [e])[0]
