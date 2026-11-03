"""Panel "Cuentas de padres": invitar (enlace de un solo uso para enviar por
WhatsApp), aprobar, bloquear, cerrar sesiones, y el estado de avisos de cada padre."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app import familias
from app.comun import obtener
from app.configuracion import anotar
from app.db import get_db
from app.deps import Sesion, requerir_permiso
from app.models import (Alumno, AlumnoApoderado, Apoderado, CambioApoderado, ConfigFamilias, ConsentimientoApoderado,
                        EntregaAviso, InvitacionFamilia, SuscripcionPush, Usuario)
from app.validacion import sin_tildes

router = APIRouter(prefix="/familias", tags=["familias"])
ver = requerir_permiso("familias")
editar = requerir_permiso("familias", "editar")
editar_reglas = requerir_permiso("configuracion", "editar")


def _notificaciones(ap: Apoderado, dispositivos: int) -> str:
    """activas: le llegan push. sin_permiso: entró a la app pero no aceptó notificaciones. sin_app: nunca entró."""
    if ap.cuenta_id is None:
        return "sin_app"
    return "activas" if dispositivos else "sin_permiso"


def _invitacion(inv: InvitacionFamilia | None) -> dict | None:
    if inv is None:
        return None
    return {"estado": familias.estado_invitacion(inv), "creado_en": inv.creado_en.isoformat(),
            "vence_en": inv.vence_en.isoformat(), "intentos": inv.intentos, "motivo_anulacion": inv.motivo_anulacion}


@router.get("/apoderados")
def listar(q: str = "", estado: str | None = None, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> list[dict]:
    cid = s.colegio.id
    consulta = select(Apoderado).where(Apoderado.colegio_id == cid)
    if estado:
        consulta = consulta.where(Apoderado.estado_acceso == estado)
    texto = sin_tildes(q.strip().lower())
    if texto:
        consulta = consulta.where(or_(
            func.translate(func.lower(Apoderado.apellidos + " " + Apoderado.nombres), "áéíóúüñ", "aeiouun")
            .contains(texto), Apoderado.numero_documento.contains(texto.upper())))
    aps = db.scalars(consulta.order_by(Apoderado.apellidos, Apoderado.nombres).limit(500)).all()
    ids = [a.id for a in aps]
    hijos: dict[int, list[str]] = {}
    for apo_id, nombres in db.execute(
            select(AlumnoApoderado.apoderado_id, Alumno.nombres)
            .join(Alumno, and_(Alumno.colegio_id == AlumnoApoderado.colegio_id, Alumno.id == AlumnoApoderado.alumno_id))
            .where(AlumnoApoderado.colegio_id == cid, AlumnoApoderado.apoderado_id.in_(ids), Alumno.activo)):
        hijos.setdefault(apo_id, []).append(nombres)
    dispositivos = dict(db.execute(
        select(SuscripcionPush.cuenta_id, func.count()).where(
            SuscripcionPush.cuenta_id.in_({a.cuenta_id for a in aps if a.cuenta_id}))
        .group_by(SuscripcionPush.cuenta_id)).all())
    ultima_inv = {}
    for inv in db.scalars(select(InvitacionFamilia).where(InvitacionFamilia.colegio_id == cid,
                                                          InvitacionFamilia.apoderado_id.in_(ids))
                          .order_by(InvitacionFamilia.creado_en)):
        ultima_inv[inv.apoderado_id] = inv
    ultima_entrega = {}
    for e in db.scalars(select(EntregaAviso).where(EntregaAviso.colegio_id == cid, EntregaAviso.apoderado_id.in_(ids))
                        .order_by(EntregaAviso.creado_en)):
        ultima_entrega[e.apoderado_id] = e
    return [{
        "id": a.id, "nombre": f"{a.apellidos}, {a.nombres}", "nombres": a.nombres,
        "documento": f"{a.tipo_documento} {a.numero_documento}", "celular": a.celular,
        "hijos": hijos.get(a.id, []), "estado": a.estado_acceso,
        "notificaciones": _notificaciones(a, dispositivos.get(a.cuenta_id, 0)),
        "invitacion": _invitacion(ultima_inv.get(a.id)),
        "ultimo_aviso": ({"cuerpo": e.cuerpo, "estado": e.estado, "creado_en": e.creado_en.isoformat()}
                         if (e := ultima_entrega.get(a.id)) else None),
    } for a in aps]


@router.get("/apoderados/{apoderado_id}")
def detalle(apoderado_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    """Todo lo de un padre: sus avisos (qué le llegó y qué no), enlaces, consentimiento y cambios de datos."""
    cid = s.colegio.id
    a = obtener(db, Apoderado, cid, apoderado_id, "Apoderado")
    nombres_personal = dict(db.execute(select(Usuario.id, Usuario.apellidos + ", " + Usuario.nombres)
                                       .where(Usuario.colegio_id == cid)).all())
    entregas = db.scalars(select(EntregaAviso).where(EntregaAviso.colegio_id == cid, EntregaAviso.apoderado_id == a.id)
                          .order_by(EntregaAviso.creado_en.desc()).limit(50))
    invitaciones = db.scalars(select(InvitacionFamilia).where(InvitacionFamilia.colegio_id == cid,
                                                              InvitacionFamilia.apoderado_id == a.id)
                              .order_by(InvitacionFamilia.creado_en.desc()).limit(10))
    consentimientos = db.scalars(select(ConsentimientoApoderado).where(
        ConsentimientoApoderado.colegio_id == cid, ConsentimientoApoderado.apoderado_id == a.id)
        .order_by(ConsentimientoApoderado.aceptado_en.desc()))
    cambios = db.scalars(select(CambioApoderado).where(CambioApoderado.colegio_id == cid,
                                                       CambioApoderado.apoderado_id == a.id)
                         .order_by(CambioApoderado.creado_en.desc()).limit(50))
    dispositivos = db.scalar(select(func.count()).select_from(SuscripcionPush)
                             .where(SuscripcionPush.cuenta_id == a.cuenta_id)) if a.cuenta_id else 0
    return {
        "id": a.id, "nombre": f"{a.apellidos}, {a.nombres}", "celular": a.celular, "estado": a.estado_acceso,
        "activado_en": a.activado_en.isoformat() if a.activado_en else None,
        "notificaciones": _notificaciones(a, dispositivos), "dispositivos": dispositivos,
        "avisos": [{"creado_en": e.creado_en.isoformat(), "titulo": e.titulo, "cuerpo": e.cuerpo, "estado": e.estado,
                    "dispositivos": e.dispositivos} for e in entregas],
        "invitaciones": [_invitacion(i) | {"creado_por": nombres_personal.get(i.creado_por_id)} for i in invitaciones],
        "consentimientos": [{"version": c.version, "aceptado_en": c.aceptado_en.isoformat()} for c in consentimientos],
        "cambios": [{"campo": c.campo, "antes": c.antes, "despues": c.despues, "origen": c.origen,
                     "por": nombres_personal.get(c.cambiado_por_id), "creado_en": c.creado_en.isoformat()}
                    for c in cambios],
    }


class DatosInvitacion(BaseModel):
    nuevo_pin: bool = False  # el padre olvidó su PIN: al activar crea uno nuevo


@router.post("/apoderados/{apoderado_id}/invitacion", status_code=201)
def invitar(apoderado_id: int, d: DatosInvitacion, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Crea el enlace personal. El token se devuelve una sola vez: el navegador arma el enlace y el
    botón de WhatsApp (wa.me) con el mensaje prellenado; se envía desde el WhatsApp del colegio."""
    a = obtener(db, Apoderado, s.colegio.id, apoderado_id, "Apoderado")
    if a.estado_acceso == "bloqueado":
        raise HTTPException(status.HTTP_409_CONFLICT, "El apoderado está bloqueado. Desbloquéalo primero")
    inv, token = familias.crear_invitacion(db, a, s.usuario.id, d.nuevo_pin)
    # Nunca el enlace ni el PIN: solo que se generó.
    anotar(db, s, "crear", "familias", "invitación", a.id,
           f"Enlace de activación para {a.apellidos}, {a.nombres}" + (" (PIN nuevo)" if d.nuevo_pin else ""))
    return {"token": token, "vence_en": inv.vence_en.isoformat(), "celular": a.celular, "nombres": a.nombres}


