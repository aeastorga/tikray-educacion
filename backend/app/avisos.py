"""Proceso que vacía `cola_aviso`: arma el mensaje, revisa que siga siendo cierto
y lo envía por push a cada apoderado que recibe avisos. Deja una `entrega_aviso`
por apoderado (el "estado de avisos por padre").

Corre en un hilo del servidor; varias instancias pueden correr a la vez porque
toma los avisos con FOR UPDATE SKIP LOCKED.
"""

import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import configuracion
from app.config import get_settings
from app.models import (Alumno, AlumnoApoderado, Apoderado, AsistenciaAlumno, ColaAviso, Colegio, EntregaAviso,
                        SuscripcionPush)

log = logging.getLogger(__name__)

MAX_INTENTOS = 5
# Un aviso que no pudo salir en este tiempo ya no sirve ("ingresó a las 7:40" a la noche).
VIGENCIA = timedelta(hours=6)
# Respetan el horario sin molestar (la asistencia sale siempre) y solo llegan a quien ya tiene acceso.
ESPERAN_SILENCIO = ("cuaderno", "cobro", "calendario")

# Resultado de enviar a un navegador: "ok", "expirada" (el navegador la dio de baja) o "error".
Enviador = Callable[[SuscripcionPush, dict], str]


def push_configurado() -> bool:
    s = get_settings()
    return bool(s.vapid_clave_privada and s.vapid_clave_publica)


def enviar_push(sus: SuscripcionPush, mensaje: dict) -> str:
    from pywebpush import WebPushException, webpush

    s = get_settings()
    try:
        webpush({"endpoint": sus.endpoint, "keys": {"p256dh": sus.p256dh, "auth": sus.auth}},
                data=json.dumps(mensaje), vapid_private_key=s.vapid_clave_privada,
                vapid_claims={"sub": s.vapid_contacto}, ttl=6 * 3600, timeout=10)
        return "ok"
    except WebPushException as e:
        codigo = getattr(e.response, "status_code", None)
        if codigo in (404, 410):
            return "expirada"
        log.warning("Push %s: %s", codigo, e)
        return "error"
    except Exception:
        log.exception("Push")
        return "error"


def _primer_nombre(a: Alumno) -> str:
    return a.nombres.split()[0] if a.nombres else a.apellidos


def mensaje(aviso: ColaAviso, colegio: Colegio, alumno: Alumno | None) -> dict:
    hora = aviso.datos.get("hora")
    if aviso.tipo == "cuenta":
        titulo, cuerpo = colegio.nombre, aviso.datos.get("mensaje", "Hubo un cambio en tu cuenta.")
    elif aviso.tipo == "cuaderno":
        titulo, cuerpo = colegio.nombre, aviso.datos.get("mensaje", "Tienes una novedad en el cuaderno.")
    elif aviso.tipo == "cobro":
        titulo, cuerpo = colegio.nombre, aviso.datos.get("mensaje", "Tienes cuotas por pagar.")
    elif aviso.tipo == "calendario":
        titulo, cuerpo = colegio.nombre, aviso.datos.get("mensaje", "Hay una novedad en el calendario.")
    else:
        n = _primer_nombre(alumno)
        cuerpo = {
            "ingreso": f"{n} ingresó al colegio a las {hora}.",
            "tarde": f"{n} llegó tarde: ingresó a las {hora} ({aviso.datos.get('minutos_tarde')} min).",
            "salida": f"{n} salió del colegio a las {hora}.",
            "falta": f"{n} no ha llegado hoy al colegio.",
        }[aviso.tipo]
        titulo = colegio.nombre
    if aviso.tipo in ESPERAN_SILENCIO:  # cada novedad del cuaderno y cada recordatorio es su propia notificación
        return {"titulo": titulo, "cuerpo": cuerpo, "url": aviso.datos.get("url", "/familia"),
                "etiqueta": f"{aviso.tipo}-{aviso.id}"}
    return {"titulo": titulo, "cuerpo": cuerpo, "url": "/familia",
            "etiqueta": f"{aviso.tipo}-{aviso.alumno_id or aviso.apoderado_id}-{aviso.fecha}"}


def _sigue_vigente(db: Session, aviso: ColaAviso, ahora: datetime) -> str | None:
    """Motivo para no enviarlo, o None."""
    # Lo del cuaderno y los cobros pueden esperar a propósito (programado, horario sin molestar): cuenta desde que pudo salir.
    desde = aviso.procesar_desde if aviso.tipo in ESPERAN_SILENCIO else aviso.creado_en
    if ahora - desde > VIGENCIA:
        return "vencido"
    if aviso.tipo == "falta":
        # Entre que se encoló y ahora pudo llegar (o registrarse una marcación sin internet).
        estado = db.scalar(select(AsistenciaAlumno.estado).where(
            AsistenciaAlumno.colegio_id == aviso.colegio_id, AsistenciaAlumno.alumno_id == aviso.alumno_id,
            AsistenciaAlumno.fecha == aviso.fecha))
        if estado != "falta":
            return "ya llegó"
    return None


