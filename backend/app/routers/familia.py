"""Espacio de la familia: activación con enlace de un solo uso, ingreso con PIN
o passkey, hijos con su asistencia del día, avisos recibidos y notificaciones push.

Sin registro abierto: solo entra quien el colegio invitó, con el documento del
alumno y el suyo. La cuenta es global (una por documento) y une a los hijos de
todos los colegios donde está activa; el acceso a cada colegio lo decide ese colegio.
"""

import json
import re
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

from app import asistencia, familias
from app.config import get_settings
from app.db import get_db
from app.deps import SesionFamilia, _host, colegio_del_host, familia_sesion
from app.fechas import hoy_lima
from app.models import (Alumno, AlumnoApoderado, AnioEscolar, Apoderado, AsistenciaAlumno, Colegio,
                        ConsentimientoApoderado, CuentaFamilia, EntregaAviso, Grado, InvitacionFamilia, Marcacion,
                        Matricula, PasskeyFamilia, RetoUsado, Seccion, SuscripcionPush, Turno)
from app.proteccion import FALLOS_IP, ip_cliente, permitir_intento, registrar_fallo
from app.routers.estructura import es_dia_lectivo
from app.seguridad import emitir_token, hashear_clave, leer_token, verificar_clave, verificar_clave_o_simular

publico = APIRouter(prefix="/familia", tags=["familia"])
privado = APIRouter(prefix="/familia", tags=["familia"])

MENSAJES_ENLACE = {
    "usada": "Este enlace ya se usó. Si ya activaste tu cuenta, entra con tu documento y tu PIN.",
    "anulada": "Este enlace ya no es válido: el colegio envió uno nuevo o cambió tus datos. Pide uno nuevo.",
    "bloqueada": "El enlace se bloqueó por demasiados intentos. Pide uno nuevo al colegio.",
    "vencida": "El enlace venció. Pide uno nuevo al colegio.",
}


def _doc(texto: str) -> str:
    return re.sub(r"[\s.\-]", "", texto or "").upper()


def _pin_valido(pin: str | None) -> str:
    if not pin or not re.fullmatch(r"\d{6}", pin):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El PIN debe tener 6 números")
    if len(set(pin)) == 1 or pin in "0123456789" or pin in "9876543210":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Ese PIN es muy fácil de adivinar. Evita números repetidos o seguidos")
    return pin


def _comprobar_pin(db: Session, cuenta: CuentaFamilia, pin: str, colegio: Colegio) -> bool:
    """Verifica el PIN llevando la cuenta de fallidos en la base (vale en todos los colegios y
    servidores). Bloqueado, o recién bloqueado por este intento: 429. Un fallido queda guardado."""
    if hasta := familias.pin_bloqueado_hasta(cuenta):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, familias.mensaje_pin_bloqueado(hasta))
    if verificar_clave(pin, cuenta.pin_hash):
        cuenta.pin_fallidos = 0
        return True
    hasta = familias.registrar_pin_fallido(db, cuenta, colegio.id)
    db.commit()
    if hasta:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, familias.mensaje_pin_bloqueado(hasta))
    return False


def _token(colegio: Colegio, cuenta: CuentaFamilia, ap: Apoderado) -> dict:
    t = emitir_token("familia", cuenta.id, ap.version_sesion, get_settings().token_familia_minutos,
                     col=colegio.id, apo=ap.id)
    return {"token": t, "estado": ap.estado_acceso}


# --- Activación -----------------------------------------------------------------

class DatosEnlace(BaseModel):
    token: str = Field(min_length=20, max_length=100)
    documento_alumno: str = Field(min_length=1, max_length=20)
    documento_apoderado: str = Field(min_length=1, max_length=20)


class Activacion(DatosEnlace):
    acepto: bool
    pin: str | None = None  # el nuevo, si aún no tiene cuenta (o el colegio pidió uno nuevo)
    pin_actual: str | None = None  # si ya tiene cuenta por otro colegio


