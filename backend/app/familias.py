"""Reglas de familias: invitaciones de un solo uso, cambios de contacto del
apoderado (auditados) y el texto del consentimiento (Ley 29733)."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.fechas import hoy_lima
from app.models import Apoderado, CambioApoderado, ColaAviso, ConfigFamilias, InvitacionFamilia

VIGENCIA_INVITACION = timedelta(days=7)
INTENTOS_INVITACION = 5

CONSENTIMIENTO_VERSION = "2026-11"


def texto_consentimiento(colegio: str) -> str:
    return (
        f"Autorizo a {colegio}, titular del banco de datos, a tratar mis datos personales y los de mi hijo o hija "
        "(identidad, contacto, matrícula y asistencia) para informarme sobre su asistencia y comunicarse conmigo, "
        "conforme a la Ley 29733 de Protección de Datos Personales. Tikray Labs presta la plataforma como "
        "encargado del tratamiento y no usa estos datos para otros fines. Puedo pedir al colegio acceso, "
        "rectificación o cancelación de mis datos, y retirar esta autorización, en cualquier momento."
    )


def activacion(db: Session, colegio_id: int) -> str:
    c = db.get(ConfigFamilias, colegio_id)
    return c.activacion if c else "automatica"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def estado_invitacion(inv: InvitacionFamilia, ahora: datetime | None = None) -> str:
    ahora = ahora or datetime.now(UTC)
    if inv.usada_en:
        return "usada"
    if inv.anulada_en:
        return "anulada"
    if inv.intentos >= INTENTOS_INVITACION:
        return "bloqueada"
    if inv.vence_en <= ahora:
        return "vencida"
    return "pendiente"


def anular_invitaciones(db: Session, colegio_id: int, apoderado_id: int, motivo: str) -> int:
    r = db.execute(update(InvitacionFamilia).where(
        InvitacionFamilia.colegio_id == colegio_id, InvitacionFamilia.apoderado_id == apoderado_id,
        InvitacionFamilia.usada_en.is_(None), InvitacionFamilia.anulada_en.is_(None),
    ).values(anulada_en=datetime.now(UTC), motivo_anulacion=motivo))
    return r.rowcount


def crear_invitacion(db: Session, ap: Apoderado, creado_por_id: int | None,
                     nuevo_pin: bool = False) -> tuple[InvitacionFamilia, str]:
    """Un enlace nuevo anula los anteriores: solo sirve el último que se envió."""
    anular_invitaciones(db, ap.colegio_id, ap.id, "Se envió un enlace nuevo")
    token = secrets.token_urlsafe(32)
    inv = InvitacionFamilia(colegio_id=ap.colegio_id, apoderado_id=ap.id, token_hash=hash_token(token),
                            celular=ap.celular, nuevo_pin=nuevo_pin, creado_por_id=creado_por_id,
                            vence_en=datetime.now(UTC) + VIGENCIA_INVITACION)
    db.add(inv)
    db.flush()
    return inv, token


def _oculto(celular: str | None) -> str:
    return f"*** *** {celular[-3:]}" if celular else "ninguno"


def cambiar_contacto(db: Session, ap: Apoderado, celular: str | None, correo: str | None, origen: str,
                     usuario_id: int | None) -> None:
    """Aplica celular y correo (un dato vacío no borra el anterior) y deja registro de quién
    cambió qué. Si cambia el celular: se anula el enlace pendiente (se envió al número viejo) y,
    si el apoderado ya activó su cuenta, se le avisa."""
    for campo, nuevo in (("celular", celular), ("correo", correo)):
        antes = getattr(ap, campo)
        if not nuevo or nuevo == antes:
            continue
        setattr(ap, campo, nuevo)
        if ap.id is None:  # apoderado nuevo: no hay nada que auditar
            continue
        db.add(CambioApoderado(colegio_id=ap.colegio_id, apoderado_id=ap.id, campo=campo, antes=antes,
                               despues=nuevo, origen=origen, cambiado_por_id=usuario_id))
        if campo != "celular" or antes is None:
            continue
        anular_invitaciones(db, ap.colegio_id, ap.id, "Cambió el celular del apoderado")
        if ap.cuenta_id is not None and ap.estado_acceso in ("activo", "pendiente"):
            db.add(ColaAviso(
                colegio_id=ap.colegio_id, tipo="cuenta", apoderado_id=ap.id, fecha=hoy_lima(),
                datos={"mensaje": f"El celular registrado en el colegio cambió de {_oculto(antes)} a "
                                  f"{_oculto(nuevo)}. Si no lo pediste, comunícate con el colegio."},
            ))


def apoderado_por_token(db: Session, colegio_id: int, token: str) -> tuple[InvitacionFamilia, Apoderado] | None:
    inv = db.scalar(select(InvitacionFamilia).where(InvitacionFamilia.colegio_id == colegio_id,
                                                    InvitacionFamilia.token_hash == hash_token(token))
                    .with_for_update())
    if inv is None:
        return None
    return inv, db.get(Apoderado, inv.apoderado_id)