def _destinatarios(db: Session, aviso: ColaAviso) -> list[Apoderado]:
    if aviso.apoderado_id is not None:
        # De su cuenta se le avisa aunque esté pendiente; del cuaderno, solo si ya tiene acceso.
        estados = ("activo",) if aviso.tipo in ESPERAN_SILENCIO else ("activo", "pendiente")
        q = select(Apoderado).where(Apoderado.colegio_id == aviso.colegio_id, Apoderado.id == aviso.apoderado_id,
                                    Apoderado.estado_acceso.in_(estados))
    else:
        q = (select(Apoderado)
             .join(AlumnoApoderado, (AlumnoApoderado.colegio_id == Apoderado.colegio_id)
                   & (AlumnoApoderado.apoderado_id == Apoderado.id))
             .where(Apoderado.colegio_id == aviso.colegio_id, AlumnoApoderado.alumno_id == aviso.alumno_id,
                    AlumnoApoderado.recibe_avisos, Apoderado.estado_acceso == "activo"))
    return [a for a in db.scalars(q) if a.cuenta_id is not None]


def _procesar(db: Session, aviso: ColaAviso, enviar: Enviador, ahora: datetime) -> None:
    colegio = db.get(Colegio, aviso.colegio_id)
    if not configuracion.aviso_permitido(colegio, aviso.tipo):
        aviso.estado, aviso.procesado_en = "descartado", ahora
        aviso.datos = {**aviso.datos, "motivo": "apagado por el colegio"}
        return
    if aviso.tipo in ESPERAN_SILENCIO and (fin := configuracion.fin_del_silencio(colegio, ahora)):
        aviso.procesar_desde = fin  # horario sin molestar: espera en la cola (la asistencia sale siempre)
        return
    motivo = _sigue_vigente(db, aviso, ahora)
    if motivo:
        aviso.estado, aviso.procesado_en, aviso.datos = "descartado", ahora, {**aviso.datos, "motivo": motivo}
        return
    destinatarios = _destinatarios(db, aviso)
    if not destinatarios:
        aviso.estado, aviso.procesado_en = "sin_destinatarios", ahora
        return
    alumno = db.get(Alumno, aviso.alumno_id) if aviso.alumno_id else None
    msj = mensaje(aviso, colegio, alumno)
    ya = {e.apoderado_id: e for e in db.scalars(select(EntregaAviso).where(
        EntregaAviso.colegio_id == aviso.colegio_id, EntregaAviso.aviso_id == aviso.id))}
    pendientes_error = False
    for ap in destinatarios:
        entrega = ya.get(ap.id)
        if entrega is not None and entrega.estado != "error":
            continue  # en un reintento no se repite a quien ya le llegó
        # La cuenta es global: le llega en todos los navegadores donde aceptó notificaciones.
        subs = db.scalars(select(SuscripcionPush).where(SuscripcionPush.cuenta_id == ap.cuenta_id)).all()
        ok = 0
        for sus in subs:
            r = enviar(sus, msj)
            if r == "ok":
                ok += 1
                sus.ultimo_envio = ahora
            elif r == "expirada":
                db.execute(delete(SuscripcionPush).where(SuscripcionPush.id == sus.id))
        estado = "enviado" if ok else ("sin_notificaciones" if not subs else "error")
        if entrega is None:
            entrega = EntregaAviso(colegio_id=aviso.colegio_id, aviso_id=aviso.id, apoderado_id=ap.id,
                                   titulo=msj["titulo"][:120], cuerpo=msj["cuerpo"][:300], estado=estado)
            db.add(entrega)
        entrega.estado, entrega.dispositivos = estado, ok
        entrega.detalle = None if estado != "error" else "No se pudo entregar; se reintentará"
        pendientes_error |= estado == "error"
    aviso.intentos += 1
    if pendientes_error and aviso.intentos < MAX_INTENTOS:
        aviso.procesar_desde = ahora + timedelta(minutes=2 ** aviso.intentos)
    else:
        aviso.estado, aviso.procesado_en = ("error" if pendientes_error else "enviado"), ahora


def procesar_cola(db: Session, enviar: Enviador = enviar_push, ahora: datetime | None = None,
                  limite: int = 100) -> int:
    """Procesa hasta `limite` avisos pendientes y hace commit. Devuelve cuántos procesó."""
    ahora = ahora or datetime.now(UTC)
    avisos = db.scalars(select(ColaAviso).where(ColaAviso.estado == "pendiente", ColaAviso.procesar_desde <= ahora)
                        .order_by(ColaAviso.procesar_desde).limit(limite).with_for_update(skip_locked=True)).all()
    for aviso in avisos:
        _procesar(db, aviso, enviar, ahora)
        db.flush()
    db.commit()
    return len(avisos)


def bucle_avisos(parar: threading.Event, cada: float = 3) -> None:
    from app.db import get_sessionmaker

    if not push_configurado():
        log.warning("Push sin configurar (VAPID_CLAVE_PRIVADA/PUBLICA): los avisos quedan en la cola")
        return
    while not parar.wait(cada):
        try:
            with get_sessionmaker()() as db:
                while procesar_cola(db) == 100:  # si hay más, seguir sin esperar
                    pass
        except Exception:
            log.exception("Envío de avisos")
