"""Panel del director: cómo va el colegio hoy, en una sola pantalla.

Cada bloque sale solo si la persona tiene permiso de ver ese módulo (el director los ve
todos). El cuaderno respeta "solo sus secciones".
"""

from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app import cuaderno
from app.db import get_db
from app.deps import Sesion, puede, usuario_actual
from app.fechas import LIMA, hoy_lima
from app.models import (Alumno, AnioEscolar, Apoderado, AsistenciaAlumno, AsistenciaPersonal, ColaAviso,
                        DestinoCuaderno, EntradaCuaderno, EntregaAviso, Grado, LicenciaPersonal, Marcacion, Matricula,
                        MensajeCuaderno, Seccion, SuscripcionPush, Turno, Usuario)
from app.routers.estructura import es_dia_lectivo

router = APIRouter(prefix="/panel", tags=["panel"])

DIAS_TENDENCIA = 10
TRAMO_MINUTOS = 10  # llegadas por hora, en tramos de 10 minutos
LISTA_CORTA = 5


def ahora_lima() -> datetime:
    """Reloj del panel (aparte para poder fijarlo en las pruebas)."""
    return datetime.now(UTC).astimezone(LIMA)


def _tramo(momento: datetime) -> str:
    local = momento.astimezone(LIMA)
    return f"{local.hour:02d}:{local.minute // TRAMO_MINUTOS * TRAMO_MINUTOS:02d}"


def _llegadas(db: Session, cid: int, hoy, matriculados) -> dict:
    """Ingresos de hoy en tramos de 10 minutos (hora de Lima), separados en a tiempo y tarde según el
    estado que calculó la portería con el turno de cada alumno. `limite` es la hora de tolerancia del turno
    con más ingresos (para la referencia del gráfico)."""
    filas = db.execute(
        select(AsistenciaAlumno.entrada, AsistenciaAlumno.estado, Turno.hora_entrada, Turno.tolerancia_minutos)
        .join(matriculados, matriculados.c.alumno_id == AsistenciaAlumno.alumno_id)
        .outerjoin(Seccion, and_(Seccion.colegio_id == AsistenciaAlumno.colegio_id,
                                 Seccion.id == matriculados.c.seccion_id))
        .outerjoin(Turno, and_(Turno.colegio_id == Seccion.colegio_id, Turno.id == Seccion.turno_id))
        .where(AsistenciaAlumno.colegio_id == cid, AsistenciaAlumno.fecha == hoy,
               AsistenciaAlumno.entrada.is_not(None), AsistenciaAlumno.estado.in_(("presente", "tarde")))).all()
    tramos: dict[str, dict] = {}
    turnos: Counter = Counter()
    for entrada, estado, hora_entrada, tolerancia in filas:
        t = tramos.setdefault(_tramo(entrada), {"a_tiempo": 0, "tarde": 0})
        t["tarde" if estado == "tarde" else "a_tiempo"] += 1
        if hora_entrada is not None:
            turnos[(hora_entrada, tolerancia)] += 1
    limite = None
    if turnos:
        (hora_entrada, tolerancia), _ = turnos.most_common(1)[0]
        fin = datetime.combine(hoy, hora_entrada) + timedelta(minutes=tolerancia)
        limite = fin.strftime("%H:%M")
    # Tramos seguidos (también los vacíos) entre la primera y la última llegada.
    lista = []
    if tramos:
        claves = sorted(tramos)
        actual = datetime.strptime(claves[0], "%H:%M")
        ultimo = datetime.strptime(claves[-1], "%H:%M")
        while actual <= ultimo:
            k = actual.strftime("%H:%M")
            lista.append({"inicio": k, **tramos.get(k, {"a_tiempo": 0, "tarde": 0})})
            actual += timedelta(minutes=TRAMO_MINUTOS)
    return {"tramo_minutos": TRAMO_MINUTOS, "tramos": lista, "limite": limite}


def _ultima_marcacion(db: Session, cid: int, hoy, matriculados) -> dict | None:
    m = db.scalar(select(Marcacion).where(Marcacion.colegio_id == cid, Marcacion.fecha == hoy,
                                          Marcacion.alumno_id.in_(select(matriculados.c.alumno_id)))
                  .order_by(Marcacion.momento.desc(), Marcacion.id.desc()).limit(1))
    if m is None:
        return None
    return {"hora": m.momento.astimezone(LIMA).strftime("%H:%M"), "equipo": m.equipo, "origen": m.origen}


