"""Calendario escolar, lado de la familia: solo los eventos que tocan a sus hijos (todo el colegio, su nivel o
su sección según la matrícula de ese año) y los días sin clases. Con el módulo apagado, 403."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app import calendario
from app.db import get_db
from app.deps import SesionFamilia, modulo_encendido
from app.fechas import hoy_lima
from app.models import Alumno, AlumnoApoderado, EventoCalendario
from app.routers.familia_cuaderno import familia_activa

privado = APIRouter(prefix="/familia/calendario", tags=["familia"],
                    dependencies=[Depends(modulo_encendido("calendario"))])


def _hijos(db: Session, s: SesionFamilia) -> list[Alumno]:
    return list(db.scalars(select(Alumno).join(AlumnoApoderado, and_(AlumnoApoderado.colegio_id == Alumno.colegio_id,
                                                                     AlumnoApoderado.alumno_id == Alumno.id))
                           .where(Alumno.colegio_id == s.colegio.id, AlumnoApoderado.apoderado_id == s.apoderado.id,
                                  Alumno.activo).order_by(Alumno.nombres)))


def _de_sus_hijos(db: Session, s: SesionFamilia, eventos: list[EventoCalendario]) -> list[dict]:
    """Los eventos que tocan a alguno de sus hijos, con a cuáles (por su primer nombre)."""
    cid = s.colegio.id
    hijos = _hijos(db, s)
    donde = calendario.ubicacion(db, cid, [a.id for a in hijos])
    dest = calendario.destinos(db, cid, eventos)
    niveles, secciones = calendario.nombres_destinos(db, cid)
    r = []
    for e in eventos:
        suyos = [a.nombres.split()[0] for a in hijos if calendario.le_toca(e, dest[e.id], a.id, donde)]
        if suyos:
            r.append(calendario.evento_dict(e, dest[e.id], calendario.para_quien(e, dest[e.id], niveles, secciones),
                                            completo=False) | {"hijos": suyos})
    return r


@privado.get("/mes")
def mes(mes: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"), s: SesionFamilia = Depends(familia_activa),
        db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    desde = calendario.primer_dia_mes(mes)
    hasta = calendario.ultimo_dia_mes(desde)
    return {"mes": desde.strftime("%Y-%m"), "hoy": hoy_lima().isoformat(),
            "eventos": _de_sus_hijos(db, s, calendario.eventos_entre(db, cid, desde, hasta)),
            "sin_clases": calendario.sin_clases(db, cid, desde, hasta)}


@privado.get("/proximos")
def proximos(s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)) -> dict:
    """Los próximos 90 días: eventos sin anular de sus hijos y días sin clases."""
    cid, hoy = s.colegio.id, hoy_lima()
    hasta = hoy + timedelta(days=90)
    eventos = [e for e in calendario.eventos_entre(db, cid, hoy, hasta) if e.anulado_en is None]
    return {"hoy": hoy.isoformat(), "eventos": _de_sus_hijos(db, s, eventos),
            "sin_clases": calendario.sin_clases(db, cid, hoy, hasta)}