def _verificar_enlace(db: Session, colegio: Colegio, d: DatosEnlace, request: Request):
    ip = f"familia:{ip_cliente(request)}"
    if not FALLOS_IP.hay_cupo(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos. Espera unos minutos")
    res = familias.apoderado_por_token(db, colegio.id, d.token)
    if res is None:
        FALLOS_IP.registrar(ip)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enlace no válido. Revisa que lo hayas abierto completo")
    inv, ap = res
    estado = familias.estado_invitacion(inv)
    if estado != "pendiente":
        raise HTTPException(status.HTTP_410_GONE, MENSAJES_ENLACE[estado])
    hijo = db.scalar(select(Alumno.id).join(
        AlumnoApoderado, and_(AlumnoApoderado.colegio_id == Alumno.colegio_id, AlumnoApoderado.alumno_id == Alumno.id))
        .where(Alumno.colegio_id == colegio.id, AlumnoApoderado.apoderado_id == ap.id, Alumno.activo,
               Alumno.numero_documento == _doc(d.documento_alumno)))
    if hijo is None or _doc(d.documento_apoderado) != ap.numero_documento:
        FALLOS_IP.registrar(ip)
        inv.intentos += 1
        db.commit()
        quedan = familias.INTENTOS_INVITACION - inv.intentos
        if quedan <= 0:
            raise HTTPException(status.HTTP_410_GONE, MENSAJES_ENLACE["bloqueada"])
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Los documentos no coinciden con los registrados en el "
                            f"colegio. Te {'queda 1 intento' if quedan == 1 else f'quedan {quedan} intentos'}.")
    if ap.estado_acceso == "bloqueado":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu acceso está bloqueado. Comunícate con el colegio")
    return inv, ap


def _cuenta_de(db: Session, ap: Apoderado) -> CuentaFamilia | None:
    return db.scalar(select(CuentaFamilia).where(CuentaFamilia.tipo_documento == ap.tipo_documento,
                                                 CuentaFamilia.numero_documento == ap.numero_documento))


@publico.post("/activacion/revisar")
def revisar_enlace(d: DatosEnlace, request: Request, colegio: Colegio = Depends(colegio_del_host),
                   db: Session = Depends(get_db)) -> dict:
    """Primer paso: el enlace sirve y los documentos coinciden. No activa nada."""
    inv, ap = _verificar_enlace(db, colegio, d, request)
    db.commit()  # suelta el FOR UPDATE
    return {"nombres": ap.nombres, "colegio": colegio.nombre,
            "pide_pin_actual": _cuenta_de(db, ap) is not None and not inv.nuevo_pin,
            "consentimiento": {"version": familias.CONSENTIMIENTO_VERSION,
                               "texto": familias.texto_consentimiento(colegio.nombre)}}


@publico.post("/activacion/completar")
def completar_activacion(d: Activacion, request: Request, colegio: Colegio = Depends(colegio_del_host),
                         db: Session = Depends(get_db)) -> dict:
    inv, ap = _verificar_enlace(db, colegio, d, request)
    if not d.acepto:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Para activar tu cuenta debes aceptar el tratamiento de datos")
    resultado = activar(db, colegio, inv, ap, d.pin, d.pin_actual, request)
    db.add(ConsentimientoApoderado(colegio_id=colegio.id, apoderado_id=ap.id,
                                   version=familias.CONSENTIMIENTO_VERSION, ip=ip_cliente(request)[:45]))
    db.commit()
    return resultado


def activar(db: Session, colegio: Colegio, inv: InvitacionFamilia, ap: Apoderado, pin: str | None,
            pin_actual: str | None, request: Request) -> dict:
    """Crea la cuenta (o la une, si ya tiene una por otro colegio) y marca el enlace como usado.
    Lo usan el enlace personal y la ficha aprobada en la reunión. No guarda el consentimiento ni hace commit
    (salvo el del PIN fallido)."""
    ahora = datetime.now(UTC)
    cuenta = _cuenta_de(db, ap)
    if cuenta is not None and not inv.nuevo_pin:
        # Ya tiene cuenta (por otro colegio): demuestra que es suya con su PIN, no lo reemplaza.
        if not _comprobar_pin(db, cuenta, pin_actual or "", colegio):
            FALLOS_IP.registrar(f"familia:{ip_cliente(request)}")
            inv.intentos += 1
            db.commit()
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "El PIN no es correcto. Si lo olvidaste, pide al colegio un enlace para crear uno nuevo")
    elif cuenta is not None:
        cuenta.pin_hash = hashear_clave(_pin_valido(pin))
        familias.pin_nuevo(db, cuenta, ap, colegio)
    else:
        cuenta = CuentaFamilia(tipo_documento=ap.tipo_documento, numero_documento=ap.numero_documento,
                               pin_hash=hashear_clave(_pin_valido(pin)))
        db.add(cuenta)
        db.flush()
    db.refresh(ap)
    ap.cuenta_id = cuenta.id
    if ap.estado_acceso != "activo":
        # Quien el colegio ya aprobó antes (p. ej. quedó pendiente por un PIN nuevo creado en otro
        # colegio) vuelve a activo con el enlace de este colegio; también quien el tutor aprobó en persona.
        automatica = familias.activacion(db, colegio.id) == "automatica"
        ap.estado_acceso = "activo" if automatica or ap.activado_en or inv.presencial else "pendiente"
    if ap.estado_acceso == "activo" and ap.activado_en is None:
        ap.activado_en = ahora
    inv.usada_en = ahora
    return _token(colegio, cuenta, ap)


