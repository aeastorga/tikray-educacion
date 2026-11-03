"""Reglas del modo reunión: el QR del aula, qué alumnos admite, qué cambia cada ficha frente al
padrón y qué pasa al aprobarla. Ver app/models/reunion.py."""

import hashlib
import hmac
import secrets
from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app import familias
from app.config import get_settings
from app.models import (Alumno, AlumnoApoderado, Apoderado, CambioApoderado, ConsentimientoApoderado, FichaReunion,
                        Matricula, ReunionPadres)
from app.proteccion import LimitadorVentana

HORAS_POR_DEFECTO = 3
HORAS_MAXIMAS = 8
# Fichas vivas (no rechazadas) por alumno en una reunión: los dos apoderados y alguna corrección.
FICHAS_POR_ALUMNO = 4
# El código del celular del padre sirve hasta un rato después de cerrar la reunión, para crear su PIN.
MARGEN_ACTIVACION = timedelta(hours=2)
# Documentos de alumno equivocados: por celular (IP) y por QR. Con el tope del QR se bloquea entero.
FALLOS_REUNION = LimitadorVentana("reunion", 10, 900)
CAMPOS = ("tipo_documento", "numero_documento", "nombres", "apellidos", "celular", "correo", "parentesco")


def tope_fallos(alumnos: int) -> int:
    return max(30, 2 * alumnos)


def _firma(r: ReunionPadres) -> str:
    clave = get_settings().secret_key.encode()
    mensaje = f"reunion:{r.colegio_id}:{r.id}:{r.nonce}".encode()
    return urlsafe_b64encode(hmac.new(clave, mensaje, hashlib.sha256).digest()[:18]).decode()


def token_qr(r: ReunionPadres) -> str:
    return f"{r.id}.{_firma(r)}"


def nuevo_nonce() -> str:
    return secrets.token_hex(16)


def por_token(db: Session, colegio_id: int, token: str) -> ReunionPadres | None:
    """La reunión de este colegio cuyo QR es `token`. Un QR de otro colegio no existe aquí."""
    ident, _, firma = (token or "").partition(".")
    if not ident.isdigit() or not firma or len(ident) > 12:
        return None
    r = db.scalar(select(ReunionPadres).where(ReunionPadres.colegio_id == colegio_id,
                                              ReunionPadres.id == int(ident)))
    return r if r is not None and hmac.compare_digest(_firma(r), firma) else None


def alumnos_de(db: Session, r: ReunionPadres):
    """Consulta de los alumnos activos matriculados en la sección de la reunión."""
    return (select(Alumno)
            .join(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id, Matricula.alumno_id == Alumno.id))
            .where(Alumno.colegio_id == r.colegio_id, Matricula.seccion_id == r.seccion_id, Alumno.activo))


def cantidad_alumnos(db: Session, r: ReunionPadres) -> int:
    return db.scalar(select(func.count()).select_from(alumnos_de(db, r).subquery())) or 0


def estado(r: ReunionPadres, alumnos: int, ahora: datetime | None = None) -> str:
    ahora = ahora or datetime.now(UTC)
    if r.cerrada_en:
        return "cerrada"
    if r.vence_en <= ahora:
        return "vencida"
    if r.intentos_fallidos >= tope_fallos(alumnos):
        return "bloqueada"
    return "abierta"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def nuevo_token_ficha(ficha_id: int) -> str:
    return f"{ficha_id}.{secrets.token_urlsafe(24)}"


# --- Cambios frente al padrón -------------------------------------------------------------

def _registrado(db: Session, colegio_id: int, alumno_id: int, persona: dict) -> tuple[Apoderado | None, str | None]:
    """El apoderado del padrón con ese documento (en el colegio) y su parentesco con el alumno, si ya lo es."""
    ap = db.scalar(select(Apoderado).where(Apoderado.colegio_id == colegio_id,
                                           Apoderado.tipo_documento == persona["tipo_documento"],
                                           Apoderado.numero_documento == persona["numero_documento"]))
    if ap is None:
        return None, None
    vinculo = db.scalar(select(AlumnoApoderado).where(
        AlumnoApoderado.colegio_id == colegio_id, AlumnoApoderado.alumno_id == alumno_id,
        AlumnoApoderado.apoderado_id == ap.id))
    return ap, vinculo.parentesco if vinculo else None


