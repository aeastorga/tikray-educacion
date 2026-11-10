"""Autorizaciones: a qué alumnos va cada una, quién puede responder, la respuesta vigente, los conteos y los avisos
(al publicar, el recordatorio del día anterior a la fecha límite y el botón "Recordar a los que faltan").

Decisiones aprobadas:
- A2: basta la respuesta de un apoderado; si responden distinto, vale la última y quedan todas en el historial.
- A3: se puede cambiar la respuesta hasta la fecha límite (cada cambio es una fila nueva).
- A4: después de la fecha límite no se responde; quien no respondió queda "sin respuesta".
- A6: responde solo el apoderado que recibe avisos de ese alumno y tiene la cuenta activa.

Los avisos van por la cola en segundo plano como los del calendario: uno por apoderado (aunque tenga varios hijos),
esperan al fin del horario sin molestar y se apagan en Configuración › Avisos ("autorizaciones").
"""

import logging
import threading
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, insert, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app import configuracion
from app.calendario import fecha_texto
from app.fechas import LIMA
from app.models import (Alumno, AlumnoApoderado, AlumnoAutorizacion, Apoderado, Autorizacion, ColaAviso, Colegio,
                        DestinoAutorizacion, Grado, Matricula, Nivel, RespuestaAutorizacion, Seccion)

log = logging.getLogger(__name__)

MAX_BYTES_ADJUNTO = 5 * 1024 * 1024
TIPOS_ADJUNTO = ("application/pdf", "image/jpeg", "image/png", "image/webp")
NOMBRE_ESTADO = {"borrador": "Borrador", "publicada": "Publicada", "cerrada": "Cerrada", "anulada": "Anulada"}


# --- Estado ------------------------------------------------------------------------------------

def estado(a: Autorizacion, hoy: date) -> str:
    """El que se muestra: una publicada cuya fecha límite ya pasó se ve cerrada (A4)."""
    if a.estado == "publicada" and a.fecha_limite < hoy:
        return "cerrada"
    return a.estado


def abierta(a: Autorizacion, hoy: date) -> bool:
    """¿Se puede responder? Publicada y hasta el final del día de la fecha límite (hora de Lima)."""
    return estado(a, hoy) == "publicada"


# --- Textos -------------------------------------------------------------------------------------

def texto_publicada(a: Autorizacion) -> str:
    return f"Autorización: {a.titulo}. Responde hasta {fecha_texto(a.fecha_limite, a.fecha_limite)}."


def texto_recordatorio(a: Autorizacion, hoy: date) -> str:
    if a.fecha_limite == hoy:
        cuando = "hoy"
    elif a.fecha_limite == hoy + timedelta(days=1):
        cuando = "mañana"
    else:
        cuando = fecha_texto(a.fecha_limite, a.fecha_limite)
    return f"Falta tu respuesta: {a.titulo}. Vence {cuando}."


# --- A quién va ------------------------------------------------------------------------------------

def destinos(db: Session, a: Autorizacion) -> dict[str, list[int]]:
    r: dict[str, list[int]] = {"niveles": [], "secciones": [], "alumnos": []}
    for d in db.scalars(select(DestinoAutorizacion).where(DestinoAutorizacion.colegio_id == a.colegio_id,
                                                          DestinoAutorizacion.autorizacion_id == a.id)):
        if d.nivel_id is not None:
            r["niveles"].append(d.nivel_id)
        elif d.seccion_id is not None:
            r["secciones"].append(d.seccion_id)
        else:
            r["alumnos"].append(d.alumno_id)
    return {k: sorted(v) for k, v in r.items()}


