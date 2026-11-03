"""Panel de Tikray Labs: /plataforma.

Usa su propio token ("plataforma") y su propia tabla de usuarios. Un token de
colegio nunca entra aquí, y un token de plataforma nunca entra a /api.
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import activacion, configuracion
from app.config import get_settings
from app.db import get_db
from app.deps import SUBDOMINIOS_RESERVADOS, admin_plataforma
from app.fechas import hoy_lima
from app.models import AdminPlataforma, Colegio, Rol, Usuario
from app.models.colegio import CONTRATABLES
from app.modulos import MODULOS
from app.routers.configuracion import NOMBRE_CAMPO, Perfil, aplicar_perfil, modulos_de, perfil_de
from app.routers.personal import DocumentoPersonal
from app.proteccion import generar_clave_temporal, ip_cliente, permitir_intento, registrar_fallo
from app.seguridad import emitir_token, hashear_clave, verificar_clave_o_simular

publico = APIRouter(prefix="/plataforma", tags=["plataforma"])
router = APIRouter(prefix="/plataforma", tags=["plataforma"], dependencies=[Depends(admin_plataforma)])

QUIEN = "Tikray Labs"  # en el historial del colegio
SUBDOMINIO = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"
Estado = Literal["prueba", "activo", "suspendido"]


class Ingreso(BaseModel):
    correo: str = Field(max_length=254)
    clave: str = Field(max_length=200)


class Director(DocumentoPersonal):
    pass


def _dominio(v: str | None) -> str | None:
    return v.strip().lower().rstrip(".") or None if v else None


def _prueba_con_vencimiento(estado: str | None, vence_en: date | None) -> None:
    if estado == "prueba" and vence_en is None:
        raise ValueError("Una prueba necesita fecha de vencimiento")


class NuevoColegio(BaseModel):
    nombre: str = Field(min_length=1, max_length=200)
    subdominio: str = Field(pattern=SUBDOMINIO)
    dominio_propio: str | None = Field(default=None, max_length=253)
    estado: Estado = "activo"
    vence_en: date | None = None
    director: Director

    @model_validator(mode="after")
    def _estado(self):
        _prueba_con_vencimiento(self.estado, self.vence_en)
        return self

    @field_validator("subdominio")
    @classmethod
    def _no_reservado(cls, v: str) -> str:
        if v in SUBDOMINIOS_RESERVADOS:
            raise ValueError("Ese subdominio está reservado")
        return v

    _norm_dominio = field_validator("dominio_propio")(classmethod(lambda cls, v: _dominio(v)))


class CambioColegio(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=200)
    dominio_propio: str | None = Field(default=None, max_length=253)
    estado: Estado | None = None
    vence_en: date | None = None
    perfil: Perfil | None = None
    modulos_contratados: list[Literal["asistencia", "cuaderno", "familias", "reuniones"]] | None = None

    _norm_dominio = field_validator("dominio_propio")(classmethod(lambda cls, v: _dominio(v)))


class ColegioOut(BaseModel):
    id: int
    nombre: str
    subdominio: str
    dominio_propio: str | None
    estado: str
    vence_en: date | None
    disponible: bool
    es_demo: bool
    perfil: dict
    modulos: list[dict]


class ColegioCreado(BaseModel):
    colegio: ColegioOut
    director_usuario: str
    director_clave_temporal: str  # se muestra una sola vez


def _salida(c: Colegio) -> ColegioOut:
    return ColegioOut(id=c.id, nombre=c.nombre, subdominio=c.subdominio, dominio_propio=c.dominio_propio,
                      estado=c.estado, vence_en=c.vence_en, disponible=c.disponible(hoy_lima()), es_demo=c.es_demo,
                      perfil=perfil_de(c), modulos=modulos_de(c))


def _conflicto() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "El subdominio o dominio ya está en uso")


@publico.post("/auth/ingreso")
def ingresar(datos: Ingreso, request: Request, db: Session = Depends(get_db)) -> dict:
    correo = datos.correo.strip().lower()
    cuenta, ip = f"plataforma:{correo}", f"plataforma:{ip_cliente(request)}"
    if not permitir_intento(cuenta, ip):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales incorrectas")
    admin = db.scalar(select(AdminPlataforma).where(AdminPlataforma.correo == correo))
    ok = verificar_clave_o_simular(datos.clave, admin.clave_hash if admin else None)
    if not ok or not admin.activo:
        registrar_fallo(cuenta, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales incorrectas")
    token = emitir_token("plataforma", admin.id, admin.version_sesion, get_settings().token_plataforma_minutos)
    return {"token": token, "nombre": admin.nombre}


@router.get("/colegios")
def listar(db: Session = Depends(get_db)) -> list[ColegioOut]:
    return [_salida(c) for c in db.scalars(select(Colegio).order_by(Colegio.nombre))]


@router.post("/colegios", status_code=201)
def crear(datos: NuevoColegio, db: Session = Depends(get_db)) -> ColegioCreado:
    colegio = Colegio(nombre=datos.nombre.strip(), subdominio=datos.subdominio,
                      dominio_propio=datos.dominio_propio, estado=datos.estado, vence_en=datos.vence_en)
    db.add(colegio)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _conflicto()
    rol = Rol(colegio_id=colegio.id, nombre="Director", es_director=True)
    db.add(rol)
    configuracion.crear_categorias_por_defecto(db, colegio.id)
    db.flush()
    clave = generar_clave_temporal()
    d = datos.director
    db.add(Usuario(
        colegio_id=colegio.id, tipo_documento=d.tipo_documento, numero_documento=d.numero_documento,
        usuario=d.numero_documento, nombres=d.nombres, apellidos=d.apellidos, rol_id=rol.id, clave_hash=hashear_clave(clave),
    ))
    db.commit()
    return ColegioCreado(colegio=_salida(colegio), director_usuario=d.numero_documento, director_clave_temporal=clave)


@router.patch("/colegios/{colegio_id}")
def editar(colegio_id: int, datos: CambioColegio, db: Session = Depends(get_db)) -> ColegioOut:
    colegio = db.get(Colegio, colegio_id)
    if colegio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Colegio no encontrado")
    cambios = datos.model_dump(exclude_unset=True)
    perfil, contratados = cambios.pop("perfil", None), cambios.pop("modulos_contratados", None)
    if perfil is not None:
        if campos := aplicar_perfil(colegio, datos.perfil):
            configuracion.registrar(db, colegio.id, QUIEN, "editar", "configuracion", "perfil", colegio.id,
                                    "Perfil del colegio: " + ", ".join(NOMBRE_CAMPO[c] for c in campos))
    if contratados is not None:
        nuevos = [m for m in CONTRATABLES if m in set(contratados)]
        if nuevos != [m for m in CONTRATABLES if m in (colegio.modulos_contratados or [])]:
            colegio.modulos_contratados = nuevos
            # Lo que se deja de contratar ya no figura como "apagado por el director".
            colegio.modulos_apagados = [m for m in (colegio.modulos_apagados or []) if m in nuevos]
            configuracion.registrar(db, colegio.id, QUIEN, "editar", "configuracion", "modulos", colegio.id,
                                    "Módulos contratados: " + (", ".join(MODULOS[m] for m in nuevos) or "ninguno"))
    for campo, valor in cambios.items():
        # dominio_propio y vence_en se pueden vaciar enviando null; el resto, no.
        if campo not in ("dominio_propio", "vence_en") and valor is None:
            continue
        setattr(colegio, campo, valor.strip() if campo == "nombre" else valor)
    try:
        _prueba_con_vencimiento(colegio.estado, colegio.vence_en)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflicto()
    return _salida(colegio)


# --- Pasar de prueba a activo ---------------------------------------------------------------

class Activacion(BaseModel):
    borrar_ejemplo: bool
    confirmar: str = Field(max_length=63)  # el subdominio, escrito a mano


@router.post("/colegios/{colegio_id}/activar")
def activar(colegio_id: int, d: Activacion, db: Session = Depends(get_db)) -> dict:
    """Un colegio en prueba pasa a activo. Si se pide, borra los datos de ejemplo (alumnos, apoderados,
    marcaciones, cuaderno y avisos) y conserva la estructura, turnos, calendario, roles, personal, imagen y
    configuración. Nunca la demo pública."""
    c = db.get(Colegio, colegio_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Colegio no encontrado")
    if c.es_demo:
        raise HTTPException(status.HTTP_409_CONFLICT, "La demo pública no se activa")
    if c.estado != "prueba":
        raise HTTPException(status.HTTP_409_CONFLICT, "Solo se activa un colegio en prueba")
    if d.confirmar.strip().lower() != c.subdominio:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Escribe el subdominio del colegio para confirmar")
    db.execute(text("SELECT pg_advisory_xact_lock(8, :c)"), {"c": c.id})
    borrados = activacion.borrar_datos_de_ejemplo(db, c) if d.borrar_ejemplo else {}
    c.estado, c.vence_en = "activo", None
    configuracion.registrar(db, c.id, QUIEN, "editar", "configuracion", "colegio", c.id,
                            "Colegio activado" + (" y datos de ejemplo borrados" if d.borrar_ejemplo else ""))
    db.commit()
    activacion.borrar_archivos(borrados.pop("_archivos", []))
    return {"colegio": _salida(c), "borrados": borrados}


# --- Demo con datos ficticios --------------------------------------------------------------

class NuevaDemo(BaseModel):
    subdominio: str = Field(default="demo", pattern=SUBDOMINIO)
    nombre: str = Field(default="Colegio Demo Tikray", min_length=1, max_length=200)
    alumnos_por_seccion: int = Field(default=24, ge=1, le=60)


def _demo(db: Session, subdominio: str, nombre: str, alumnos_por_seccion: int) -> dict:
    from app import demo

    try:
        r = demo.crear_o_reiniciar(db, subdominio, nombre, alumnos_por_seccion)
    except demo.NoEsDemo:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese subdominio es de un colegio real") from None
    return {"colegio": _salida(db.get(Colegio, r.colegio_id)), "alumnos": r.alumnos, "apoderados": r.apoderados,
            "personal": r.personal, "credenciales": r.credenciales}


@router.post("/demo", status_code=201)
def crear_demo(d: NuevaDemo, db: Session = Depends(get_db)) -> dict:
    """Crea el colegio demo (o lo reinicia si ya existe y es demo). Las credenciales son las de la demo."""
    if d.subdominio in SUBDOMINIOS_RESERVADOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Ese subdominio está reservado")
    return _demo(db, d.subdominio, d.nombre, d.alumnos_por_seccion)


@router.post("/colegios/{colegio_id}/reiniciar-demo")
def reiniciar_demo(colegio_id: int, db: Session = Depends(get_db)) -> dict:
    """Borra todo lo del colegio demo (lo que cargaron en la presentación) y lo vuelve a sembrar."""
    c = db.get(Colegio, colegio_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Colegio no encontrado")
    if not c.es_demo:
        raise HTTPException(status.HTTP_409_CONFLICT, "Solo se reinicia un colegio de demostración")
    return _demo(db, c.subdominio, c.nombre, 24)


@router.get("/resumen")
def resumen(db: Session = Depends(get_db)) -> dict:
    return {
        "colegios": db.scalar(select(func.count()).select_from(Colegio)),
        "por_estado": dict(db.execute(select(Colegio.estado, func.count()).group_by(Colegio.estado)).all()),
        "personal": db.scalar(select(func.count()).select_from(Usuario)),
    }
