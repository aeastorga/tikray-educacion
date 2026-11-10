"""Calendario escolar: a quién va cada evento, qué ve cada familia, el aviso al publicar y el recordatorio
del día anterior (C4 y C5: solo si se marcó "avisar a las familias").

Los avisos van por la cola en segundo plano como los del cuaderno: un aviso por apoderado con acceso,
esperan al fin del horario sin molestar y se apagan en Configuración › Avisos ("calendario").
"""

import logging
import threading
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, insert, select
from sqlalchemy.orm import Session

from app import configuracion
from app.fechas import LIMA, hoy_lima
from app.models import (Alumno, AlumnoApoderado, Apoderado, ColaAviso, Colegio, DestinoEvento, DiaNoLectivo,
                        EventoCalendario, Grado, Matricula, Nivel, Seccion)

log = logging.getLogger(__name__)

NOMBRE_TIPO = {"actuacion": "Actuación", "reunion_padres": "Reunión de padres", "examen": "Examen",
               "feriado": "Feriado", "salida": "Salida o paseo", "otro": "Otro"}
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre")


# --- Textos -------------------------------------------------------------------------------------

def fecha_texto(inicio: date, fin: date) -> str:
    """"el viernes 14 de noviembre" o "del 14 al 16 de noviembre" (o "del 28 de noviembre al 2 de diciembre")."""
    if inicio == fin:
        return f"el {DIAS[inicio.weekday()]} {inicio.day} de {MESES[inicio.month - 1]}"
    if (inicio.year, inicio.month) == (fin.year, fin.month):
        return f"del {inicio.day} al {fin.day} de {MESES[fin.month - 1]}"
    return f"del {inicio.day} de {MESES[inicio.month - 1]} al {fin.day} de {MESES[fin.month - 1]}"


def _a_las(e: EventoCalendario) -> str:
    return f" a las {e.hora.strftime('%H:%M')}" if e.hora else ""  # el formato de hora de los demás avisos


def texto_publicado(e: EventoCalendario) -> str:
    return f"Calendario: {e.titulo}, {fecha_texto(e.inicio, e.fin)}{_a_las(e)}."


def texto_recordatorio(e: EventoCalendario) -> str:
    return f"Mañana: {e.titulo}{_a_las(e)}."


# --- A quién va ---------------------------------------------------------------------------------

def destinos(db: Session, colegio_id: int, eventos: list[EventoCalendario]) -> dict[int, dict[str, list[int]]]:
    """{evento_id: {"niveles": [...], "secciones": [...]}}"""
    r: dict[int, dict[str, list[int]]] = {e.id: {"niveles": [], "secciones": []} for e in eventos}
    if not r:
        return r
    for d in db.scalars(select(DestinoEvento).where(DestinoEvento.colegio_id == colegio_id,
                                                    DestinoEvento.evento_id.in_(r))):
        if d.nivel_id is not None:
            r[d.evento_id]["niveles"].append(d.nivel_id)
        else:
            r[d.evento_id]["secciones"].append(d.seccion_id)
    return r


def ubicacion(db: Session, colegio_id: int, alumno_ids: list[int]) -> dict[tuple[int, int], tuple[int, int]]:
    """{(anio_id, alumno_id): (seccion_id, nivel_id)} de las matrículas de esos alumnos."""
    if not alumno_ids:
        return {}
    filas = db.execute(
        select(Matricula.anio_id, Matricula.alumno_id, Matricula.seccion_id, Grado.nivel_id)
        .join(Seccion, and_(Seccion.colegio_id == Matricula.colegio_id, Seccion.id == Matricula.seccion_id))
        .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
        .where(Matricula.colegio_id == colegio_id, Matricula.alumno_id.in_(alumno_ids)))
    return {(anio, alumno): (sec, niv) for anio, alumno, sec, niv in filas}


def le_toca(e: EventoCalendario, dest: dict[str, list[int]], alumno_id: int,
            donde: dict[tuple[int, int], tuple[int, int]]) -> bool:
    """¿El evento es para este alumno? Todo el colegio: sí. Nivel o sección: según su matrícula de ese año."""
    if e.alcance == "colegio":
        return True
    lugar = donde.get((e.anio_id, alumno_id))
    if lugar is None:
        return False
    seccion_id, nivel_id = lugar
    return seccion_id in dest["secciones"] if e.alcance == "secciones" else nivel_id in dest["niveles"]


