"""Panel del director: cómo va el colegio hoy, en una sola pantalla.

Cada bloque sale solo si la persona tiene permiso de ver ese módulo (el director los ve
todos). El cuaderno respeta "solo sus secciones".
"""

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app import cuaderno
from app.db import get_db
from app.deps import Sesion, tiene_permiso, usuario_actual
from app.fechas import hoy_lima
from app.models import (Alumno, AnioEscolar, Apoderado, AsistenciaAlumno, AsistenciaPersonal, ColaAviso,
                        DestinoCuaderno, EntradaCuaderno, EntregaAviso, Grado, Matricula, MensajeCuaderno, Seccion,
                        SuscripcionPush, Usuario)
from app.routers.estructura import es_dia_lectivo

router = APIRouter(prefix="/panel", tags=["panel"])

DIAS_TENDENCIA = 10


def _asistencia(db: Session, cid: int) -> dict:
    hoy = hoy_lima()
    anio = db.scalar(select(AnioEscolar.id).where(AnioEscolar.colegio_id == cid, AnioEscolar.activo))
    matriculados = (select(Matricula.alumno_id, Matricula.seccion_id)
                    .join(Alumno, and_(Alumno.colegio_id == Matricula.colegio_id, Alumno.id == Matricula.alumno_id))
                    .where(Matricula.colegio_id == cid, Matricula.anio_id == anio, Alumno.activo).subquery())
    total = db.scalar(select(func.count()).select_from(matriculados)) or 0
    estados = dict(db.execute(
        select(AsistenciaAlumno.estado, func.count())
        .join(matriculados, matriculados.c.alumno_id == AsistenciaAlumno.alumno_id)
        .where(AsistenciaAlumno.colegio_id == cid, AsistenciaAlumno.fecha == hoy)
        .group_by(AsistenciaAlumno.estado)).all())
    hoy_d = {k: estados.get(k, 0) for k in ("presente", "tarde", "falta", "justificada")}
    hoy_d["sin_registro"] = max(total - sum(hoy_d.values()), 0)

    # Secciones con más faltas hoy (sin justificar).
    peores = db.execute(
        select(Seccion.id, Grado.nombre, Seccion.nombre, func.count())
        .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
        .join(matriculados, matriculados.c.seccion_id == Seccion.id)
        .join(AsistenciaAlumno, and_(AsistenciaAlumno.colegio_id == Seccion.colegio_id,
                                     AsistenciaAlumno.alumno_id == matriculados.c.alumno_id,
                                     AsistenciaAlumno.fecha == hoy, AsistenciaAlumno.estado == "falta"))
        .where(Seccion.colegio_id == cid)
        .group_by(Seccion.id, Grado.nombre, Seccion.nombre).order_by(func.count().desc()).limit(5)).all()

    # Últimos días de clase: % que vino (presente o tarde) sobre los registrados.
    desde = hoy - timedelta(days=DIAS_TENDENCIA * 2 + 7)
    por_dia: dict = {}
    for fecha, vino, registrados in db.execute(
            select(AsistenciaAlumno.fecha,
                   func.count(case((AsistenciaAlumno.estado.in_(("presente", "tarde")), 1))), func.count())
            .where(AsistenciaAlumno.colegio_id == cid, AsistenciaAlumno.fecha.between(desde, hoy))
            .group_by(AsistenciaAlumno.fecha)):
        por_dia[fecha] = (vino, registrados)
    tendencia = []
    d = hoy
    while d >= desde and len(tendencia) < DIAS_TENDENCIA:
        if es_dia_lectivo(db, cid, d):
            vino, registrados = por_dia.get(d, (0, 0))
            tendencia.append({"fecha": d.isoformat(), "vino": vino, "registrados": registrados,
                              "porcentaje": round(100 * vino / registrados) if registrados else None})
        d -= timedelta(days=1)

    personal = dict(db.execute(select(AsistenciaPersonal.estado, func.count())
                               .where(AsistenciaPersonal.colegio_id == cid, AsistenciaPersonal.fecha == hoy)
                               .group_by(AsistenciaPersonal.estado)).all())
    return {
        "lectivo": es_dia_lectivo(db, cid, hoy), "alumnos": total, "hoy": hoy_d,
        "porcentaje": round(100 * (hoy_d["presente"] + hoy_d["tarde"]) / total) if total else None,
        "secciones_con_faltas": [{"id": i, "nombre": f"{g} {s}", "faltas": n} for i, g, s, n in peores],
        "tendencia": list(reversed(tendencia)),
        "personal": {k: personal.get(k, 0) for k in ("presente", "tarde", "falta", "licencia")},
    }