def alumnos_elegidos(db: Session, colegio_id: int, anio_id: int, alcance: str,
                     dest: dict[str, list[int]]) -> dict[int, int | None]:
    """{alumno_id: seccion_id} de los alumnos activos a los que va (la sección es la de su matrícula del año)."""
    q = (select(Alumno.id, Matricula.seccion_id)
         .outerjoin(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id, Matricula.alumno_id == Alumno.id,
                                    Matricula.anio_id == anio_id))
         .where(Alumno.colegio_id == colegio_id, Alumno.activo))
    if alcance == "secciones":
        q = q.where(Matricula.seccion_id.in_(dest["secciones"]))
    elif alcance == "niveles":
        q = (q.join(Seccion, and_(Seccion.colegio_id == Matricula.colegio_id, Seccion.id == Matricula.seccion_id))
             .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
             .where(Grado.nivel_id.in_(dest["niveles"])))
    elif alcance == "alumnos":
        q = q.where(Alumno.id.in_(dest["alumnos"]))
    return dict(db.execute(q).all())


def alumnos_de(db: Session, a: Autorizacion) -> dict[int, int | None]:
    """Los alumnos a los que va: los fijados al publicar o, sin publicar, los que tocarían hoy."""
    if a.publicada_en is None:
        return alumnos_elegidos(db, a.colegio_id, a.anio_id, a.alcance, destinos(db, a))
    return dict(db.execute(select(AlumnoAutorizacion.alumno_id, AlumnoAutorizacion.seccion_id).where(
        AlumnoAutorizacion.colegio_id == a.colegio_id, AlumnoAutorizacion.autorizacion_id == a.id)).all())


def dentro_de(alumnos: dict[int, int | None], permitidas: set[int] | None) -> bool:
    """¿Todos los alumnos son de las secciones permitidas? (None: ve todo el colegio)."""
    return permitidas is None or all(s in permitidas for s in alumnos.values())


def toca_secciones(alumnos: dict[int, int | None], permitidas: set[int] | None) -> bool:
    return permitidas is None or any(s in permitidas for s in alumnos.values())


# --- Respuestas ----------------------------------------------------------------------------------

def vigentes(db: Session, colegio_id: int, autorizacion_ids: list[int]) -> dict[tuple[int, int], RespuestaAutorizacion]:
    """{(autorizacion_id, alumno_id): última respuesta} (A2: vale la última, sea de quien sea)."""
    if not autorizacion_ids:
        return {}
    filas = db.scalars(
        select(RespuestaAutorizacion)
        .where(RespuestaAutorizacion.colegio_id == colegio_id,
               RespuestaAutorizacion.autorizacion_id.in_(autorizacion_ids))
        .ext(distinct_on(RespuestaAutorizacion.autorizacion_id, RespuestaAutorizacion.alumno_id))
        .order_by(RespuestaAutorizacion.autorizacion_id, RespuestaAutorizacion.alumno_id,
                  RespuestaAutorizacion.respondido_en.desc(), RespuestaAutorizacion.id.desc()))
    return {(r.autorizacion_id, r.alumno_id): r for r in filas}


def historial(db: Session, a: Autorizacion) -> dict[int, list[RespuestaAutorizacion]]:
    """{alumno_id: respuestas de la más antigua a la última}."""
    r: dict[int, list[RespuestaAutorizacion]] = {}
    for fila in db.scalars(select(RespuestaAutorizacion).where(
            RespuestaAutorizacion.colegio_id == a.colegio_id, RespuestaAutorizacion.autorizacion_id == a.id)
            .order_by(RespuestaAutorizacion.respondido_en, RespuestaAutorizacion.id)):
        r.setdefault(fila.alumno_id, []).append(fila)
    return r


def conteo(alumnos: list[int], vig: dict[int, RespuestaAutorizacion | None]) -> dict:
    si = sum(1 for a in alumnos if vig.get(a) is not None and vig[a].autoriza)
    no = sum(1 for a in alumnos if vig.get(a) is not None and not vig[a].autoriza)
    return {"total": len(alumnos), "autorizan": si, "no_autorizan": no, "faltan": len(alumnos) - si - no}


def respuesta_dict(r: RespuestaAutorizacion) -> dict:
    return {"autoriza": r.autoriza, "comentario": r.comentario, "apoderado": r.apoderado_nombre,
            "en": r.respondido_en.isoformat()}