def cambios_persona(db: Session, colegio_id: int, alumno_id: int, persona: dict | None) -> dict | None:
    """Qué es nuevo o distinto frente al padrón: {estado: nuevo|nuevo_vinculo|registrado, cambios: {campo: [antes, después]}}."""
    if not persona:
        return None
    ap, parentesco = _registrado(db, colegio_id, alumno_id, persona)
    if ap is None:
        return {"estado": "nuevo", "apoderado_id": None, "cambios": {}, "con_cuenta": False}
    actual = {"nombres": ap.nombres, "apellidos": ap.apellidos, "celular": ap.celular, "correo": ap.correo,
              "parentesco": parentesco}
    cambios = {c: [actual[c], persona.get(c)] for c in actual
               if persona.get(c) and (persona.get(c) or "") != (actual[c] or "")}
    return {"estado": "registrado" if parentesco else "nuevo_vinculo", "apoderado_id": ap.id, "cambios": cambios,
            "con_cuenta": ap.estado_acceso in ("activo", "pendiente")}


# --- Aprobar -------------------------------------------------------------------------------

def _aplicar_persona(db: Session, ficha: FichaReunion, persona: dict, usuario_id: int,
                     tocar_contacto: bool) -> tuple[Apoderado, list[str]]:
    """Crea o actualiza el apoderado y lo une al alumno. Devuelve también lo que no se aplicó y por qué."""
    cid, notas = ficha.colegio_id, []
    ap, parentesco = _registrado(db, cid, ficha.alumno_id, persona)
    if ap is None:
        ap = Apoderado(colegio_id=cid, tipo_documento=persona["tipo_documento"],
                       numero_documento=persona["numero_documento"], nombres=persona["nombres"],
                       apellidos=persona["apellidos"], celular=persona.get("celular"), correo=persona.get("correo"))
        db.add(ap)
        db.flush()
        db.add(CambioApoderado(colegio_id=cid, apoderado_id=ap.id, campo="alta", antes=None,
                               despues=f"ficha de la reunión #{ficha.reunion_id}", origen="reunion",
                               cambiado_por_id=usuario_id))
    else:
        for campo in ("nombres", "apellidos"):
            nuevo = persona.get(campo)
            if nuevo and nuevo != getattr(ap, campo):
                db.add(CambioApoderado(colegio_id=cid, apoderado_id=ap.id, campo=campo, antes=getattr(ap, campo),
                                       despues=nuevo, origen="reunion", cambiado_por_id=usuario_id))
                setattr(ap, campo, nuevo)
        if tocar_contacto:
            familias.cambiar_contacto(db, ap, persona.get("celular"), persona.get("correo"), "reunion", usuario_id)
        elif (persona.get("celular") and persona["celular"] != ap.celular) or \
                (persona.get("correo") and persona["correo"] != ap.correo):
            notas.append(f"No se cambió el contacto de {ap.nombres}: tiene cuenta propia y debe pedirlo en persona.")
    if parentesco is None:
        db.add(AlumnoApoderado(colegio_id=cid, alumno_id=ficha.alumno_id, apoderado_id=ap.id,
                               parentesco=persona.get("parentesco") or "Apoderado"))
    elif persona.get("parentesco") and persona["parentesco"] != parentesco:
        vinculo = db.scalar(select(AlumnoApoderado).where(
            AlumnoApoderado.colegio_id == cid, AlumnoApoderado.alumno_id == ficha.alumno_id,
            AlumnoApoderado.apoderado_id == ap.id))
        vinculo.parentesco = persona["parentesco"]
    db.flush()
    return ap, notas


def aprobar(db: Session, ficha: FichaReunion, usuario_id: int) -> tuple[Apoderado, list[str]]:
    """Pasa la ficha al padrón: el que la llenó (con su consentimiento, de la fecha en que lo dio) y el
    otro apoderado. El contacto del otro no se toca si ya tiene cuenta: no lo pidió él. No hace commit."""
    ap, notas = _aplicar_persona(db, ficha, ficha.datos["apoderado"], usuario_id, tocar_contacto=True)
    if ap.estado_acceso == "bloqueado":
        raise ValueError("Ese apoderado está bloqueado en el colegio")
    db.add(ConsentimientoApoderado(colegio_id=ficha.colegio_id, apoderado_id=ap.id,
                                   version=ficha.consentimiento_version, aceptado_en=ficha.actualizado_en,
                                   ip=ficha.ip))
    ficha.apoderado_id = ap.id
    if ficha.datos.get("otro"):
        otro, _ = _registrado(db, ficha.colegio_id, ficha.alumno_id, ficha.datos["otro"])
        con_cuenta = otro is not None and otro.cuenta_id is not None
        otro, mas = _aplicar_persona(db, ficha, ficha.datos["otro"], usuario_id, tocar_contacto=not con_cuenta)
        ficha.otro_apoderado_id = otro.id
        notas += mas
    ficha.estado, ficha.revisado_por_id, ficha.revisado_en = "aprobada", usuario_id, datetime.now(UTC)
    return ap, notas