def _cuaderno(db: Session, s: Sesion) -> dict:
    cid = s.colegio.id
    permitidas = cuaderno.secciones_permitidas(db, s.usuario)

    def visibles(q):
        return q.where(EntradaCuaderno.seccion_id.in_(permitidas)) if permitidas is not None else q

    por_aprobar = db.execute(visibles(
        select(EntradaCuaderno.tipo, func.count()).where(EntradaCuaderno.colegio_id == cid,
                                                         EntradaCuaderno.estado == "pendiente"))
        .group_by(EntradaCuaderno.tipo)).all()
    ultimo = (select(MensajeCuaderno.de_familia).where(MensajeCuaderno.colegio_id == cid,
                                                       MensajeCuaderno.entrada_id == EntradaCuaderno.id)
              .order_by(MensajeCuaderno.id.desc()).limit(1).scalar_subquery())
    sin_responder = db.scalar(visibles(select(func.count()).select_from(EntradaCuaderno).where(
        EntradaCuaderno.colegio_id == cid, ultimo.is_(True)))) or 0
    con_firma = db.scalars(visibles(select(EntradaCuaderno).where(
        EntradaCuaderno.colegio_id == cid, EntradaCuaderno.tipo.in_(("comunicado", "citacion")),
        (EntradaCuaderno.tipo == "citacion") | EntradaCuaderno.pide_firma))
        .order_by(EntradaCuaderno.id.desc()).limit(5)).all()
    firmas = {}
    if con_firma:
        apo = DestinoCuaderno.apoderado_id
        for eid, total, firmados in db.execute(
                select(DestinoCuaderno.entrada_id, func.count(apo.distinct()),
                       func.count(case((DestinoCuaderno.firmado_en.is_not(None), apo)).distinct()))
                .where(DestinoCuaderno.colegio_id == cid, DestinoCuaderno.entrada_id.in_([e.id for e in con_firma]))
                .group_by(DestinoCuaderno.entrada_id)):
            firmas[eid] = (total, firmados)
    return {
        "por_aprobar": dict(por_aprobar), "sin_responder": sin_responder,
        "firmas": [{"id": e.id, "tipo": e.tipo, "titulo": e.titulo, "creado_en": cuaderno.iso(e.creado_en),
                    "apoderados": firmas.get(e.id, (0, 0))[0], "firmados": firmas.get(e.id, (0, 0))[1]}
                   for e in con_firma],
    }


def _familias(db: Session, cid: int) -> dict:
    hoy = hoy_lima()
    estados = dict(db.execute(select(Apoderado.estado_acceso, func.count()).where(Apoderado.colegio_id == cid)
                              .group_by(Apoderado.estado_acceso)).all())
    con_push = db.scalar(select(func.count(Apoderado.id.distinct()))
                         .join(SuscripcionPush, SuscripcionPush.cuenta_id == Apoderado.cuenta_id)
                         .where(Apoderado.colegio_id == cid, Apoderado.estado_acceso == "activo")) or 0
    entregas = dict(db.execute(
        select(EntregaAviso.estado, func.count())
        .join(ColaAviso, and_(ColaAviso.colegio_id == EntregaAviso.colegio_id, ColaAviso.id == EntregaAviso.aviso_id))
        .where(EntregaAviso.colegio_id == cid, ColaAviso.fecha == hoy)
        .group_by(EntregaAviso.estado)).all())
    en_cola = db.scalar(select(func.count()).select_from(ColaAviso).where(
        ColaAviso.colegio_id == cid, ColaAviso.estado == "pendiente")) or 0
    return {
        "apoderados": sum(estados.values()), "activos": estados.get("activo", 0),
        "pendientes": estados.get("pendiente", 0), "sin_cuenta": estados.get("sin_cuenta", 0),
        "bloqueados": estados.get("bloqueado", 0), "con_notificaciones": con_push,
        "avisos_hoy": {k: entregas.get(k, 0) for k in ("enviado", "sin_notificaciones", "error")},
        "avisos_en_cola": en_cola,
    }


@router.get("/resumen")
def resumen(s: Sesion = Depends(usuario_actual), db: Session = Depends(get_db)) -> dict:
    cid, u = s.colegio.id, s.usuario
    salida: dict = {"fecha": hoy_lima().isoformat(), "colegio": s.colegio.nombre}
    if tiene_permiso(u, "asistencia", "ver"):
        salida["asistencia"] = _asistencia(db, cid)
    if tiene_permiso(u, "cuaderno", "ver"):
        salida["cuaderno"] = _cuaderno(db, s)
    if tiene_permiso(u, "familias", "ver"):
        salida["familias"] = _familias(db, cid)
    if u.rol.es_director:
        salida["personal_activo"] = db.scalar(select(func.count()).select_from(Usuario).where(
            Usuario.colegio_id == cid, Usuario.activo))
    return salida
