"""El día en curso del colegio demo: marcaciones simuladas hasta la hora actual de Lima.

Solo para colegios `es_demo`. Cada alumno y cada persona del personal tiene su hora de llegada y de
salida del día, sacada al azar pero siempre igual para ese día (semilla = colegio + fecha + persona):
así se puede llamar cuantas veces se quiera (al crear la demo y en cada vuelta del proceso de fondo)
y solo agrega lo que ya "pasó". La mayoría llega a tiempo, algunos tarde y pocos faltan.

Los avisos de esas marcaciones se guardan ya procesados, con el estado que tendrían (entregado a quien
tiene la app con avisos, sin notificaciones a quien no). No se crean suscripciones push: nada intenta
enviarse. Lo que marque alguien de verdad en la portería de la demo pasa por el camino normal y aquí no se
toca (quien ya tiene asistencia hoy se salta).
"""

import random
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import asistencia, avisos
from app.fechas import LIMA
from app.models import (Alumno, AlumnoApoderado, AnioEscolar, Apoderado, AsistenciaAlumno, AsistenciaPersonal,
                        ColaAviso, Colegio, EntregaAviso, LicenciaPersonal, Marcacion, Matricula, Seccion, Turno,
                        Usuario)
from app.routers.estructura import es_dia_lectivo

EQUIPOS = ("Puerta principal", "Puerta principal", "Puerta principal", "Puerta lateral")
FALTAN = 0.035      # alumnos que no vienen
TARDE = 0.08        # alumnos que llegan después de la tolerancia
CON_AVISOS = 0.75   # de los apoderados con cuenta, cuántos tienen los avisos activos en su celular


def _azar(cid: int, fecha: date, quien: str) -> random.Random:
    return random.Random(f"demo-{cid}-{fecha.isoformat()}-{quien}")


def _en(fecha: date, base, minutos: float) -> datetime:
    return datetime.combine(fecha, base, LIMA) + timedelta(seconds=round(minutos * 60))


def plan_alumno(cid: int, fecha: date, alumno_id: int, turno: Turno) -> dict:
    """Qué hace el alumno ese día: falta, o su hora de entrada y de salida (en Lima)."""
    r = _azar(cid, fecha, f"a{alumno_id}")
    x = r.random()
    if x < FALTAN:
        return {"falta": True}
    if x < FALTAN + TARDE:
        entrada = _en(fecha, turno.hora_entrada, turno.tolerancia_minutos + r.uniform(1, 28))
    else:
        entrada = _en(fecha, turno.hora_entrada, -r.triangular(0, 28, 9) + r.uniform(0, turno.tolerancia_minutos * .6))
    return {"falta": False, "equipo": r.choice(EQUIPOS), "entrada": entrada,
            "salida": _en(fecha, turno.hora_salida, r.uniform(0, 22))}


def plan_personal(cid: int, fecha: date, usuario_id: int, turno: Turno) -> dict:
    r = _azar(cid, fecha, f"p{usuario_id}")
    if r.random() < 0.05:
        entrada = _en(fecha, turno.hora_entrada, turno.tolerancia_minutos + r.uniform(1, 15))
    else:
        entrada = _en(fecha, turno.hora_entrada, -r.uniform(5, 35))
    return {"entrada": entrada}