def alumnos_del_evento(db: Session, e: EventoCalendario) -> list[int]:
    q = select(Alumno.id).where(Alumno.colegio_id == e.colegio_id, Alumno.activo)
    if e.alcance != "colegio":
        dest = destinos(db, e.colegio_id, [e])[e.id]
        q = (q.join(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id, Matricula.alumno_id == Alumno.id,
                                    Matricula.anio_id == e.anio_id)))
        if e.alcance == "secciones":
            q = q.where(Matricula.seccion_id.in_(dest["secciones"]))
        else:
            q = (q.join(Seccion, and_(Seccion.colegio_id == Matricula.colegio_id, Seccion.id == Matricula.seccion_id))
                 .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
                 .where(Grado.nivel_id.in_(dest["niveles"])))
    return list(db.scalars(q))


def apoderados_del_evento(db: Session, e: EventoCalendario) -> list[int]:
    """Apoderados con acceso activo a la app de los alumnos a los que va el evento (sin repetir)."""
    alumnos = alumnos_del_evento(db, e)
    if not alumnos:
        return []
    return sorted(set(db.scalars(
        select(Apoderado.id)
        .join(AlumnoApoderado, and_(AlumnoApoderado.colegio_id == Apoderado.colegio_id,
                                    AlumnoApoderado.apoderado_id == Apoderado.id))
        .where(Apoderado.colegio_id == e.colegio_id, AlumnoApoderado.alumno_id.in_(alumnos),
               Apoderado.estado_acceso == "activo"))))


# --- Avisos ---------------------------------------------------------------------------------------

def _encolar(db: Session, e: EventoCalendario, mensaje: str, que: str, ahora: datetime) -> int:
    apoderados = apoderados_del_evento(db, e)
    if apoderados:
        datos = {"mensaje": mensaje[:280], "url": "/familia/calendario", "evento_id": e.id, "que": que}
        db.execute(insert(ColaAviso).values([
            {"colegio_id": e.colegio_id, "tipo": "calendario", "apoderado_id": a, "datos": datos,
             "fecha": ahora.astimezone(LIMA).date(), "procesar_desde": ahora} for a in apoderados]))
    return len(apoderados)


def al_guardar(db: Session, e: EventoCalendario, colegio: Colegio, ahora: datetime | None = None) -> int:
    """Después de crear o editar: si se marcó "avisar" y aún no se avisó, encola el aviso de publicación
    (solo si el evento no terminó). Si el evento es hoy o mañana, el aviso de publicación hace de
    recordatorio. Devuelve cuántos avisos encoló."""
    ahora = ahora or datetime.now(UTC)
    hoy = ahora.astimezone(LIMA).date()
    if not e.avisar or e.anulado_en is not None:
        quitar_pendientes(db, e)
        return 0
    encolados = 0
    if e.aviso_en is None:
        e.aviso_en = ahora
        if e.fin >= hoy and configuracion.aviso_permitido(colegio, "calendario"):
            encolados = _encolar(db, e, texto_publicado(e), "publicado", ahora)
    if e.recordatorio_en is None and e.inicio <= hoy + timedelta(days=1):
        e.recordatorio_en = ahora  # ya no hace falta: el evento es hoy, mañana o ya pasó
    return encolados


def quitar_pendientes(db: Session, e: EventoCalendario, motivo: str = "ya no se avisa") -> None:
    """Descarta los avisos de este evento que aún no salieron (anulado, o ya no se avisa). No se borran:
    quedan en la cola como descartados, con el motivo."""
    ahora = datetime.now(UTC)
    for aviso in db.scalars(select(ColaAviso).where(
            ColaAviso.colegio_id == e.colegio_id, ColaAviso.tipo == "calendario", ColaAviso.estado == "pendiente",
            ColaAviso.datos["evento_id"].as_integer() == e.id).with_for_update()):
        aviso.estado, aviso.procesado_en = "descartado", ahora
        aviso.datos = {**aviso.datos, "motivo": motivo}


def revisar_recordatorios(db: Session, hoy: date | None = None, ahora: datetime | None = None) -> int:
    """Encola el recordatorio de los eventos de mañana marcados con "avisar" (una sola vez por evento: queda
    marcado). Corre seguido para alcanzar a los creados durante el día; el horario sin molestar lo respeta
    la cola. Devuelve cuántos avisos encoló."""
    ahora = ahora or datetime.now(UTC)
    hoy = hoy or ahora.astimezone(LIMA).date()
    manana = hoy + timedelta(days=1)
    encolados = 0
    eventos = db.scalars(select(EventoCalendario).where(
        EventoCalendario.inicio == manana, EventoCalendario.avisar, EventoCalendario.anulado_en.is_(None),
        EventoCalendario.recordatorio_en.is_(None)).with_for_update(skip_locked=True)).all()
    colegios: dict[int, Colegio] = {}
    for e in eventos:
        colegio = colegios.setdefault(e.colegio_id, db.get(Colegio, e.colegio_id))
        if (not colegio.disponible(hoy) or not colegio.modulo_activo("calendario")
                or not configuracion.aviso_permitido(colegio, "calendario")):
            continue
        e.recordatorio_en = ahora
        encolados += _encolar(db, e, texto_recordatorio(e), "recordatorio", ahora)
        db.flush()
    db.commit()
    return encolados