def _personal(db: Session, cid: int, hoy) -> dict:
    estados = dict(db.execute(select(AsistenciaPersonal.estado, func.count())
                              .where(AsistenciaPersonal.colegio_id == cid, AsistenciaPersonal.fecha == hoy)
                              .group_by(AsistenciaPersonal.estado)).all())
    # Quien tiene turno es quien debe marcar.
    con_turno = (Usuario.colegio_id == cid, Usuario.activo, Usuario.turno_id.is_not(None))
    total = db.scalar(select(func.count()).select_from(Usuario).where(*con_turno)) or 0
    nombre = lambda u: f"{u.nombres} {u.apellidos}"  # noqa: E731
    tarde = db.execute(select(Usuario, AsistenciaPersonal.minutos_tarde)
                       .join(AsistenciaPersonal, and_(AsistenciaPersonal.colegio_id == Usuario.colegio_id,
                                                      AsistenciaPersonal.usuario_id == Usuario.id))
                       .where(Usuario.colegio_id == cid, AsistenciaPersonal.fecha == hoy,
                              AsistenciaPersonal.estado == "tarde")
                       .order_by(AsistenciaPersonal.minutos_tarde.desc()).limit(LISTA_CORTA)).all()
    licencias = db.execute(select(Usuario, LicenciaPersonal.tipo)
                           .join(LicenciaPersonal, and_(LicenciaPersonal.colegio_id == Usuario.colegio_id,
                                                        LicenciaPersonal.usuario_id == Usuario.id))
                           .where(Usuario.colegio_id == cid, LicenciaPersonal.desde <= hoy,
                                  LicenciaPersonal.hasta >= hoy)
                           .order_by(Usuario.apellidos).limit(LISTA_CORTA)).all()
    con_licencia_q = (select(LicenciaPersonal.usuario_id)
                      .where(LicenciaPersonal.colegio_id == cid, LicenciaPersonal.desde <= hoy,
                             LicenciaPersonal.hasta >= hoy))
    con_licencia = db.scalar(select(func.count(Usuario.id)).where(
        Usuario.colegio_id == cid, Usuario.activo, Usuario.id.in_(con_licencia_q))) or 0
    # Sin marcar: ya pasó la hora de entrada de su turno (hora de Lima), no tiene ingreso hoy (aunque ya le
    # haya caído la falta automática) y no está de licencia. Antes de su hora todavía no se le espera.
    marcaron = (select(AsistenciaPersonal.usuario_id)
                .where(AsistenciaPersonal.colegio_id == cid, AsistenciaPersonal.fecha == hoy,
                       AsistenciaPersonal.entrada.is_not(None)))
    ya_entraron = select(Turno.id).where(Turno.colegio_id == cid, Turno.hora_entrada < ahora_lima().time())
    sin_marcar_q = select(Usuario).where(*con_turno, Usuario.turno_id.in_(ya_entraron), Usuario.id.not_in(marcaron),
                                         Usuario.id.not_in(con_licencia_q))
    sin_marcar_total = db.scalar(select(func.count()).select_from(sin_marcar_q.subquery())) or 0
    sin_marcar = db.scalars(sin_marcar_q.order_by(Usuario.apellidos).limit(LISTA_CORTA)).all()
    return {
        **{k: estados.get(k, 0) for k in ("presente", "tarde", "falta", "licencia")},
        "total": total, "sin_marcar": sin_marcar_total, "con_licencia": con_licencia,
        "lista": {
            "licencias": [{"nombre": nombre(u), "tipo": t} for u, t in licencias],
            "tardanzas": [{"nombre": nombre(u), "minutos": m} for u, m in tarde],
            "sin_marcar": [{"nombre": nombre(u)} for u in sin_marcar],
        },
    }


