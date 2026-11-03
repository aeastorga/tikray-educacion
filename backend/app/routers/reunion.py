"""Modo reunión: el tutor abre la reunión de su aula y muestra el QR; cada padre llena su ficha
desde su celular (o una tablet en modo quiosco, o en papel) y el tutor la aprueba ahí mismo.

Dos routers:
- `router` (/api/reuniones): personal con el módulo "Reunión de padres"; un rol "solo sus
  secciones" solo abre y ve reuniones de las secciones a su cargo.
- `publico` (/api/familia/reunion): el padre, sin sesión. Solo con un QR vigente de este colegio,
  solo para alumnos de esa sección y con límite de intentos. Nada entra al padrón sin el tutor.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app import familias, pdf, reunion, validacion
from app.comun import guardar, obtener
from app.cuaderno import secciones_permitidas
from app.db import get_db
from app.deps import Sesion, colegio_del_host, requerir_permiso
from app.models import (Alumno, AlumnoApoderado, Apoderado, Colegio, FichaReunion, Grado, InvitacionFamilia,
                        Matricula, ReunionPadres, Seccion, Usuario)
from app.proteccion import FALLOS_IP, ip_cliente
from app.routers.importacion import imagen_pdf
from app.routers.estructura import anio_activo
from app.routers.familia import _cuenta_de, activar

router = APIRouter(prefix="/reuniones", tags=["reuniones"])
publico = APIRouter(prefix="/familia/reunion", tags=["reuniones"])
ver = requerir_permiso("reuniones")
editar = requerir_permiso("reuniones", "editar")

PARENTESCOS = ("Madre", "Padre", "Abuela", "Abuelo", "Tía", "Tío", "Hermana", "Hermano", "Apoderado", "Otro")


# --- Datos de la ficha ---------------------------------------------------------------------

class Persona(BaseModel):
    tipo_documento: str = "DNI"
    numero_documento: str = Field(max_length=20)
    nombres: str = Field(max_length=200)
    apellidos: str = Field(max_length=200)
    celular: str | None = Field(default=None, max_length=20)
    correo: str | None = Field(default=None, max_length=254)
    parentesco: Literal[PARENTESCOS] = "Apoderado"

    @model_validator(mode="after")
    def normalizar(self):
        self.tipo_documento = validacion.tipo_documento(self.tipo_documento)
        self.numero_documento = validacion.documento(self.tipo_documento, self.numero_documento)
        self.nombres = validacion.nombre(self.nombres)
        self.apellidos = validacion.nombre(self.apellidos)
        self.celular = validacion.celular(self.celular)
        self.correo = validacion.correo(self.correo)
        return self


class Ficha(BaseModel):
    apoderado: Persona
    otro: Persona | None = None
    acepto: bool

    @model_validator(mode="after")
    def revisar(self):
        if not self.acepto:
            raise ValueError("Para enviar la ficha debes aceptar el tratamiento de datos")
        if self.apoderado.celular is None:
            raise ValueError("Tu celular es obligatorio: por ahí te llegan los avisos del colegio")
        if self.otro and (self.otro.tipo_documento, self.otro.numero_documento) == \
                (self.apoderado.tipo_documento, self.apoderado.numero_documento):
            raise ValueError("El otro apoderado no puede tener tu mismo documento")
        return self

    def guardable(self) -> dict:
        return {"apoderado": self.apoderado.model_dump(), "otro": self.otro.model_dump() if self.otro else None}


# --- Ayudas --------------------------------------------------------------------------------

def _etiqueta(db: Session, cid: int, seccion_id: int) -> str:
    fila = db.execute(select(Grado.nombre, Seccion.nombre)
                      .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
                      .where(Seccion.colegio_id == cid, Seccion.id == seccion_id)).first()
    return f"{fila[0]} {fila[1]}" if fila else ""


def _permitida(db: Session, s: Sesion, seccion_id: int) -> None:
    permitidas = secciones_permitidas(db, s.usuario)
    if permitidas is not None and seccion_id not in permitidas:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sección no encontrada")


def _reunion(db: Session, s: Sesion, reunion_id: int) -> ReunionPadres:
    r = obtener(db, ReunionPadres, s.colegio.id, reunion_id, "Reunión")
    _permitida(db, s, r.seccion_id)
    return r


def qr_svg(texto: str) -> str:
    widget = QrCodeWidget(texto, barLevel="M")
    x1, y1, x2, y2 = widget.getBounds()
    lado = 240
    dibujo = Drawing(lado, lado, transform=[lado / (x2 - x1), 0, 0, lado / (y2 - y1), 0, 0])
    dibujo.add(widget)
    return renderSVG.drawToString(dibujo)


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def _ficha_salida(db: Session, f: FichaReunion, alumnos: dict[int, str]) -> dict:
    cid = f.colegio_id
    pendiente = f.estado == "pendiente"
    return {
        "id": f.id, "alumno_id": f.alumno_id, "alumno": alumnos.get(f.alumno_id, ""), "origen": f.origen,
        "estado": f.estado, "datos": f.datos, "creado_en": _iso(f.creado_en), "actualizado_en": _iso(f.actualizado_en),
        "reenviada": f.actualizado_en > f.creado_en,
        # Los cambios frente al padrón se calculan ahora (si alguien cambió el padrón mientras tanto, se ve).
        "apoderado": reunion.cambios_persona(db, cid, f.alumno_id, f.datos["apoderado"]) if pendiente else None,
        "otro": reunion.cambios_persona(db, cid, f.alumno_id, f.datos.get("otro")) if pendiente else None,
        "motivo_rechazo": f.motivo_rechazo, "revisado_en": _iso(f.revisado_en),
        "cuenta": _estado_cuenta(db, f) if f.estado == "aprobada" else None,
    }


def _estado_cuenta(db: Session, f: FichaReunion) -> str | None:
    ap = db.get(Apoderado, f.apoderado_id) if f.apoderado_id else None
    if ap is None:
        return None
    if ap.estado_acceso == "activo":
        return "activa"
    inv = db.get(InvitacionFamilia, f.invitacion_id) if f.invitacion_id else None
    return "por_activar" if inv and familias.estado_invitacion(inv) == "pendiente" else ap.estado_acceso


def _salida(db: Session, r: ReunionPadres, con_fichas: bool = True) -> dict:
    cid = r.colegio_id
    total = reunion.cantidad_alumnos(db, r)
    estado = reunion.estado(r, total)
    creador = db.scalar(select(Usuario.nombres + " " + Usuario.apellidos).where(
        Usuario.colegio_id == cid, Usuario.id == r.creado_por_id)) if r.creado_por_id else None
    salida = {
        "id": r.id, "seccion_id": r.seccion_id, "seccion": _etiqueta(db, cid, r.seccion_id), "titulo": r.titulo,
        "creado_en": _iso(r.creado_en), "vence_en": _iso(r.vence_en), "cerrada_en": _iso(r.cerrada_en),
        "creado_por": creador, "estado": estado, "alumnos": total,
        # El QR solo mientras está abierta; el navegador arma la dirección con su propio origen.
        "token": reunion.token_qr(r) if estado == "abierta" else None,
    }
    if con_fichas:
        fichas = db.scalars(select(FichaReunion).where(FichaReunion.colegio_id == cid, FichaReunion.reunion_id == r.id)
                            .order_by(FichaReunion.actualizado_en.desc())).all()
        nombres = dict(db.execute(select(Alumno.id, Alumno.apellidos + ", " + Alumno.nombres).where(
            Alumno.colegio_id == cid, Alumno.id.in_({f.alumno_id for f in fichas}))).all())
        salida["fichas"] = [_ficha_salida(db, f, nombres) for f in fichas]
    return salida


# --- Personal: abrir, ver, aprobar --------------------------------------------------------

@router.get("/secciones")
def secciones(s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> list[dict]:
    """Secciones del año activo en las que esta persona puede hacer reunión, con la reunión abierta si hay."""
    cid = s.colegio.id
    anio = anio_activo(db, cid)
    permitidas = secciones_permitidas(db, s.usuario)
    q = (select(Seccion.id, Grado.nombre, Seccion.nombre)
         .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
         .where(Seccion.colegio_id == cid, Seccion.anio_id == anio.id).order_by(Grado.orden, Grado.nombre, Seccion.nombre))
    if permitidas is not None:
        q = q.where(Seccion.id.in_(permitidas))
    abiertas = {r.seccion_id: r for r in db.scalars(select(ReunionPadres).where(
        ReunionPadres.colegio_id == cid, ReunionPadres.cerrada_en.is_(None),
        ReunionPadres.vence_en > datetime.now(UTC)))}
    return [{"id": i, "nombre": f"{g} {n}", "reunion_abierta": abiertas[i].id if i in abiertas else None}
            for i, g, n in db.execute(q)]


@router.get("")
def listar(s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> list[dict]:
    """Reuniones de los últimos 60 días de las secciones que puede ver."""
    q = select(ReunionPadres).where(ReunionPadres.colegio_id == s.colegio.id,
                                    ReunionPadres.creado_en > datetime.now(UTC) - timedelta(days=60))
    permitidas = secciones_permitidas(db, s.usuario)
    if permitidas is not None:
        q = q.where(ReunionPadres.seccion_id.in_(permitidas))
    filas = []
    for r in db.scalars(q.order_by(ReunionPadres.creado_en.desc()).limit(100)):
        conteo = dict(db.execute(select(FichaReunion.estado, func.count()).where(
            FichaReunion.colegio_id == r.colegio_id, FichaReunion.reunion_id == r.id)
            .group_by(FichaReunion.estado)).all())
        filas.append(_salida(db, r, con_fichas=False) | {"fichas": conteo})
    return filas


class NuevaReunion(BaseModel):
    seccion_id: int
    horas: int = Field(default=reunion.HORAS_POR_DEFECTO, ge=1, le=reunion.HORAS_MAXIMAS)
    titulo: str = Field(default="Reunión de padres", min_length=1, max_length=120)


@router.post("", status_code=201)
def abrir(d: NuevaReunion, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Abre la reunión de una sección. Si había otra abierta en esa sección, la cierra: un solo QR vale."""
    cid = s.colegio.id
    obtener(db, Seccion, cid, d.seccion_id, "Sección")
    _permitida(db, s, d.seccion_id)
    ahora = datetime.now(UTC)
    for previa in db.scalars(select(ReunionPadres).where(
            ReunionPadres.colegio_id == cid, ReunionPadres.seccion_id == d.seccion_id,
            ReunionPadres.cerrada_en.is_(None), ReunionPadres.vence_en > ahora)):
        previa.cerrada_en = ahora
    r = ReunionPadres(colegio_id=cid, seccion_id=d.seccion_id, titulo=d.titulo.strip(), nonce=reunion.nuevo_nonce(),
                      creado_por_id=s.usuario.id, creado_en=ahora, vence_en=ahora + timedelta(hours=d.horas))
    db.add(r)
    guardar(db)
    return _salida(db, r)