def simular_dia(db: Session, colegio: Colegio, ahora: datetime | None = None) -> int:
    """Agrega lo que ya pasó hoy en el colegio demo (hasta `ahora`). Devuelve cuántos eventos agregó.
    No hace commit."""
    if not colegio.es_demo:
        return 0
    ahora = (ahora or datetime.now(UTC)).astimezone(LIMA)
    fecha, cid = ahora.date(), colegio.id
    if not es_dia_lectivo(db, cid, fecha):
        return 0
    corte_min = asistencia.config(db, cid).minutos_corte_falta
    anio = select(AnioEscolar.id).where(AnioEscolar.colegio_id == cid, AnioEscolar.activo).scalar_subquery()
    alumnos = db.execute(
        select(Alumno.id, Alumno.nombres, Matricula.seccion_id, Turno).select_from(Alumno)
        .join(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id, Matricula.alumno_id == Alumno.id,
                              Matricula.anio_id == anio))
        .join(Seccion, and_(Seccion.colegio_id == Matricula.colegio_id, Seccion.id == Matricula.seccion_id))
        .join(Turno, and_(Turno.colegio_id == Seccion.colegio_id, Turno.id == Seccion.turno_id))
        .where(Alumno.colegio_id == cid, Alumno.activo)).all()
    dias = {d.alumno_id: d for d in db.scalars(select(AsistenciaAlumno).where(
        AsistenciaAlumno.colegio_id == cid, AsistenciaAlumno.fecha == fecha))}
    hechas = set(db.scalars(select(Marcacion.id_cliente).where(
        Marcacion.colegio_id == cid, Marcacion.fecha == fecha, Marcacion.id_cliente.like("demo-%"))))

    eventos = []  # (alumno_id, nombres, tipo, fila del día, momento)
    for alumno_id, nombres, seccion_id, turno in alumnos:
        plan = plan_alumno(cid, fecha, alumno_id, turno)
        dia = dias.get(alumno_id)
        if plan["falta"]:
            corte = _en(fecha, turno.hora_entrada, corte_min)
            if dia is None and ahora >= corte:
                dia = AsistenciaAlumno(colegio_id=cid, alumno_id=alumno_id, fecha=fecha, seccion_id=seccion_id,
                                       estado="falta", minutos_tarde=0)
                db.add(dia)
                eventos.append((alumno_id, nombres, "falta", dia, corte))
            continue
        clave_e, clave_s = f"demo-{fecha}-a{alumno_id}-e", f"demo-{fecha}-a{alumno_id}-s"
        if dia is None and plan["entrada"] <= ahora:
            minutos = asistencia.minutos_tarde(turno, plan["entrada"])
            dia = AsistenciaAlumno(colegio_id=cid, alumno_id=alumno_id, fecha=fecha, seccion_id=seccion_id,
                                   estado="tarde" if minutos else "presente", minutos_tarde=minutos,
                                   entrada=plan["entrada"])
            db.add(dia)
            db.add(Marcacion(colegio_id=cid, id_cliente=clave_e, alumno_id=alumno_id, momento=plan["entrada"],
                             fecha=fecha, origen="qr", equipo=plan["equipo"], resultado="entrada",
                             recibido_en=plan["entrada"]))
            hechas.add(clave_e)
            eventos.append((alumno_id, nombres, "tarde" if minutos else "ingreso", dia, plan["entrada"]))
        if clave_e in hechas and clave_s not in hechas and plan["salida"] <= ahora and dia is not None:
            dia.salida = plan["salida"]
            db.add(Marcacion(colegio_id=cid, id_cliente=clave_s, alumno_id=alumno_id, momento=plan["salida"],
                             fecha=fecha, origen="qr", equipo=plan["equipo"], resultado="salida",
                             recibido_en=plan["salida"]))
            eventos.append((alumno_id, nombres, "salida", dia, plan["salida"]))
    db.flush()
    if eventos:
        _avisos(db, colegio, fecha, eventos)
    return len(eventos) + _personal(db, cid, fecha, ahora)