def _asistencia(db: Session, cid: int, permitidas: set[int] | None) -> dict:
    """Asistencia de hoy. Con `permitidas` (rol con "solo sus secciones"), solo de esas secciones."""
    hoy = hoy_lima()
    anio = db.scalar(select(AnioEscolar.id).where(AnioEscolar.colegio_id == cid, AnioEscolar.activo))
    q = (select(Matricula.alumno_id, Matricula.seccion_id)
         .join(Alumno, and_(Alumno.colegio_id == Matricula.colegio_id, Alumno.id == Matricula.alumno_id))
         .where(Matricula.colegio_id == cid, Matricula.anio_id == anio, Alumno.activo))
    if permitidas is not None:
        q = q.where(Matricula.seccion_id.in_(permitidas))
    matriculados = q.subquery()
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
            .where(AsistenciaAlumno.colegio_id == cid, AsistenciaAlumno.fecha.between(desde, hoy),
                   AsistenciaAlumno.alumno_id.in_(select(matriculados.c.alumno_id)))
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

    return {
        "lectivo": es_dia_lectivo(db, cid, hoy), "alumnos": total, "hoy": hoy_d,
        # Sin ningún registro todavía (antes del ingreso) no hay porcentaje: no es 0 %.
        "porcentaje": (round(100 * (hoy_d["presente"] + hoy_d["tarde"]) / total)
                       if total and hoy_d["sin_registro"] < total else None),
        "solo_sus_secciones": permitidas is not None,
        "secciones_con_faltas": [{"id": i, "nombre": f"{g} {s}", "faltas": n} for i, g, s, n in peores],
        "tendencia": list(reversed(tendencia)),
        "llegadas": _llegadas(db, cid, hoy, matriculados),
        "ultima_marcacion": _ultima_marcacion(db, cid, hoy, matriculados),
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
        EntradaCuaderno.colegio_id == cid, EntradaCuaderno.tipo.in_(("comunicado", "citacion")), cuaderno.publicada(),
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
    salidas = db.execute(visibles(
        select(EntradaCuaderno, Alumno.nombres, Alumno.apellidos)
        .join(Alumno, and_(Alumno.colegio_id == EntradaCuaderno.colegio_id, Alumno.id == EntradaCuaderno.alumno_id))
        .where(EntradaCuaderno.colegio_id == cid, EntradaCuaderno.tipo == "permiso_salida",
               EntradaCuaderno.desde == hoy_lima(), EntradaCuaderno.estado.in_(("pendiente", "aprobada"))))
        .order_by(EntradaCuaderno.hora_salida)).all()
    return {
        "por_aprobar": dict(por_aprobar), "sin_responder": sin_responder,
        "permisos_salida_hoy": [{"id": e.id, "alumno": f"{n} {a}", "hora": e.hora_salida.strftime("%H:%M"),
                                 "estado": e.estado} for e, n, a in salidas],
        "firmas": [{"id": e.id, "tipo": e.tipo, "titulo": e.titulo, "creado_en": cuaderno.iso(e.creado_en),
                    "apoderados": firmas.get(e.id, (0, 0))[0], "firmados": firmas.get(e.id, (0, 0))[1]}
                   for e in con_firma],
    }


def _familias(db: Session, cid: int) -> dict:
    hoy = hoy_lima()
    estados = dict(db.execute(select(Apoderado.estado_acceso, func.count()).where(Apoderado.colegio_id == cid)
                              .group_by(Apoderado.estado_acceso)).all())
    # Reciben avisos: tienen un celular suscrito o hoy ya les llegó alguno (lo segundo cubre la demo, que
    # simula entregas sin crear suscripciones).
    con_push = db.scalar(select(func.count()).select_from(Apoderado).where(
        Apoderado.colegio_id == cid, Apoderado.estado_acceso == "activo",
        or_(Apoderado.cuenta_id.in_(select(SuscripcionPush.cuenta_id)),
            Apoderado.id.in_(select(EntregaAviso.apoderado_id)
                             .join(ColaAviso, and_(ColaAviso.colegio_id == EntregaAviso.colegio_id,
                                                   ColaAviso.id == EntregaAviso.aviso_id))
                             .where(EntregaAviso.colegio_id == cid, EntregaAviso.estado == "enviado",
                                    ColaAviso.fecha == hoy))))) or 0
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
    if puede(s, "asistencia", "ver"):
        salida["asistencia"] = _asistencia(db, cid, cuaderno.secciones_permitidas(db, u))
    if puede(s, "personal", "ver"):  # nombres, licencias y quién no marcó: solo con este permiso
        salida["personal"] = _personal(db, cid, hoy_lima())
    if puede(s, "cuaderno", "ver"):
        salida["cuaderno"] = _cuaderno(db, s)
    if puede(s, "familias", "ver"):
        salida["familias"] = _familias(db, cid)
    if u.rol.es_director:
        salida["personal_activo"] = db.scalar(select(func.count()).select_from(Usuario).where(
            Usuario.colegio_id == cid, Usuario.activo))
    return salida


@router.get("/menu")
def menu(s: Sesion = Depends(usuario_actual), db: Session = Depends(get_db)) -> dict:
    """Lo que muestra el menú lateral: año escolar y contadores de pendientes, según los permisos."""
    cid, u = s.colegio.id, s.usuario
    anio = db.scalar(select(AnioEscolar.anio).where(AnioEscolar.colegio_id == cid, AnioEscolar.activo))
    salida: dict = {"anio": anio}
    if puede(s, "cuaderno", "ver"):
        permitidas = cuaderno.secciones_permitidas(db, u)
        q = select(func.count()).select_from(EntradaCuaderno).where(EntradaCuaderno.colegio_id == cid,
                                                                    EntradaCuaderno.estado == "pendiente")
        if permitidas is not None:
            q = q.where(EntradaCuaderno.seccion_id.in_(permitidas))
        salida["cuaderno_pendientes"] = db.scalar(q) or 0
    if puede(s, "familias", "ver"):
        salida["padres_por_aprobar"] = db.scalar(select(func.count()).select_from(Apoderado).where(
            Apoderado.colegio_id == cid, Apoderado.estado_acceso == "pendiente")) or 0
    return salida