# --- Ingreso --------------------------------------------------------------------

class IngresoPin(BaseModel):
    documento: str = Field(min_length=1, max_length=20)
    pin: str = Field(min_length=1, max_length=20)


def _acceso_aqui(db: Session, colegio: Colegio, cuenta: CuentaFamilia) -> Apoderado:
    ap = db.scalar(select(Apoderado).where(Apoderado.colegio_id == colegio.id, Apoderado.cuenta_id == cuenta.id))
    if ap is None or ap.estado_acceso == "sin_cuenta":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu cuenta aún no está activada en este colegio. "
                            "Pide tu enlace personal al colegio")
    if ap.estado_acceso == "bloqueado":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu acceso está bloqueado. Comunícate con el colegio")
    return ap


@publico.post("/ingreso")
def ingresar(d: IngresoPin, request: Request, colegio: Colegio = Depends(colegio_del_host),
             db: Session = Depends(get_db)) -> dict:
    doc = _doc(d.documento)
    # El PIN es corto: 5 intentos por documento y 50 por IP cada 15 minutos.
    cuenta_lim, ip = f"familia:{doc}", f"familia:{ip_cliente(request)}"
    if not permitir_intento(cuenta_lim, ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos. Espera 15 minutos")
    cuentas = db.scalars(select(CuentaFamilia).where(CuentaFamilia.numero_documento == doc)).all()
    # Además del límite por ventana (tabla intento_fallido), el PIN se bloquea un día tras 10 fallidos seguidos (en la base).
    abiertas = [c for c in cuentas if not familias.pin_bloqueado_hasta(c)]
    if cuentas and not abiertas:
        hasta = min(c.pin_bloqueado_hasta for c in cuentas)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, familias.mensaje_pin_bloqueado(hasta))
    cuenta = next((c for c in abiertas if verificar_clave(d.pin, c.pin_hash)), None)
    if cuenta is None:
        if not cuentas:
            verificar_clave_o_simular(d.pin, None)
        registrar_fallo(cuenta_lim, ip)
        bloqueos = [h for c in abiertas if (h := familias.registrar_pin_fallido(db, c, colegio.id))]
        db.commit()
        if bloqueos:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, familias.mensaje_pin_bloqueado(bloqueos[0]))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Documento o PIN incorrectos")
    cuenta.pin_fallidos = 0
    db.commit()
    return _token(colegio, cuenta, _acceso_aqui(db, colegio, cuenta))


# --- Passkeys (huella o rostro del celular) ---------------------------------------

def _origen(request: Request) -> tuple[str, str]:
    """(rp_id, origen). La passkey queda atada a la dirección del colegio por donde se registró."""
    host = _host(request)
    origen = request.headers.get("origin", "")
    if urlparse(origen).hostname != host:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Origen no válido")
    return host, origen


def _reto(uso: str, sub: int, colegio: Colegio, reto: bytes) -> str:
    return emitir_token("reto", sub, 0, 5, uso=uso, col=colegio.id, reto=bytes_to_base64url(reto))


def _leer_reto(db: Session, token: str, uso: str, colegio: Colegio) -> dict:
    """El reto firmado, que además sirve una sola vez: se gasta al presentarlo, salga bien o no."""
    datos = leer_token("reto", token)
    if datos is None or datos.get("uso") != uso or datos.get("col") != colegio.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El pedido venció. Inténtalo de nuevo")
    ahora = datetime.now(UTC)
    db.execute(delete(RetoUsado).where(RetoUsado.vence_en < ahora))
    nuevo = db.scalar(insert(RetoUsado).values(reto=datos["reto"], colegio_id=colegio.id,
                                               vence_en=datetime.fromtimestamp(datos["exp"], UTC))
                      .on_conflict_do_nothing().returning(RetoUsado.reto))
    db.commit()  # gastado aunque la verificación falle después
    if nuevo is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este pedido ya se usó. Inténtalo de nuevo")
    return datos


class Credencial(BaseModel):
    credencial: dict
    reto: str = Field(max_length=2000)