def bucle_recordatorios(parar: threading.Event, cada: float = 600) -> None:
    """Hilo del servidor: revisa los recordatorios cada 10 minutos. La marca de cada evento evita repetirlos."""
    from app.db import get_sessionmaker

    while True:
        try:
            with get_sessionmaker()() as db:
                revisar_recordatorios(db)
        except Exception:
            log.exception("Recordatorios del calendario")
        if parar.wait(cada):
            return


# --- Lectura ---------------------------------------------------------------------------------------

def eventos_entre(db: Session, colegio_id: int, desde: date, hasta: date) -> list[EventoCalendario]:
    """Los que tocan algún día del rango (también los anulados)."""
    return list(db.scalars(select(EventoCalendario).where(
        EventoCalendario.colegio_id == colegio_id, EventoCalendario.inicio <= hasta, EventoCalendario.fin >= desde)
        .order_by(EventoCalendario.inicio, EventoCalendario.hora.nulls_first(), EventoCalendario.id)))


def proximos(db: Session, colegio_id: int, hoy: date, limite: int) -> list[EventoCalendario]:
    """Los que no terminaron ni se anularon, del más cercano al más lejano."""
    return list(db.scalars(select(EventoCalendario).where(
        EventoCalendario.colegio_id == colegio_id, EventoCalendario.fin >= hoy, EventoCalendario.anulado_en.is_(None))
        .order_by(EventoCalendario.inicio, EventoCalendario.hora.nulls_first(), EventoCalendario.id).limit(limite)))


def sin_clases(db: Session, colegio_id: int, desde: date, hasta: date) -> list[dict]:
    return [{"fecha": d.fecha.isoformat(), "motivo": d.motivo} for d in db.scalars(
        select(DiaNoLectivo).where(DiaNoLectivo.colegio_id == colegio_id, DiaNoLectivo.fecha.between(desde, hasta))
        .order_by(DiaNoLectivo.fecha))]


def nombres_destinos(db: Session, colegio_id: int) -> tuple[dict[int, str], dict[int, str]]:
    niveles = dict(db.execute(select(Nivel.id, Nivel.nombre).where(Nivel.colegio_id == colegio_id)).all())
    secciones = {sid: f"{n} · {g} {s}" for sid, n, g, s in db.execute(
        select(Seccion.id, Nivel.nombre, Grado.nombre, Seccion.nombre)
        .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
        .join(Nivel, and_(Nivel.colegio_id == Grado.colegio_id, Nivel.id == Grado.nivel_id))
        .where(Seccion.colegio_id == colegio_id))}
    return niveles, secciones


def para_quien(e: EventoCalendario, dest: dict[str, list[int]], niveles: dict[int, str],
               secciones: dict[int, str]) -> str:
    if e.alcance == "colegio":
        return "Todo el colegio"
    if e.alcance == "niveles":
        return ", ".join(sorted(niveles.get(i, "?") for i in dest["niveles"])) or "Ningún nivel"
    return ", ".join(sorted(secciones.get(i, "?") for i in dest["secciones"])) or "Ninguna sección"


def evento_dict(e: EventoCalendario, dest: dict[str, list[int]], para: str, completo: bool = True) -> dict:
    """`completo`: con lo que solo ve el colegio (destinos por id, avisar)."""
    d = {"id": e.id, "titulo": e.titulo, "descripcion": e.descripcion, "inicio": e.inicio.isoformat(),
         "fin": e.fin.isoformat(), "hora": e.hora.strftime("%H:%M") if e.hora else None, "tipo": e.tipo,
         "tipo_nombre": NOMBRE_TIPO[e.tipo], "para": para, "anulado": e.anulado_en is not None,
         "anulado_motivo": e.anulado_motivo}
    if completo:
        d |= {"alcance": e.alcance, "niveles": sorted(dest["niveles"]), "secciones": sorted(dest["secciones"]),
              "avisar": e.avisar, "avisado": e.aviso_en is not None}
    return d


def primer_dia_mes(mes: str | None) -> date:
    hoy = hoy_lima()
    if not mes:
        return hoy.replace(day=1)
    try:
        return date.fromisoformat(f"{mes}-01")
    except ValueError:
        from fastapi import HTTPException, status
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Mes inválido (usa AAAA-MM)") from None


def ultimo_dia_mes(inicio: date) -> date:
    return (inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1)
