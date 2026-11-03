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
                        Matricula, ReunionPadres, Usuario)
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


def tiene_cuenta(ap: Apoderado | None) -> bool:
    """Con cuenta propia, su celular y correo solo los cambia él en persona en secretaría, nunca una
    ficha: ni la que llena otro, ni la suya (alguien con su DNI y el del hijo podría desviar sus avisos)."""
    return ap is not None and ap.cuenta_id is not None


def cambios_persona(db: Session, colegio_id: int, alumno_id: int, persona: dict | None) -> dict | None:
    """Qué es nuevo o distinto frente al padrón: {estado: nuevo|nuevo_vinculo|registrado, cambios: {campo: [antes, después]}}.
    Con cuenta propia, el celular y el correo distintos van en `sin_aplicar`: no se cambian al aprobar."""
    if not persona:
        return None
    ap, parentesco = _registrado(db, colegio_id, alumno_id, persona)
    if ap is None:
        return {"estado": "nuevo", "apoderado_id": None, "cambios": {}, "sin_aplicar": {}, "con_cuenta": False}
    actual = {"nombres": ap.nombres, "apellidos": ap.apellidos, "celular": ap.celular, "correo": ap.correo,
              "parentesco": parentesco}
    cambios = {c: [actual[c], persona.get(c)] for c in actual
               if persona.get(c) and (persona.get(c) or "") != (actual[c] or "")}
    sin_aplicar = {c: cambios.pop(c) for c in ("celular", "correo") if c in cambios and tiene_cuenta(ap)}
    return {"estado": "registrado" if parentesco else "nuevo_vinculo", "apoderado_id": ap.id, "cambios": cambios,
            "sin_aplicar": sin_aplicar, "con_cuenta": tiene_cuenta(ap)}


def requiere_verificacion(db: Session, ficha: FichaReunion) -> bool:
    """El tutor debe ver el DNI en persona antes de aprobar si la ficha suma un apoderado al alumno
    (nuevo en el padrón, o ya registrado pero no como apoderado de este alumno) o cambia un celular."""
    for persona in (ficha.datos["apoderado"], ficha.datos.get("otro")):
        c = cambios_persona(db, ficha.colegio_id, ficha.alumno_id, persona)
        if c and (c["estado"] != "registrado" or "celular" in c["cambios"]):
            return True
    return False


class FaltaVerificar(Exception):
    pass


class Bloqueado(Exception):
    pass


# --- Aprobar -------------------------------------------------------------------------------

def _aplicar_persona(db: Session, ficha: FichaReunion, persona: dict, usuario_id: int,
                     verificado: str | None) -> tuple[Apoderado, list[str]]:
    """Crea o actualiza el apoderado y lo une al alumno. Devuelve también lo que no se aplicó y por qué.
    `verificado`: texto de quién vio el DNI en persona, que queda en el registro de cambios."""
    cid, notas = ficha.colegio_id, []
    ap, parentesco = _registrado(db, cid, ficha.alumno_id, persona)
    nuevo_vinculo = parentesco is None
    cambia_celular = False
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
        distinto = (persona.get("celular") and persona["celular"] != ap.celular) or \
            (persona.get("correo") and persona["correo"] != ap.correo)
        if tiene_cuenta(ap):
            if distinto:
                notas.append(f"No se cambió el celular ni el correo de {ap.nombres}: tiene cuenta propia; "
                             "debe pedirlo en persona en secretaría.")
        else:
            cambia_celular = bool(persona.get("celular")) and persona["celular"] != ap.celular
            familias.cambiar_contacto(db, ap, persona.get("celular"), persona.get("correo"), "reunion", usuario_id)
    if parentesco is None:
        db.add(AlumnoApoderado(colegio_id=cid, alumno_id=ficha.alumno_id, apoderado_id=ap.id,
                               parentesco=persona.get("parentesco") or "Apoderado"))
    elif persona.get("parentesco") and persona["parentesco"] != parentesco:
        vinculo = db.scalar(select(AlumnoApoderado).where(
            AlumnoApoderado.colegio_id == cid, AlumnoApoderado.alumno_id == ficha.alumno_id,
            AlumnoApoderado.apoderado_id == ap.id))
        vinculo.parentesco = persona["parentesco"]
    if verificado and (nuevo_vinculo or cambia_celular):
        db.add(CambioApoderado(colegio_id=cid, apoderado_id=ap.id, campo="dni_verificado", antes=None,
                               despues=verificado, origen="reunion", cambiado_por_id=usuario_id))
    db.flush()
    return ap, notas


def aprobar(db: Session, ficha: FichaReunion, usuario: Usuario, dni_verificado: bool) -> tuple[Apoderado, list[str]]:
    """Pasa la ficha al padrón: el que la llenó (con su consentimiento, de la fecha en que lo dio) y el
    otro apoderado. A quien tiene cuenta propia no se le cambia el contacto. Si suma un apoderado o
    cambia un celular, exige que el tutor haya visto el DNI en persona y lo deja registrado. No hace commit."""
    if requiere_verificacion(db, ficha) and not dni_verificado:
        raise FaltaVerificar("Esta ficha suma un apoderado o cambia un celular: marca «Verifiqué su DNI en "
                             "persona» después de ver su documento")
    principal, _ = _registrado(db, ficha.colegio_id, ficha.alumno_id, ficha.datos["apoderado"])
    if principal is not None and principal.estado_acceso == "bloqueado":
        raise Bloqueado("Ese apoderado está bloqueado en el colegio")
    ahora = datetime.now(UTC)
    nombre = f"{usuario.nombres} {usuario.apellidos}"
    verificado = None
    if dni_verificado:
        ficha.dni_verificado_por_id, ficha.dni_verificado_por, ficha.dni_verificado_en = usuario.id, nombre, ahora
        verificado = f"DNI visto en persona por {nombre} (reunión #{ficha.reunion_id})"[:254]
    ap, notas = _aplicar_persona(db, ficha, ficha.datos["apoderado"], usuario.id, verificado)
    db.add(ConsentimientoApoderado(colegio_id=ficha.colegio_id, apoderado_id=ap.id,
                                   version=ficha.consentimiento_version, aceptado_en=ficha.actualizado_en,
                                   ip=ficha.ip))
    ficha.apoderado_id = ap.id
    if ficha.datos.get("otro"):
        otro, mas = _aplicar_persona(db, ficha, ficha.datos["otro"], usuario.id, verificado)
        ficha.otro_apoderado_id = otro.id
        notas += mas
    ficha.estado, ficha.revisado_por_id, ficha.revisado_en = "aprobada", usuario.id, ahora
    return ap, notas