def puede_responder(db: Session, colegio_id: int, apoderado_id: int, alumno_id: int) -> bool:
    """A6: el apoderado recibe los avisos de ese alumno y tiene la cuenta activa."""
    return db.scalar(select(AlumnoApoderado.alumno_id)
                     .join(Apoderado, and_(Apoderado.colegio_id == AlumnoApoderado.colegio_id,
                                           Apoderado.id == AlumnoApoderado.apoderado_id))
                     .where(AlumnoApoderado.colegio_id == colegio_id, AlumnoApoderado.alumno_id == alumno_id,
                            AlumnoApoderado.apoderado_id == apoderado_id, AlumnoApoderado.recibe_avisos,
                            Apoderado.estado_acceso == "activo")) is not None


# --- Avisos ------------------------------------------------------------------------------------------

def apoderados_que_responden(db: Session, colegio_id: int, alumno_ids: list[int]) -> list[int]:
    """A6: apoderados que reciben avisos de esos alumnos y tienen la cuenta activa (sin repetir)."""
    if not alumno_ids:
        return []
    return sorted(set(db.scalars(
        select(Apoderado.id)
        .join(AlumnoApoderado, and_(AlumnoApoderado.colegio_id == Apoderado.colegio_id,
                                    AlumnoApoderado.apoderado_id == Apoderado.id))
        .where(Apoderado.colegio_id == colegio_id, AlumnoApoderado.alumno_id.in_(alumno_ids),
               AlumnoApoderado.recibe_avisos, Apoderado.estado_acceso == "activo"))))


def _encolar(db: Session, a: Autorizacion, alumno_ids: list[int], mensaje: str, que: str, ahora: datetime) -> int:
    apoderados = apoderados_que_responden(db, a.colegio_id, alumno_ids)
    if apoderados:
        datos = {"mensaje": mensaje[:280], "url": "/familia/autorizaciones", "autorizacion_id": a.id, "que": que}
        db.execute(insert(ColaAviso).values([
            {"colegio_id": a.colegio_id, "tipo": "autorizar", "apoderado_id": p, "datos": datos,
             "fecha": ahora.astimezone(LIMA).date(), "procesar_desde": ahora} for p in apoderados]))
    return len(apoderados)


def pendientes(db: Session, a: Autorizacion) -> list[int]:
    """Alumnos que aún no tienen respuesta."""
    vig = vigentes(db, a.colegio_id, [a.id])
    return [al for al in alumnos_de(db, a) if (a.id, al) not in vig]


def publicar(db: Session, a: Autorizacion, colegio: Colegio, ahora: datetime | None = None) -> int:
    """Fija los alumnos a los que va, la deja publicada y encola el aviso. Si la fecha límite es hoy o mañana,
    el aviso de publicación hace de recordatorio. Devuelve cuántos avisos encoló."""
    ahora = ahora or datetime.now(UTC)
    hoy = ahora.astimezone(LIMA).date()
    alumnos = alumnos_de(db, a)
    db.execute(insert(AlumnoAutorizacion).values([
        {"colegio_id": a.colegio_id, "autorizacion_id": a.id, "alumno_id": al, "seccion_id": sec}
        for al, sec in alumnos.items()]))
    a.estado, a.publicada_en = "publicada", ahora
    if a.fecha_limite <= hoy + timedelta(days=1):
        a.recordatorio_en = ahora
    if not configuracion.aviso_permitido(colegio, "autorizar"):
        return 0
    return _encolar(db, a, list(alumnos), texto_publicada(a), "publicada", ahora)


def recordar(db: Session, a: Autorizacion, que: str = "recordar", ahora: datetime | None = None) -> int:
    """Aviso solo a los apoderados de los alumnos sin respuesta. Devuelve cuántos avisos encoló."""
    ahora = ahora or datetime.now(UTC)
    return _encolar(db, a, pendientes(db, a), texto_recordatorio(a, ahora.astimezone(LIMA).date()), que, ahora)


