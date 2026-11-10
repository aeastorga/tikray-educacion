"""Recojo seguro: reglas compartidas por el panel del colegio, la app de la familia y la portería.

- Quién puede recoger hoy a cada alumno: sus apoderados (siempre, sin estar en la lista), los autorizados
  activos y los autorizados del día.
- Registrar quién lo recogió en una salida (opcional; lo envía la portería después de la marcación, con o sin
  internet). Se ve en la app de la familia y en los reportes. El aviso de salida no cambia: sale al instante al
  escanear, como siempre, y no se manda un segundo aviso.
- La portería nunca bloquea la salida: si quien recoge no está en la lista, se registra igual como
  "fuera de la lista".

Ley 29733: el documento y la foto de quien recoge se usan solo para esto. En el celular de la portería el
documento va con los últimos 4 dígitos.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app import configuracion
from app.almacenamiento import get_almacenamiento_privado
from app.models import (Alumno, AlumnoApoderado, Apoderado, AutorizacionRecojoDia, AutorizadoRecojo,
                        Marcacion, Recojo)

MAX_AUTORIZADOS = 5
# Hasta cuántos días adelante el padre puede autorizar a alguien por un día.
DIAS_ADELANTE = 30
MAX_FOTO = 5 * 1024 * 1024
TIPOS_FOTO = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n", "image/webp": b"RIFF"}


def enmascarar(numero: str) -> str:
    return f"••••{numero[-4:]}" if len(numero) > 4 else numero


def nombre_completo(nombres: str, apellidos: str) -> str:
    return f"{nombres} {apellidos}".strip()


# --- Quién puede recoger ----------------------------------------------------------------------

def _persona(tipo: str, id_: int, nombres: str, apellidos: str, tipo_doc: str, numero: str, parentesco: str,
             completo: bool, foto: bool = False) -> dict:
    return {"tipo": tipo, "id": id_, "nombre": nombre_completo(nombres, apellidos), "parentesco": parentesco,
            "tipo_documento": tipo_doc, "documento": numero if completo else enmascarar(numero), "foto": foto}


def quienes_pueden(db: Session, colegio_id: int, fecha: date, alumno_ids: list[int] | None = None) -> dict[int, dict]:
    """Por alumno: las personas que pueden recogerlo ese día. Sin `alumno_ids`, todos los alumnos activos (el
    padrón de la portería). Tres consultas en total, no una por alumno."""
    def filtro(col):
        return [col.in_(alumno_ids)] if alumno_ids is not None else []

    salida: dict[int, dict] = {}

    def de(alumno_id: int) -> dict:
        return salida.setdefault(alumno_id, {"personas": []})

    for v, ap, a in db.execute(
            select(AlumnoApoderado, Apoderado, Alumno)
            .join(Apoderado, and_(Apoderado.colegio_id == AlumnoApoderado.colegio_id,
                                  Apoderado.id == AlumnoApoderado.apoderado_id))
            .join(Alumno, and_(Alumno.colegio_id == AlumnoApoderado.colegio_id, Alumno.id == AlumnoApoderado.alumno_id))
            .where(AlumnoApoderado.colegio_id == colegio_id, Alumno.activo, *filtro(AlumnoApoderado.alumno_id))
            .order_by(Apoderado.apellidos, Apoderado.nombres)):
        de(a.id)["personas"].append(_persona("apoderado", ap.id, ap.nombres, ap.apellidos, ap.tipo_documento,
                                             ap.numero_documento, v.parentesco, False))
    for x in db.scalars(select(AutorizadoRecojo).where(
            AutorizadoRecojo.colegio_id == colegio_id, AutorizadoRecojo.activo, *filtro(AutorizadoRecojo.alumno_id))
            .order_by(AutorizadoRecojo.apellidos, AutorizadoRecojo.nombres)):
        de(x.alumno_id)["personas"].append(_persona("autorizado", x.id, x.nombres, x.apellidos, x.tipo_documento,
                                                    x.numero_documento, x.parentesco, False, x.foto_clave is not None))
    for x in db.scalars(select(AutorizacionRecojoDia).where(
            AutorizacionRecojoDia.colegio_id == colegio_id, AutorizacionRecojoDia.fecha == fecha,
            AutorizacionRecojoDia.anulada_en.is_(None), *filtro(AutorizacionRecojoDia.alumno_id))
            .order_by(AutorizacionRecojoDia.id)):
        de(x.alumno_id)["personas"].append(_persona("del_dia", x.id, x.nombres, x.apellidos, x.tipo_documento,
                                                    x.numero_documento, x.parentesco, False))
    return salida


# --- Autorizados: alta, cambios y foto ----------------------------------------------------------

def _bloquear_alumno(db: Session, colegio_id: int, alumno_id: int) -> Alumno:
    """Un alta a la vez por alumno: dos al mismo tiempo no pasan el máximo."""
    a = db.scalar(select(Alumno).where(Alumno.colegio_id == colegio_id, Alumno.id == alumno_id).with_for_update())
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alumno no encontrado")
    return a


def _activos(db: Session, colegio_id: int, alumno_id: int, sin: int | None = None) -> list[AutorizadoRecojo]:
    q = select(AutorizadoRecojo).where(AutorizadoRecojo.colegio_id == colegio_id,
                                       AutorizadoRecojo.alumno_id == alumno_id, AutorizadoRecojo.activo)
    return [x for x in db.scalars(q) if x.id != sin]


def _revisar_lista(db: Session, colegio_id: int, alumno_id: int, numero: str, sin: int | None = None,
                   activo: bool = True) -> None:
    if not activo:
        return
    activos = _activos(db, colegio_id, alumno_id, sin)
    if any(x.numero_documento == numero for x in activos):
        raise HTTPException(status.HTTP_409_CONFLICT, "Esa persona ya está en la lista")
    if len(activos) >= MAX_AUTORIZADOS:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Máximo {MAX_AUTORIZADOS} autorizados por alumno. Desactiva uno para agregar otro.")


def crear_autorizado(db: Session, colegio_id: int, alumno_id: int, datos: dict, *, usuario_id: int | None = None,
                     apoderado_id: int | None = None) -> AutorizadoRecojo:
    _bloquear_alumno(db, colegio_id, alumno_id)
    _revisar_lista(db, colegio_id, alumno_id, datos["numero_documento"])
    x = AutorizadoRecojo(colegio_id=colegio_id, alumno_id=alumno_id, activo=True,
                         origen="familia" if apoderado_id else "colegio", creado_por_usuario_id=usuario_id,
                         creado_por_apoderado_id=apoderado_id, **datos)
    db.add(x)
    return x


def editar_autorizado(db: Session, x: AutorizadoRecojo, datos: dict, activo: bool) -> str:
    """Cambia los datos y el estado. Devuelve qué pasó, para el historial."""
    _bloquear_alumno(db, x.colegio_id, x.alumno_id)
    _revisar_lista(db, x.colegio_id, x.alumno_id, datos["numero_documento"], sin=x.id, activo=activo)
    que = "Editó" if activo == x.activo else ("Activó" if activo else "Desactivó")
    for k, v in datos.items():
        setattr(x, k, v)
    x.activo = activo
    return que


async def leer_foto(archivo: UploadFile | None) -> tuple[str, bytes]:
    """Solo imágenes (JPG, PNG, WEBP) de hasta 5 MB; se revisa el tipo real, no el que dice el navegador."""
    if archivo is None or not archivo.filename:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Falta la foto")
    contenido = await archivo.read(MAX_FOTO + 1)
    if len(contenido) > MAX_FOTO:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "La foto pesa más de 5 MB")
    for tipo, firma in TIPOS_FOTO.items():
        if contenido.startswith(firma) and (tipo != "image/webp" or contenido[8:12] == b"WEBP"):
            return tipo, contenido
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Solo se acepta una foto JPG, PNG o WEBP")


def guardar_foto(x: AutorizadoRecojo, tipo: str, contenido: bytes) -> str | None:
    """Guarda la foto nueva y devuelve la clave de la anterior (se borra después del commit)."""
    anterior = x.foto_clave
    x.foto_clave, x.foto_tipo = f"recojo/{x.colegio_id}/{uuid.uuid4().hex}", tipo
    get_almacenamiento_privado().guardar(x.foto_clave, contenido, tipo)
    return anterior


def autorizado_dict(x: AutorizadoRecojo) -> dict:
    return {"id": x.id, "alumno_id": x.alumno_id, "nombres": x.nombres, "apellidos": x.apellidos,
            "tipo_documento": x.tipo_documento, "numero_documento": x.numero_documento, "parentesco": x.parentesco,
            "celular": x.celular, "foto": x.foto_clave is not None, "activo": x.activo, "origen": x.origen}


def del_dia_dict(x: AutorizacionRecojoDia) -> dict:
    return {"id": x.id, "alumno_id": x.alumno_id, "fecha": x.fecha.isoformat(), "nombres": x.nombres,
            "apellidos": x.apellidos, "tipo_documento": x.tipo_documento, "numero_documento": x.numero_documento,
            "parentesco": x.parentesco}


# --- Registrar quién lo recogió (portería) -------------------------------------------------------

@dataclass
class DatosRecojo:
    marcacion: str  # id_cliente de la marcación de salida
    tipo: str  # apoderado | autorizado | del_dia | otro
    persona_id: int | None = None
    nombres: str | None = None
    apellidos: str | None = None
    tipo_documento: str | None = None
    numero_documento: str | None = None


def _rechazo(d: DatosRecojo, mensaje: str) -> dict:
    return {"marcacion": d.marcacion, "estado": "rechazada", "mensaje": mensaje}


def registrar(db: Session, colegio_id: int, d: DatosRecojo, registrado_por_id: int | None,
              quien=None, ahora: datetime | None = None) -> dict:
    """Guarda quién recogió al alumno en esa salida (o lo corrige). No hace commit.
    Si la marcación aún no llegó (se envían en orden, pero puede fallar), responde "esperando" y la portería
    lo reintenta."""
    ahora = ahora or datetime.now(UTC)
    m = db.scalar(select(Marcacion).where(Marcacion.colegio_id == colegio_id, Marcacion.id_cliente == d.marcacion,
                                          Marcacion.alumno_id.is_not(None)))
    if m is None:
        return {"marcacion": d.marcacion, "estado": "esperando", "mensaje": "La salida aún no llega"}
    alumno = db.scalar(select(Alumno).where(Alumno.colegio_id == colegio_id, Alumno.id == m.alumno_id))
    fila = {"tipo": d.tipo, "fuera_de_lista": False, "apoderado_id": None, "autorizado_id": None,
            "autorizacion_dia_id": None, "nombre": None, "tipo_documento": None, "numero_documento": None,
            "parentesco": None}
    if d.tipo == "apoderado":
        ap = db.scalar(select(Apoderado).where(Apoderado.colegio_id == colegio_id, Apoderado.id == d.persona_id))
        if ap is None:
            return _rechazo(d, "Persona no encontrada")
        v = db.scalar(select(AlumnoApoderado).where(AlumnoApoderado.colegio_id == colegio_id,
                                                    AlumnoApoderado.alumno_id == alumno.id,
                                                    AlumnoApoderado.apoderado_id == ap.id))
        fila |= {"apoderado_id": ap.id, "fuera_de_lista": v is None, "parentesco": v.parentesco if v else None}
        persona = ap
    elif d.tipo == "autorizado":
        x = db.scalar(select(AutorizadoRecojo).where(AutorizadoRecojo.colegio_id == colegio_id,
                                                     AutorizadoRecojo.id == d.persona_id,
                                                     AutorizadoRecojo.alumno_id == alumno.id))
        if x is None:
            return _rechazo(d, "Persona no encontrada")
        fila |= {"autorizado_id": x.id, "fuera_de_lista": not x.activo, "parentesco": x.parentesco}
        persona = x
    elif d.tipo == "del_dia":
        x = db.scalar(select(AutorizacionRecojoDia).where(AutorizacionRecojoDia.colegio_id == colegio_id,
                                                          AutorizacionRecojoDia.id == d.persona_id,
                                                          AutorizacionRecojoDia.alumno_id == alumno.id))
        if x is None:
            return _rechazo(d, "Persona no encontrada")
        fila |= {"autorizacion_dia_id": x.id, "parentesco": x.parentesco,
                 "fuera_de_lista": x.fecha != m.fecha or x.anulada_en is not None}
        persona = x
    else:  # otro: nombres y documento ya validados por la ruta
        persona = d
        fila["fuera_de_lista"] = True
    fila |= {"nombre": nombre_completo(persona.nombres, persona.apellidos),
             "tipo_documento": persona.tipo_documento, "numero_documento": persona.numero_documento}

    r = db.scalar(select(Recojo).where(Recojo.colegio_id == colegio_id, Recojo.marcacion_id == m.id))
    # Un reenvío igual (la portería no recibió la respuesta) no deja otra línea en el historial.
    cambio = r is None or (r.tipo, r.numero_documento, r.fuera_de_lista) != (
        fila["tipo"], fila["numero_documento"], fila["fuera_de_lista"])
    if r is None:
        r = Recojo(colegio_id=colegio_id, marcacion_id=m.id, alumno_id=alumno.id, fecha=m.fecha, momento=m.momento)
        db.add(r)
    for k, v in fila.items():
        setattr(r, k, v)
    r.registrado_por_id, r.recibido_en = registrado_por_id, ahora
    db.flush()

    if fila["fuera_de_lista"] and cambio:
        configuracion.registrar(db, colegio_id, quien, "crear", "recojo", "recojo fuera de la lista", r.id,
                                f"Salida de {alumno.apellidos}, {alumno.nombres} con {fila['nombre']} "
                                f"({fila['tipo_documento']}): fuera de la lista")
    db.flush()
    return {"marcacion": d.marcacion, "estado": "ok", "fuera_de_lista": fila["fuera_de_lista"]}


def ultimos_recojos(db: Session, colegio_id: int, fecha: date, alumno_ids: list[int]) -> dict[int, Recojo]:
    """El recojo de la última salida del día de cada alumno (para los reportes)."""
    if not alumno_ids:
        return {}
    salida: dict[int, Recojo] = {}
    for r in db.scalars(select(Recojo).where(Recojo.colegio_id == colegio_id, Recojo.fecha == fecha,
                                             Recojo.alumno_id.in_(alumno_ids)).order_by(Recojo.momento)):
        salida[r.alumno_id] = r
    return salida


def para_familia(r: Recojo | None) -> dict | None:
    """Lo que ve la familia: quién y con qué parentesco (sin el documento)."""
    if r is None:
        return None
    return {"nombre": r.nombre, "parentesco": r.parentesco, "fuera_de_lista": r.fuera_de_lista}


def recojo_dict(r: Recojo | None) -> dict | None:
    if r is None:
        return None
    return {"tipo": r.tipo, "nombre": r.nombre, "parentesco": r.parentesco, "tipo_documento": r.tipo_documento,
            "numero_documento": r.numero_documento, "fuera_de_lista": r.fuera_de_lista}