def _avisos(db: Session, colegio: Colegio, fecha: date, eventos: list) -> None:
    """Cada evento deja su aviso ya procesado y una entrega por apoderado con cuenta activa."""
    cid = colegio.id
    ids = [e[0] for e in eventos]
    destinos: dict[int, list[int]] = {}
    for alumno_id, apoderado_id in db.execute(
            select(AlumnoApoderado.alumno_id, Apoderado.id)
            .join(Apoderado, and_(Apoderado.colegio_id == AlumnoApoderado.colegio_id,
                                  Apoderado.id == AlumnoApoderado.apoderado_id))
            .where(AlumnoApoderado.colegio_id == cid, AlumnoApoderado.alumno_id.in_(ids),
                   AlumnoApoderado.recibe_avisos, Apoderado.estado_acceso == "activo",
                   Apoderado.cuenta_id.is_not(None))):
        destinos.setdefault(alumno_id, []).append(apoderado_id)
    for alumno_id, nombres, tipo, dia, momento in eventos:
        quien = destinos.get(alumno_id, [])
        datos = {} if tipo == "falta" else {"hora": asistencia.hora(momento), "minutos_tarde": dia.minutos_tarde}
        aviso = ColaAviso(colegio_id=cid, alumno_id=alumno_id, fecha=fecha, tipo=tipo, momento=momento,
                          datos=datos, estado="enviado" if quien else "sin_destinatarios", intentos=1 if quien else 0,
                          procesar_desde=momento, procesado_en=momento + timedelta(seconds=4), creado_en=momento)
        q = insert(ColaAviso).values(**{c: getattr(aviso, c) for c in (
            "colegio_id", "alumno_id", "fecha", "tipo", "momento", "datos", "estado", "intentos", "procesar_desde",
            "procesado_en", "creado_en")}).on_conflict_do_nothing().returning(ColaAviso.id)
        aviso_id = db.scalar(q)
        if aviso_id is None or not quien:
            continue
        msj = avisos.mensaje(aviso, colegio, Alumno(nombres=nombres))
        for apoderado_id in quien:
            activos = _azar(cid, date.min, f"ap{apoderado_id}").random() < CON_AVISOS
            db.add(EntregaAviso(colegio_id=cid, aviso_id=aviso_id, apoderado_id=apoderado_id,
                                estado="enviado" if activos else "sin_notificaciones", dispositivos=int(activos),
                                titulo=msj["titulo"][:120], cuerpo=msj["cuerpo"][:300],
                                creado_en=momento + timedelta(seconds=4)))


def _personal(db: Session, cid: int, fecha: date, ahora: datetime) -> int:
    hechos = {d.usuario_id for d in db.scalars(select(AsistenciaPersonal).where(
        AsistenciaPersonal.colegio_id == cid, AsistenciaPersonal.fecha == fecha))}
    con_licencia = set(db.scalars(select(LicenciaPersonal.usuario_id).where(
        LicenciaPersonal.colegio_id == cid, LicenciaPersonal.desde <= fecha, LicenciaPersonal.hasta >= fecha)))
    n = 0
    for u, turno in db.execute(select(Usuario, Turno).select_from(Usuario).join(Turno, and_(Turno.colegio_id == Usuario.colegio_id,
                                                                        Turno.id == Usuario.turno_id))
                               .where(Usuario.colegio_id == cid, Usuario.activo)):
        if u.id in hechos:
            continue
        if u.id in con_licencia:
            db.add(AsistenciaPersonal(colegio_id=cid, usuario_id=u.id, fecha=fecha, estado="licencia",
                                      minutos_tarde=0))
            n += 1
            continue
        entrada = plan_personal(cid, fecha, u.id, turno)["entrada"]
        if entrada > ahora:
            continue
        minutos = asistencia.minutos_tarde(turno, entrada)
        db.add(AsistenciaPersonal(colegio_id=cid, usuario_id=u.id, fecha=fecha, entrada=entrada,
                                  estado="tarde" if minutos else "presente", minutos_tarde=minutos))
        db.add(Marcacion(colegio_id=cid, id_cliente=f"demo-{fecha}-p{u.id}-e", usuario_id=u.id, momento=entrada,
                         fecha=fecha, origen="qr", equipo="Puerta principal", resultado="entrada",
                         recibido_en=entrada))
        n += 1
    db.flush()
    return n


def simular_demos(db: Session, ahora: datetime | None = None) -> int:
    """Para el proceso de fondo: todos los colegios demo disponibles."""
    hoy = (ahora or datetime.now(UTC)).astimezone(LIMA).date()
    total = 0
    for c in db.scalars(select(Colegio).where(Colegio.es_demo)):
        if c.disponible(hoy):
            total += simular_dia(db, c, ahora)
    return total