@router.get("/{reunion_id}")
def detalle(reunion_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    """Lo que ve el tutor en vivo (el navegador lo pide cada pocos segundos)."""
    return _salida(db, _reunion(db, s, reunion_id))


@router.post("/{reunion_id}/cerrar")
def cerrar(reunion_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    r = _reunion(db, s, reunion_id)
    r.cerrada_en = r.cerrada_en or datetime.now(UTC)
    guardar(db)
    return _salida(db, r)


@router.post("/{reunion_id}/nuevo-qr")
def nuevo_qr(reunion_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Otro QR para la misma reunión (el anterior deja de servir); vuelve a contar los intentos.
    Sirve si el QR se bloqueó o si una foto del QR salió del aula."""
    r = _reunion(db, s, reunion_id)
    if r.cerrada_en or r.vence_en <= datetime.now(UTC):
        raise HTTPException(status.HTTP_409_CONFLICT, "La reunión ya terminó. Abre una nueva")
    r.nonce, r.intentos_fallidos = reunion.nuevo_nonce(), 0
    guardar(db)
    return _salida(db, r)


class TextoQr(BaseModel):
    texto: str = Field(min_length=1, max_length=300)


@router.post("/qr")
def generar_qr(d: TextoQr, s: Sesion = Depends(ver)) -> dict:
    """El dibujo del QR (SVG) para mostrarlo en pantalla: el de la reunión o el de activar una cuenta."""
    return {"svg": qr_svg(d.texto)}


class Aprobacion(BaseModel):
    activar: bool = False  # crear la cuenta del padre ahora (el PIN lo pone él, en su celular)


@router.post("/{reunion_id}/fichas/{ficha_id}/aprobar")
def aprobar(reunion_id: int, ficha_id: int, d: Aprobacion, s: Sesion = Depends(editar),
            db: Session = Depends(get_db)) -> dict:
    r = _reunion(db, s, reunion_id)
    f = db.scalar(select(FichaReunion).where(FichaReunion.colegio_id == r.colegio_id, FichaReunion.reunion_id == r.id,
                                             FichaReunion.id == ficha_id).with_for_update())
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ficha no encontrada")
    if f.estado != "pendiente":
        raise HTTPException(status.HTTP_409_CONFLICT, "La ficha ya fue revisada")
    try:
        ap, notas = reunion.aprobar(db, f, s.usuario.id)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    salida: dict = {"ficha": f.id, "apoderado_id": ap.id, "notas": notas, "activacion": None}
    if d.activar and ap.estado_acceso != "activo":
        # El enlace vale hasta un rato después de la reunión y activa sin otra aprobación (fue en persona).
        vigencia = max(r.vence_en - datetime.now(UTC), timedelta(0)) + reunion.MARGEN_ACTIVACION
        inv, token = familias.crear_invitacion(db, ap, s.usuario.id, presencial=True, vigencia=vigencia)
        f.invitacion_id = inv.id
        # Desde su celular la crea ahí mismo; si llenó en la tablet o en papel, el tutor le muestra
        # un QR con el enlace o se lo manda por WhatsApp.
        salida["activacion"] = {"en_su_celular": f.origen == "celular" and f.token_hash is not None,
                                "token": None if f.origen == "celular" and f.token_hash else token,
                                "celular": ap.celular, "nombres": ap.nombres,
                                "pide_pin_actual": _cuenta_de(db, ap) is not None}
    guardar(db)
    return salida


class Rechazo(BaseModel):
    motivo: str = Field(min_length=1, max_length=200)


@router.post("/{reunion_id}/fichas/{ficha_id}/rechazar")
def rechazar(reunion_id: int, ficha_id: int, d: Rechazo, s: Sesion = Depends(editar),
             db: Session = Depends(get_db)) -> dict:
    r = _reunion(db, s, reunion_id)
    f = db.scalar(select(FichaReunion).where(FichaReunion.colegio_id == r.colegio_id, FichaReunion.reunion_id == r.id,
                                             FichaReunion.id == ficha_id).with_for_update())
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ficha no encontrada")
    if f.estado != "pendiente":
        raise HTTPException(status.HTTP_409_CONFLICT, "La ficha ya fue revisada")
    f.estado, f.motivo_rechazo = "rechazada", d.motivo.strip()
    f.revisado_por_id, f.revisado_en = s.usuario.id, datetime.now(UTC)
    guardar(db)
    return {"ficha": f.id, "estado": f.estado}


class FichaPapel(Ficha):
    alumno_id: int


@router.post("/{reunion_id}/fichas", status_code=201)
def ficha_en_papel(reunion_id: int, d: FichaPapel, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """El tutor pasa una ficha de papel (firmada por el padre). Queda pendiente como las demás."""
    r = _reunion(db, s, reunion_id)
    alumno = db.scalar(reunion.alumnos_de(db, r).where(Alumno.id == d.alumno_id))
    if alumno is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El alumno no es de esta sección")
    f, _ = _guardar_ficha(db, r, alumno, d, "papel", None)
    guardar(db)
    return {"id": f.id}


@router.get("/{reunion_id}/ausentes")
def ausentes(reunion_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> list[dict]:
    """Alumnos de la sección sin ficha (pendiente o aprobada) en esta reunión, con sus apoderados,
    para mandarles su enlace personal por WhatsApp."""
    r = _reunion(db, s, reunion_id)
    cid = r.colegio_id
    con_ficha = select(FichaReunion.alumno_id).where(FichaReunion.colegio_id == cid, FichaReunion.reunion_id == r.id,
                                                     FichaReunion.estado != "rechazada")
    alumnos = db.scalars(reunion.alumnos_de(db, r).where(Alumno.id.not_in(con_ficha))
                         .order_by(Alumno.apellidos, Alumno.nombres)).all()
    apoderados: dict[int, list[dict]] = {}
    for alumno_id, ap, parentesco in db.execute(
            select(AlumnoApoderado.alumno_id, Apoderado, AlumnoApoderado.parentesco)
            .join(Apoderado, and_(Apoderado.colegio_id == AlumnoApoderado.colegio_id,
                                  Apoderado.id == AlumnoApoderado.apoderado_id))
            .where(AlumnoApoderado.colegio_id == cid, AlumnoApoderado.alumno_id.in_([a.id for a in alumnos]))
            .order_by(Apoderado.apellidos)):
        apoderados.setdefault(alumno_id, []).append({
            "id": ap.id, "nombre": f"{ap.nombres} {ap.apellidos}", "parentesco": parentesco, "celular": ap.celular,
            "estado": ap.estado_acceso})
    return [{"id": a.id, "nombre": f"{a.apellidos}, {a.nombres}", "apoderados": apoderados.get(a.id, [])}
            for a in alumnos]


@router.post("/{reunion_id}/apoderados/{apoderado_id}/invitacion", status_code=201)
def invitar(reunion_id: int, apoderado_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """El enlace personal de un apoderado de esta sección (el mismo de "Cuentas de padres"), para el
    botón de WhatsApp. El tutor no necesita el módulo de cuentas de padres, pero solo para su aula."""
    r = _reunion(db, s, reunion_id)
    ap = obtener(db, Apoderado, r.colegio_id, apoderado_id, "Apoderado")
    es_del_aula = db.scalar(select(func.count()).select_from(AlumnoApoderado).where(
        AlumnoApoderado.colegio_id == r.colegio_id, AlumnoApoderado.apoderado_id == ap.id,
        AlumnoApoderado.alumno_id.in_(reunion.alumnos_de(db, r).with_only_columns(Alumno.id))))
    if not es_del_aula:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Apoderado no encontrado")
    if ap.estado_acceso == "bloqueado":
        raise HTTPException(status.HTTP_409_CONFLICT, "El apoderado está bloqueado. Lo desbloquea el colegio")
    if ap.estado_acceso == "activo":
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya tiene su cuenta activa")
    inv, token = familias.crear_invitacion(db, ap, s.usuario.id)
    guardar(db)
    return {"token": token, "vence_en": inv.vence_en.isoformat(), "celular": ap.celular, "nombres": ap.nombres}


@router.get("/secciones/{seccion_id}/fichas.pdf")
def fichas_pdf(seccion_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> Response:
    """Respaldo en papel: una ficha por alumno con los datos del padrón para corregir y firmar."""
    cid = s.colegio.id
    sec = obtener(db, Seccion, cid, seccion_id, "Sección")
    _permitida(db, s, sec.id)
    alumnos = db.scalars(select(Alumno).join(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id,
                                                             Matricula.alumno_id == Alumno.id))
                         .where(Alumno.colegio_id == cid, Matricula.seccion_id == sec.id, Alumno.activo)
                         .order_by(Alumno.apellidos, Alumno.nombres)).all()
    por_alumno: dict[int, list[pdf.ApoderadoFicha]] = {}
    for alumno_id, ap, parentesco in db.execute(
            select(AlumnoApoderado.alumno_id, Apoderado, AlumnoApoderado.parentesco)
            .join(Apoderado, and_(Apoderado.colegio_id == AlumnoApoderado.colegio_id,
                                  Apoderado.id == AlumnoApoderado.apoderado_id))
            .where(AlumnoApoderado.colegio_id == cid, AlumnoApoderado.alumno_id.in_([a.id for a in alumnos]))
            .order_by(Apoderado.apellidos)):
        por_alumno.setdefault(alumno_id, []).append(pdf.ApoderadoFicha(
            documento=f"{ap.tipo_documento} {ap.numero_documento}", nombres=ap.nombres, apellidos=ap.apellidos,
            parentesco=parentesco, celular=ap.celular or "", correo=ap.correo or ""))
    etiqueta = _etiqueta(db, cid, sec.id)
    contenido = pdf.fichas_reunion(
        imagen_pdf(s.colegio), etiqueta, familias.texto_consentimiento(s.colegio.nombre),
        [pdf.FichaAlumno(nombre=f"{a.apellidos}, {a.nombres}", documento=f"{a.tipo_documento} {a.numero_documento}",
                         apoderados=por_alumno.get(a.id, [])) for a in alumnos])
    nombre = "fichas-" + re.sub(r"[^a-z0-9]+", "-", validacion.sin_tildes(etiqueta).lower()).strip("-")
    return Response(contenido, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nombre.lower()}.pdf"'})


# --- Padre: QR del aula → documento del hijo → ficha → (aprobada) → PIN ---------------------

class ConQr(BaseModel):
    token: str = Field(min_length=3, max_length=80)


class ConAlumno(ConQr):
    documento_alumno: str = Field(min_length=1, max_length=20)


class FichaPadre(ConAlumno, Ficha):
    quiosco: bool = False  # tablet del aula: no se queda con nada para ver después


MENSAJES = {
    "cerrada": "La reunión ya terminó. Pide al tutor tu enlace personal.",
    "vencida": "Este código ya venció. Pide al tutor tu enlace personal.",
    "bloqueada": "Este código se bloqueó por demasiados intentos. Pide al tutor que muestre uno nuevo.",
}


def _abierta(db: Session, colegio: Colegio, token: str) -> ReunionPadres:
    r = reunion.por_token(db, colegio.id, token)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Código no válido. Escanéalo de nuevo")
    estado = reunion.estado(r, reunion.cantidad_alumnos(db, r))
    if estado != "abierta":
        raise HTTPException(status.HTTP_410_GONE, MENSAJES[estado])
    return r


def _doc(texto: str) -> str:
    return "".join(c for c in (texto or "") if c.isalnum()).upper()


def _alumno(db: Session, colegio: Colegio, d: ConAlumno, request: Request) -> tuple[ReunionPadres, Alumno]:
    """El alumno de esa sección con ese documento. Los errores cuentan por celular y por QR."""
    ip = f"{ip_cliente(request)}"
    if not FALLOS_IP.hay_cupo(f"familia:{ip}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos. Espera unos minutos")
    r = _abierta(db, colegio, d.token)
    clave = f"{r.id}:{ip}"
    if not reunion.FALLOS_REUNION.hay_cupo(clave):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos. Pide ayuda al tutor")
    alumno = db.scalar(reunion.alumnos_de(db, r).where(Alumno.numero_documento == _doc(d.documento_alumno)))
    if alumno is None:
        reunion.FALLOS_REUNION.registrar(clave)
        db.refresh(r, with_for_update=True)
        r.intentos_fallidos += 1
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "No encontramos a un alumno de esta aula con ese documento. Revísalo o pide ayuda al tutor")
    return r, alumno


@publico.post("/abrir")
def abrir_qr(d: ConQr, colegio: Colegio = Depends(colegio_del_host), db: Session = Depends(get_db)) -> dict:
    r = _abierta(db, colegio, d.token)
    return {"colegio": colegio.nombre, "titulo": r.titulo, "seccion": _etiqueta(db, colegio.id, r.seccion_id),
            "vence_en": _iso(r.vence_en), "parentescos": PARENTESCOS,
            "consentimiento": {"version": familias.CONSENTIMIENTO_VERSION,
                               "texto": familias.texto_consentimiento(colegio.nombre)}}


@publico.post("/alumno")
def revisar_alumno(d: ConAlumno, request: Request, colegio: Colegio = Depends(colegio_del_host),
                   db: Session = Depends(get_db)) -> dict:
    """Confirma el alumno. Solo su nombre de pila y la inicial del apellido; nada de los apoderados
    (no se precarga la ficha: quien tenga el QR y un DNI no debe poder leer los datos de la familia)."""
    _, alumno = _alumno(db, colegio, d, request)
    return {"alumno": f"{alumno.nombres} {alumno.apellidos[:1]}."}


def _guardar_ficha(db: Session, r: ReunionPadres, alumno: Alumno, d: Ficha, origen: str,
                   ip: str | None) -> tuple[FichaReunion, str | None]:
    """Crea la ficha, o reemplaza la pendiente de la misma persona para el mismo alumno."""
    datos = d.guardable()
    documento = datos["apoderado"]["numero_documento"]
    previas = db.scalars(select(FichaReunion).where(
        FichaReunion.colegio_id == r.colegio_id, FichaReunion.reunion_id == r.id, FichaReunion.alumno_id == alumno.id,
        FichaReunion.estado != "rechazada").with_for_update()).all()
    propia = next((f for f in previas if f.documento == documento), None)
    if propia is not None and propia.estado == "aprobada":
        raise HTTPException(status.HTTP_409_CONFLICT, "Tu ficha ya fue aprobada por el tutor")
    if propia is None and len(previas) >= reunion.FICHAS_POR_ALUMNO:
        raise HTTPException(status.HTTP_409_CONFLICT, "Este alumno ya tiene sus fichas. Pide ayuda al tutor")
    ahora = datetime.now(UTC)
    f = propia or FichaReunion(colegio_id=r.colegio_id, reunion_id=r.id, alumno_id=alumno.id, documento=documento,
                               creado_en=ahora)
    f.origen, f.datos, f.ip, f.actualizado_en = origen, datos, ip, ahora
    f.consentimiento_version = familias.CONSENTIMIENTO_VERSION
    if propia is None:
        db.add(f)
    db.flush()
    codigo = None
    if origen == "celular":
        codigo = reunion.nuevo_token_ficha(f.id)
        f.token_hash = reunion.hash_token(codigo)
    else:
        f.token_hash = None
    return f, codigo


@publico.post("/ficha", status_code=201)
def enviar_ficha(d: FichaPadre, request: Request, colegio: Colegio = Depends(colegio_del_host),
                 db: Session = Depends(get_db)) -> dict:
    r, alumno = _alumno(db, colegio, d, request)
    f, codigo = _guardar_ficha(db, r, alumno, d, "quiosco" if d.quiosco else "celular", ip_cliente(request)[:45])
    guardar(db)
    # El código se queda en el celular: con él ve si el tutor aprobó y crea su PIN. La tablet no lo guarda.
    return {"codigo": codigo, "alumno": f"{alumno.nombres} {alumno.apellidos[:1]}."}


class ConCodigo(BaseModel):
    codigo: str = Field(min_length=10, max_length=80)


def _ficha_por_codigo(db: Session, colegio: Colegio, codigo: str, request: Request) -> FichaReunion:
    ip = f"familia:{ip_cliente(request)}"
    if not FALLOS_IP.hay_cupo(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos. Espera unos minutos")
    f = db.scalar(select(FichaReunion).where(FichaReunion.colegio_id == colegio.id,
                                             FichaReunion.token_hash == reunion.hash_token(codigo)))
    r = db.get(ReunionPadres, f.reunion_id) if f else None
    if f is None or r is None or r.colegio_id != colegio.id:
        FALLOS_IP.registrar(ip)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos tu ficha. Pide ayuda al tutor")
    if datetime.now(UTC) > (r.cerrada_en or r.vence_en) + reunion.MARGEN_ACTIVACION:
        raise HTTPException(status.HTTP_410_GONE, "Este código ya venció. Pide al colegio tu enlace personal")
    return f


@publico.post("/estado")
def estado_ficha(d: ConCodigo, request: Request, colegio: Colegio = Depends(colegio_del_host),
                 db: Session = Depends(get_db)) -> dict:
    """El celular del padre lo pide cada pocos segundos mientras espera al tutor."""
    f = _ficha_por_codigo(db, colegio, d.codigo, request)
    salida = {"estado": f.estado, "motivo": f.motivo_rechazo, "puede_activar": False, "pide_pin_actual": False,
              "activa": False}
    if f.estado == "aprobada":
        ap = db.get(Apoderado, f.apoderado_id) if f.apoderado_id else None
        inv = db.get(InvitacionFamilia, f.invitacion_id) if f.invitacion_id else None
        salida["activa"] = ap is not None and ap.estado_acceso == "activo"
        if ap is not None and inv is not None and familias.estado_invitacion(inv) == "pendiente":
            salida["puede_activar"] = True
            salida["pide_pin_actual"] = _cuenta_de(db, ap) is not None
            salida["nombres"] = ap.nombres
    return salida


class ActivarDesdeFicha(ConCodigo):
    pin: str | None = None
    pin_actual: str | None = None


@publico.post("/activar")
def activar_desde_ficha(d: ActivarDesdeFicha, request: Request, colegio: Colegio = Depends(colegio_del_host),
                        db: Session = Depends(get_db)) -> dict:
    """Crea el PIN (o une la cuenta que ya tiene) con la ficha que el tutor aprobó en persona.
    El consentimiento ya quedó guardado al aprobar la ficha."""
    f = _ficha_por_codigo(db, colegio, d.codigo, request)
    inv = db.scalar(select(InvitacionFamilia).where(InvitacionFamilia.colegio_id == colegio.id,
                                                    InvitacionFamilia.id == f.invitacion_id).with_for_update()) \
        if f.invitacion_id else None
    if f.estado != "aprobada" or inv is None or familias.estado_invitacion(inv) != "pendiente":
        raise HTTPException(status.HTTP_409_CONFLICT, "El tutor aún no habilitó tu cuenta. Pídeselo")
    ap = db.get(Apoderado, inv.apoderado_id)
    if ap.estado_acceso == "bloqueado":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu acceso está bloqueado. Comunícate con el colegio")
    resultado = activar(db, colegio, inv, ap, d.pin, d.pin_actual, request)
    f.token_hash = None  # ya cumplió: no sirve para nada más
    db.commit()
    return resultado