@privado.post("/passkey/opciones-registro")
def opciones_registro(request: Request, s: SesionFamilia = Depends(familia_sesion),
                      db: Session = Depends(get_db)) -> dict:
    rp_id, _ = _origen(request)
    existentes = db.scalars(select(PasskeyFamilia).where(PasskeyFamilia.cuenta_id == s.cuenta.id,
                                                         PasskeyFamilia.rp_id == rp_id))
    o = generate_registration_options(
        rp_id=rp_id, rp_name=s.colegio.nombre, user_id=str(s.cuenta.id).encode(),
        user_name=s.cuenta.numero_documento, user_display_name=f"{s.apoderado.nombres} {s.apoderado.apellidos}",
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credencial_id))
                             for p in existentes])
    return {"opciones": json.loads(options_to_json(o)), "reto": _reto("registro", s.cuenta.id, s.colegio, o.challenge)}


@privado.post("/passkey/registro", status_code=201)
def registrar_passkey(d: Credencial, request: Request, s: SesionFamilia = Depends(familia_sesion),
                      db: Session = Depends(get_db)) -> dict:
    rp_id, origen = _origen(request)
    reto = _leer_reto(db, d.reto, "registro", s.colegio)
    if int(reto["sub"]) != s.cuenta.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El pedido no es de esta cuenta")
    try:
        v = verify_registration_response(credential=d.credencial, expected_challenge=base64url_to_bytes(reto["reto"]),
                                         expected_rp_id=rp_id, expected_origin=origen,
                                         require_user_verification=True)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se pudo registrar la huella. Inténtalo de nuevo") from None
    db.add(PasskeyFamilia(cuenta_id=s.cuenta.id, credencial_id=bytes_to_base64url(v.credential_id),
                          clave_publica=v.credential_public_key, contador=v.sign_count, rp_id=rp_id))
    db.commit()
    return {"ok": True}


@publico.post("/passkey/opciones-ingreso")
def opciones_ingreso(request: Request, colegio: Colegio = Depends(colegio_del_host)) -> dict:
    rp_id, _ = _origen(request)
    o = generate_authentication_options(rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED)
    return {"opciones": json.loads(options_to_json(o)), "reto": _reto("ingreso", 0, colegio, o.challenge)}