def _cambiar(db: Session, s: Sesion, apoderado_id: int, desde: tuple[str, ...], hacia: str | None,
             cerrar: bool, que: str) -> dict:
    a = obtener(db, Apoderado, s.colegio.id, apoderado_id, "Apoderado")
    if a.estado_acceso not in desde:
        raise HTTPException(status.HTTP_409_CONFLICT, "No se puede en su estado actual")
    if hacia:
        a.estado_acceso = hacia
        if hacia == "activo" and a.activado_en is None:
            a.activado_en = datetime.now(UTC)
    if cerrar:
        a.version_sesion += 1
    anotar(db, s, "editar", "familias", "cuenta de padre", a.id, f"{que}: {a.apellidos}, {a.nombres}")
    return {"id": a.id, "estado": a.estado_acceso}


@router.post("/apoderados/{apoderado_id}/aprobar")
def aprobar(apoderado_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    return _cambiar(db, s, apoderado_id, ("pendiente",), "activo", False, "Aprobó la cuenta")


@router.post("/apoderados/{apoderado_id}/bloquear")
def bloquear(apoderado_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    obtener(db, Apoderado, s.colegio.id, apoderado_id, "Apoderado")
    familias.anular_invitaciones(db, s.colegio.id, apoderado_id, "Apoderado bloqueado")
    return _cambiar(db, s, apoderado_id, ("sin_cuenta", "pendiente", "activo"), "bloqueado", True, "Bloqueó la cuenta")


@router.post("/apoderados/{apoderado_id}/desbloquear")
def desbloquear(apoderado_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    a = obtener(db, Apoderado, s.colegio.id, apoderado_id, "Apoderado")
    # Vuelve a donde estaba: sin cuenta, pendiente de aprobación o activo.
    hacia = "sin_cuenta" if a.cuenta_id is None else ("activo" if a.activado_en else "pendiente")
    return _cambiar(db, s, apoderado_id, ("bloqueado",), hacia, False, "Desbloqueó la cuenta")


@router.post("/apoderados/{apoderado_id}/cerrar-sesiones")
def cerrar_sesiones(apoderado_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    return _cambiar(db, s, apoderado_id, ("pendiente", "activo", "bloqueado", "sin_cuenta"), None, True, "Cerró las sesiones")


class DatosConfig(BaseModel):
    activacion: Literal["automatica", "aprobacion"]


@router.get("/configuracion")
def ver_config(s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    return {"activacion": familias.activacion(db, s.colegio.id)}


@router.put("/configuracion")
def editar_config(d: DatosConfig, s: Sesion = Depends(editar_reglas), db: Session = Depends(get_db)) -> dict:
    c = db.get(ConfigFamilias, s.colegio.id)
    if c is None:
        c = ConfigFamilias(colegio_id=s.colegio.id)
        db.add(c)
    c.activacion = d.activacion
    anotar(db, s, "editar", "familias", "reglas", None,
           "Activación de cuentas: " + ("automática" if c.activacion == "automatica" else "con aprobación"))
    return {"activacion": c.activacion}
