from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Sesion, requerir_permiso
from app.models import Rol, Usuario
from app.proteccion import generar_clave_temporal
from app.seguridad import hashear_clave

router = APIRouter(prefix="/personal", tags=["personal"])

DNI = r"^\d{8}$"


class NuevoPersonal(BaseModel):
    dni: str = Field(pattern=DNI)
    nombres: str = Field(min_length=1, max_length=120)
    apellidos: str = Field(min_length=1, max_length=120)
    rol_id: int
    usuario: str | None = Field(default=None, max_length=60)  # por defecto, el DNI


class PersonalOut(BaseModel):
    id: int
    dni: str
    usuario: str
    nombres: str
    apellidos: str
    rol_id: int
    rol: str
    activo: bool
    debe_cambiar_clave: bool


class ConClaveTemporal(BaseModel):
    personal: PersonalOut
    clave_temporal: str  # se muestra una sola vez


def _salida(u: Usuario) -> PersonalOut:
    return PersonalOut(
        id=u.id, dni=u.dni, usuario=u.usuario, nombres=u.nombres, apellidos=u.apellidos,
        rol_id=u.rol_id, rol=u.rol.nombre, activo=u.activo, debe_cambiar_clave=u.debe_cambiar_clave,
    )


def _persona(db: Session, colegio_id: int, usuario_id: int) -> Usuario:
    u = db.scalar(select(Usuario).where(Usuario.id == usuario_id, Usuario.colegio_id == colegio_id))
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona no encontrada")
    return u


@router.get("")
def listar(s: Sesion = Depends(requerir_permiso("personal")), db: Session = Depends(get_db)) -> list[PersonalOut]:
    filas = db.scalars(
        select(Usuario).where(Usuario.colegio_id == s.colegio.id).order_by(Usuario.apellidos, Usuario.nombres)
    )
    return [_salida(u) for u in filas]


@router.post("", status_code=201)
def crear(
    datos: NuevoPersonal,
    s: Sesion = Depends(requerir_permiso("personal", "editar")), db: Session = Depends(get_db),
) -> ConClaveTemporal:
    rol = db.scalar(select(Rol).where(Rol.id == datos.rol_id, Rol.colegio_id == s.colegio.id))
    if rol is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Rol no encontrado")
    if rol.es_director and not s.usuario.rol.es_director:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el director asigna el rol de director")
    clave = generar_clave_temporal()
    u = Usuario(
        colegio_id=s.colegio.id, dni=datos.dni, usuario=(datos.usuario or datos.dni).strip(),
        nombres=datos.nombres.strip(), apellidos=datos.apellidos.strip(), rol=rol,
        clave_hash=hashear_clave(clave), debe_cambiar_clave=True,
    )
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe personal con ese DNI o usuario")
    return ConClaveTemporal(personal=_salida(u), clave_temporal=clave)


@router.post("/{usuario_id}/reiniciar-clave")
def reiniciar_clave(
    usuario_id: int,
    s: Sesion = Depends(requerir_permiso("personal", "editar")), db: Session = Depends(get_db),
) -> ConClaveTemporal:
    u = _persona(db, s.colegio.id, usuario_id)
    if u.rol.es_director and not s.usuario.rol.es_director:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el director reinicia la clave de un director")
    clave = generar_clave_temporal()
    u.clave_hash = hashear_clave(clave)
    u.debe_cambiar_clave = True
    u.version_sesion += 1
    db.commit()
    return ConClaveTemporal(personal=_salida(u), clave_temporal=clave)