def quitar_pendientes(db: Session, a: Autorizacion, motivo: str) -> None:
    """Descarta los avisos que aún no salieron (anulada o cerrada). Quedan en la cola como descartados."""
    ahora = datetime.now(UTC)
    for aviso in db.scalars(select(ColaAviso).where(
            ColaAviso.colegio_id == a.colegio_id, ColaAviso.tipo == "autorizar", ColaAviso.estado == "pendiente",
            ColaAviso.datos["autorizacion_id"].as_integer() == a.id).with_for_update()):
        aviso.estado, aviso.procesado_en = "descartado", ahora
        aviso.datos = {**aviso.datos, "motivo": motivo}


def revisar_recordatorios(db: Session, hoy: date | None = None, ahora: datetime | None = None) -> int:
    """Encola el recordatorio de las que vencen mañana, solo a los que no respondieron (una vez por autorización:
    queda marcada). El horario sin molestar lo respeta la cola. Devuelve cuántos avisos encoló."""
    ahora = ahora or datetime.now(UTC)
    hoy = hoy or ahora.astimezone(LIMA).date()
    encolados = 0
    lista = db.scalars(select(Autorizacion).where(
        Autorizacion.estado == "publicada", Autorizacion.fecha_limite == hoy + timedelta(days=1),
        Autorizacion.recordatorio_en.is_(None)).with_for_update(skip_locked=True)).all()
    colegios: dict[int, Colegio] = {}
    for a in lista:
        colegio = colegios.setdefault(a.colegio_id, db.get(Colegio, a.colegio_id))
        if (not colegio.disponible(hoy) or not colegio.modulo_activo("autorizaciones")
                or not configuracion.aviso_permitido(colegio, "autorizar")):
            continue
        a.recordatorio_en = ahora
        encolados += _encolar(db, a, pendientes(db, a), texto_recordatorio(a, hoy), "recordatorio", ahora)
        db.flush()
    db.commit()
    return encolados


def bucle_recordatorios(parar: threading.Event, cada: float = 600) -> None:
    """Hilo del servidor: revisa los recordatorios cada 10 minutos. La marca de cada autorización evita repetirlos."""
    from app.db import get_sessionmaker

    while True:
        try:
            with get_sessionmaker()() as db:
                revisar_recordatorios(db)
        except Exception:
            log.exception("Recordatorios de autorizaciones")
        if parar.wait(cada):
            return


# --- Nombres -----------------------------------------------------------------------------------------

def nombres_secciones(db: Session, colegio_id: int) -> dict[int, str]:
    return {sid: f"{g} {s} {n}" for sid, n, g, s in db.execute(
        select(Seccion.id, Nivel.nombre, Grado.nombre, Seccion.nombre)
        .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
        .join(Nivel, and_(Nivel.colegio_id == Grado.colegio_id, Nivel.id == Grado.nivel_id))
        .where(Seccion.colegio_id == colegio_id))}


def orden_secciones(db: Session, colegio_id: int) -> dict[int, tuple]:
    return {sid: (no, go, s) for sid, no, go, s in db.execute(
        select(Seccion.id, Nivel.orden, Grado.orden, Seccion.nombre)
        .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
        .join(Nivel, and_(Nivel.colegio_id == Grado.colegio_id, Nivel.id == Grado.nivel_id))
        .where(Seccion.colegio_id == colegio_id))}


def para_quien(db: Session, a: Autorizacion, dest: dict[str, list[int]]) -> str:
    if a.alcance == "colegio":
        return "Todo el colegio"
    if a.alcance == "niveles":
        nombres = dict(db.execute(select(Nivel.id, Nivel.nombre).where(Nivel.colegio_id == a.colegio_id)).all())
        return ", ".join(sorted(nombres.get(i, "?") for i in dest["niveles"])) or "Ningún nivel"
    if a.alcance == "secciones":
        nombres = nombres_secciones(db, a.colegio_id)
        return ", ".join(sorted(nombres.get(i, "?") for i in dest["secciones"])) or "Ninguna sección"
    n = len(dest["alumnos"])
    return f"{n} alumno{'s' if n != 1 else ''}"