@publico.post("/passkey/ingreso")
def ingresar_passkey(d: Credencial, request: Request, colegio: Colegio = Depends(colegio_del_host),
                     db: Session = Depends(get_db)) -> dict:
    rp_id, origen = _origen(request)
    ip = f"familia:{ip_cliente(request)}"
    if not FALLOS_IP.hay_cupo(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos. Espera unos minutos")
    reto = _leer_reto(db, d.reto, "ingreso", colegio)
    pk = db.scalar(select(PasskeyFamilia).where(PasskeyFamilia.credencial_id == str(d.credencial.get("id", "")),
                                                PasskeyFamilia.rp_id == rp_id))
    try:
        if pk is None:
            raise ValueError("desconocida")
        v = verify_authentication_response(
            credential=d.credencial, expected_challenge=base64url_to_bytes(reto["reto"]), expected_rp_id=rp_id,
            expected_origin=origen, credential_public_key=pk.clave_publica, credential_current_sign_count=pk.contador,
            require_user_verification=True)
    except Exception:
        FALLOS_IP.registrar(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No se reconoció la huella. Entra con tu PIN") from None
    pk.contador, pk.usado_en = v.new_sign_count, datetime.now(UTC)
    cuenta = db.get(CuentaFamilia, pk.cuenta_id)
    ap = _acceso_aqui(db, colegio, cuenta)
    db.commit()
    return _token(colegio, cuenta, ap)


# --- Con sesión --------------------------------------------------------------------

@privado.get("/yo")
def yo(request: Request, s: SesionFamilia = Depends(familia_sesion), db: Session = Depends(get_db)) -> dict:
    ap = s.apoderado
    tiene_passkey = db.scalar(select(PasskeyFamilia.id).where(PasskeyFamilia.cuenta_id == s.cuenta.id,
                                                              PasskeyFamilia.rp_id == _host(request))) is not None
    return {"nombres": ap.nombres, "apellidos": ap.apellidos, "estado": ap.estado_acceso,
            "tiene_passkey": tiene_passkey, "push_clave": get_settings().vapid_clave_publica or None}


def _apoderados_activos(db: Session, cuenta_id: int):
    """Los apoderados de esta persona en los colegios donde está activa (y el colegio, disponible)."""
    hoy = hoy_lima()
    filas = db.execute(select(Apoderado, Colegio).join(Colegio, Colegio.id == Apoderado.colegio_id)
                       .where(Apoderado.cuenta_id == cuenta_id, Apoderado.estado_acceso == "activo")).all()
    return [(ap, c) for ap, c in filas if c.disponible(hoy)]


@privado.get("/hijos")
def hijos(s: SesionFamilia = Depends(familia_sesion), db: Session = Depends(get_db)) -> dict:
    """La tarjeta en vivo de cada hijo: cómo va su día. De todos los colegios donde la cuenta está activa."""
    hoy = hoy_lima()
    inicio_mes = hoy.replace(day=1)
    tarjetas = []
    for ap, colegio in _apoderados_activos(db, s.cuenta.id):
        anio = (select(AnioEscolar.id).where(AnioEscolar.colegio_id == colegio.id, AnioEscolar.activo)
                .scalar_subquery())
        filas = db.execute(
            select(Alumno, Grado.nombre, Seccion.nombre, AsistenciaAlumno, Turno.hora_salida)
            .select_from(AlumnoApoderado)
            .join(Alumno, and_(Alumno.colegio_id == AlumnoApoderado.colegio_id, Alumno.id == AlumnoApoderado.alumno_id))
            .outerjoin(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id, Matricula.alumno_id == Alumno.id,
                                       Matricula.anio_id == anio))
            .outerjoin(Seccion, and_(Seccion.colegio_id == Matricula.colegio_id, Seccion.id == Matricula.seccion_id))
            .outerjoin(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
            .outerjoin(Turno, and_(Turno.colegio_id == Seccion.colegio_id, Turno.id == Seccion.turno_id))
            .outerjoin(AsistenciaAlumno, and_(AsistenciaAlumno.colegio_id == Alumno.colegio_id,
                                              AsistenciaAlumno.alumno_id == Alumno.id, AsistenciaAlumno.fecha == hoy))
            .where(AlumnoApoderado.colegio_id == colegio.id, AlumnoApoderado.apoderado_id == ap.id, Alumno.activo)
            .order_by(Alumno.nombres)).all()
        ids = [a.id for a, *_ in filas]
        # Tardanzas del mes y la puerta (equipo) por donde entró hoy, en dos consultas por colegio.
        tardanzas = dict(db.execute(
            select(AsistenciaAlumno.alumno_id, func.count())
            .where(AsistenciaAlumno.colegio_id == colegio.id, AsistenciaAlumno.alumno_id.in_(ids),
                   AsistenciaAlumno.fecha.between(inicio_mes, hoy), AsistenciaAlumno.estado == "tarde")
            .group_by(AsistenciaAlumno.alumno_id)).all()) if ids else {}
        puertas = {(m.alumno_id, m.momento): m.equipo for m in db.scalars(
            select(Marcacion).where(Marcacion.colegio_id == colegio.id, Marcacion.alumno_id.in_(ids),
                                    Marcacion.fecha == hoy, Marcacion.resultado != "duplicada"))} if ids else {}
        lectivo = es_dia_lectivo(db, colegio.id, hoy)
        for a, grado, seccion, dia, hora_salida in filas:
            tarjetas.append({
                "alumno_id": a.id, "colegio": colegio.nombre, "nombres": a.nombres, "apellidos": a.apellidos,
                "seccion": f"{grado} {seccion}" if seccion else None, "lectivo": lectivo,
                "estado": dia.estado if dia else None, "entrada": asistencia.hora(dia.entrada) if dia else None,
                "salida": asistencia.hora(dia.salida) if dia else None,
                "minutos_tarde": dia.minutos_tarde if dia else 0,
                "puerta": puertas.get((a.id, dia.entrada)) if dia and dia.entrada else None,
                "hora_salida": hora_salida.strftime("%H:%M") if hora_salida else None,
                "tardanzas_mes": tardanzas.get(a.id, 0),
            })
    pendientes = db.scalars(select(Colegio.nombre).join(Apoderado, Apoderado.colegio_id == Colegio.id)
                            .where(Apoderado.cuenta_id == s.cuenta.id, Apoderado.estado_acceso == "pendiente")).all()
    return {"fecha": hoy.isoformat(), "hijos": tarjetas, "pendientes_aprobacion": pendientes}


@privado.get("/hijos/{alumno_id}/asistencia")
def asistencia_del_mes(alumno_id: int, mes: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
                       s: SesionFamilia = Depends(familia_sesion), db: Session = Depends(get_db)) -> dict:
    """Los días del mes de un hijo. Solo de un alumno vinculado a esta cuenta en un colegio donde está activa."""
    activos = {ap.id: c for ap, c in _apoderados_activos(db, s.cuenta.id)}
    vinculo = db.execute(select(AlumnoApoderado.colegio_id).where(
        AlumnoApoderado.apoderado_id.in_(activos), AlumnoApoderado.alumno_id == alumno_id)).first() if activos else None
    if vinculo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alumno no encontrado")
    cid = vinculo[0]
    hoy = hoy_lima()
    inicio = date.fromisoformat(f"{mes}-01") if mes else hoy.replace(day=1)
    fin = min((inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1), hoy)
    dias = db.scalars(select(AsistenciaAlumno).where(
        AsistenciaAlumno.colegio_id == cid, AsistenciaAlumno.alumno_id == alumno_id,
        AsistenciaAlumno.fecha.between(inicio, fin)).order_by(AsistenciaAlumno.fecha.desc())).all()
    conteo = {k: 0 for k in ("presente", "tarde", "falta", "justificada")}
    for d in dias:
        conteo[d.estado] = conteo.get(d.estado, 0) + 1
    return {
        "mes": inicio.strftime("%Y-%m"), "resumen": conteo,
        "dias": [{"fecha": d.fecha.isoformat(), "estado": d.estado, "entrada": asistencia.hora(d.entrada),
                  "salida": asistencia.hora(d.salida), "minutos_tarde": d.minutos_tarde} for d in dias],
    }


@privado.get("/avisos")
def avisos(s: SesionFamilia = Depends(familia_sesion), db: Session = Depends(get_db)) -> list[dict]:
    ids = [ap.id for ap, _ in _apoderados_activos(db, s.cuenta.id)]
    filas = db.scalars(select(EntregaAviso).where(EntregaAviso.apoderado_id.in_(ids))
                       .order_by(EntregaAviso.creado_en.desc()).limit(50)) if ids else []
    return [{"id": e.id, "titulo": e.titulo, "cuerpo": e.cuerpo, "creado_en": e.creado_en.isoformat(),
             "estado": e.estado} for e in filas]


class Suscripcion(BaseModel):
    endpoint: str = Field(pattern=r"^https://", max_length=2000)
    keys: dict[str, str]


@privado.post("/push/suscripcion", status_code=201)
def suscribir(d: Suscripcion, s: SesionFamilia = Depends(familia_sesion), db: Session = Depends(get_db)) -> dict:
    p256dh, auth = d.keys.get("p256dh", ""), d.keys.get("auth", "")
    if not (0 < len(p256dh) <= 200 and 0 < len(auth) <= 100):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Suscripción no válida")
    sus = db.scalar(select(SuscripcionPush).where(SuscripcionPush.endpoint == d.endpoint))
    if sus is None:
        sus = SuscripcionPush(endpoint=d.endpoint)
        db.add(sus)
    # Mismo navegador, otra persona (o el mismo con otro colegio): queda con quien entró ahora.
    sus.cuenta_id, sus.colegio_id, sus.p256dh, sus.auth = s.cuenta.id, s.colegio.id, p256dh, auth
    db.commit()
    return {"ok": True}


class Baja(BaseModel):
    endpoint: str = Field(max_length=2000)


@privado.post("/push/baja", status_code=204)
def dar_de_baja(d: Baja, s: SesionFamilia = Depends(familia_sesion), db: Session = Depends(get_db)) -> None:
    db.execute(delete(SuscripcionPush).where(SuscripcionPush.endpoint == d.endpoint,
                                             SuscripcionPush.cuenta_id == s.cuenta.id))
    db.commit()


class CambioPin(BaseModel):
    pin_actual: str = Field(max_length=20)
    pin_nuevo: str = Field(max_length=20)


@privado.put("/pin")
def cambiar_pin(d: CambioPin, s: SesionFamilia = Depends(familia_sesion), db: Session = Depends(get_db)) -> dict:
    if not _comprobar_pin(db, s.cuenta, d.pin_actual, s.colegio):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El PIN actual no es correcto")
    s.cuenta.pin_hash = hashear_clave(_pin_valido(d.pin_nuevo))
    db.execute(update(Apoderado).where(Apoderado.cuenta_id == s.cuenta.id)
               .values(version_sesion=Apoderado.version_sesion + 1))
    db.commit()
    db.refresh(s.apoderado)
    return _token(s.colegio, s.cuenta, s.apoderado)
