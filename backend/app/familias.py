"""Reglas de familias: invitaciones de un solo uso, cambios de contacto del
apoderado (auditados), bloqueo del PIN, PIN nuevo y el texto del consentimiento (Ley 29733)."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.fechas import LIMA, hoy_lima
from app.models import Apoderado, CambioApoderado, ColaAviso, Colegio, ConfigFamilias, CuentaFamilia, InvitacionFamilia

VIGENCIA_INVITACION = timedelta(days=7)
INTENTOS_INVITACION = 5

CONSENTIMIENTO_VERSION = "2026-11"

# PIN fallidos seguidos (en cualquier colegio) antes de bloquear el ingreso con PIN.
LIMITE_PIN = 10
BLOQUEO_PIN = timedelta(hours=24)


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


def avisar_cuenta(db: Session, ap: Apoderado, mensaje: str) -> None:
    """Aviso push sobre la cuenta. Las suscripciones son de la cuenta: le llega en todos sus celulares."""
    db.add(ColaAviso(colegio_id=ap.colegio_id, tipo="cuenta", apoderado_id=ap.id, fecha=hoy_lima(),
                     datos={"mensaje": mensaje}))


def _hora(instante: datetime) -> str:
    return instante.astimezone(LIMA).strftime("%d/%m a las %H:%M")


def pin_bloqueado_hasta(cuenta: CuentaFamilia, ahora: datetime | None = None) -> datetime | None:
    hasta = cuenta.pin_bloqueado_hasta
    return hasta if hasta and hasta > (ahora or datetime.now(UTC)) else None


def mensaje_pin_bloqueado(hasta: datetime) -> str:
    return (f"Por seguridad, el ingreso con PIN está bloqueado hasta el {_hora(hasta)}. Puedes entrar con tu "
            "huella o rostro, o pedir al colegio un enlace para crear un PIN nuevo.")


def registrar_pin_fallido(db: Session, cuenta: CuentaFamilia, colegio_id: int) -> datetime | None:
    """Suma un PIN fallido. Al llegar al límite bloquea el PIN por un día, avisa al padre y
    devuelve hasta cuándo. No hace commit."""
    db.refresh(cuenta, with_for_update=True)  # dos intentos a la vez no se pisan
    cuenta.pin_fallidos += 1
    if cuenta.pin_fallidos < LIMITE_PIN:
        return None
    ahora = datetime.now(UTC)
    cuenta.pin_fallidos, cuenta.pin_bloqueado_hasta = 0, ahora + BLOQUEO_PIN
    # El aviso sale por el colegio donde se intentó; si ahí no tiene acceso, por otro donde sí.
    destinos = db.scalars(select(Apoderado).where(Apoderado.cuenta_id == cuenta.id,
                                                  Apoderado.estado_acceso.in_(("activo", "pendiente")))).all()
    ap = next((a for a in destinos if a.colegio_id == colegio_id), destinos[0] if destinos else None)
    if ap is not None:
        avisar_cuenta(db, ap, f"Hubo {LIMITE_PIN} intentos fallidos de entrar con tu PIN. Por seguridad, el "
                              f"ingreso con PIN quedó bloqueado hasta el {_hora(cuenta.pin_bloqueado_hasta)}; con "
                              "tu huella o rostro sí puedes entrar. Si no fuiste tú, comunícate con el colegio.")
    return cuenta.pin_bloqueado_hasta


def pin_nuevo(db: Session, cuenta: CuentaFamilia, ap: Apoderado, colegio: Colegio) -> None:
    """El padre crea un PIN nuevo con un enlace de `colegio`. Se cierran sus sesiones en todos los
    colegios, se quita el bloqueo del PIN y, en los otros colegios donde estaba activo, el acceso
    queda pendiente hasta que ese colegio lo apruebe o el padre use un enlace de ese colegio:
    un enlace de un colegio no debe abrir los hijos de otro. Se le avisa en todos sus celulares."""
    cuenta.pin_fallidos, cuenta.pin_bloqueado_hasta = 0, None
    db.execute(update(Apoderado).where(Apoderado.cuenta_id == cuenta.id)
               .values(version_sesion=Apoderado.version_sesion + 1))
    otros = db.execute(select(Apoderado, Colegio.nombre).join(Colegio, Colegio.id == Apoderado.colegio_id)
                       .where(Apoderado.cuenta_id == cuenta.id, Apoderado.colegio_id != colegio.id,
                              Apoderado.estado_acceso == "activo")).all()
    for otro, _ in otros:
        otro.estado_acceso = "pendiente"
        db.add(CambioApoderado(colegio_id=otro.colegio_id, apoderado_id=otro.id, campo="acceso", antes="activo",
                               despues=f"pendiente: creó un PIN nuevo con un enlace de {colegio.nombre}",
                               origen="familia"))
    mensaje = f"Se creó un PIN nuevo para tu cuenta con un enlace de {colegio.nombre}. Se cerraron tus sesiones."
    if otros:
        nombres = ", ".join(sorted(n for _, n in otros))
        mensaje += (f" En {nombres} tu acceso queda pendiente hasta que el colegio lo apruebe o abras un "
                    "enlace de ese colegio.")
    avisar_cuenta(db, ap, mensaje + " Si no fuiste tú, comunícate con el colegio.")


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
            avisar_cuenta(db, ap, f"El celular registrado en el colegio cambió de {_oculto(antes)} a "
                                  f"{_oculto(nuevo)}. Si no lo pediste, comunícate con el colegio.")


def apoderado_por_token(db: Session, colegio_id: int, token: str) -> tuple[InvitacionFamilia, Apoderado] | None:
    inv = db.scalar(select(InvitacionFamilia).where(InvitacionFamilia.colegio_id == colegio_id,
                                                    InvitacionFamilia.token_hash == hash_token(token))
                    .with_for_update())
    if inv is None:
        return None
    return inv, db.get(Apoderado, inv.apoderado_id)

