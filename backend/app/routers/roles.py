from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import configuracion
from app.db import get_db
from app.deps import Sesion, requerir_permiso
from app.models import PermisoRol, Rol, Usuario
from app.modulos import MODULOS, NIVELES

router = APIRouter(prefix="/roles", tags=["roles"])


class DatosRol(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    permisos: dict[str, str] = {}
    # Cuaderno: solo ve y escribe lo de las secciones a su cargo (docente, tutor).
    solo_sus_secciones: bool = False
    # Caja: anular pagos de caja cerrada y gastos de días anteriores (el director siempre puede).
    puede_anular_caja: bool = False

    @field_validator("permisos")
    @classmethod
    def _validar(cls, v: dict[str, str]) -> dict[str, str]:
        for modulo, nivel in v.items():
            if modulo not in MODULOS:
                raise ValueError(f"Módulo desconocido: {modulo}")
            if nivel not in NIVELES:
                raise ValueError(f"Nivel no válido para {modulo}: {nivel}")
        return v


class RolOut(BaseModel):
    id: int
    nombre: str
    es_director: bool
    permisos: dict[str, str]
    solo_sus_secciones: bool
    puede_anular_caja: bool


def _salida(r: Rol) -> RolOut:
    permisos = {m: "editar" for m in MODULOS} if r.es_director else {p.modulo: p.nivel for p in r.permisos}
    return RolOut(id=r.id, nombre=r.nombre, es_director=r.es_director, permisos=permisos,
                  solo_sus_secciones=r.solo_sus_secciones and not r.es_director,
                  puede_anular_caja=r.puede_anular_caja and not r.es_director)


def _rol(db: Session, colegio_id: int, rol_id: int) -> Rol:
    rol = db.scalar(select(Rol).where(Rol.id == rol_id, Rol.colegio_id == colegio_id))
    if rol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rol no encontrado")
    return rol


def _guardar(db: Session, rol: Rol, s: Sesion, accion: str) -> None:
    """Guarda el rol y su línea del historial en la misma transacción."""
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un rol con ese nombre") from None
    permisos = ", ".join(f"{MODULOS.get(p.modulo, p.modulo)} ({p.nivel})" for p in rol.permisos) or "sin permisos"
    configuracion.registrar(db, s.colegio.id, s.usuario, accion, "roles", "rol", rol.id,
                            f"Rol «{rol.nombre}»: {permisos}{' · solo sus secciones' if rol.solo_sus_secciones else ''}"
                            f"{' · puede anular pagos y gastos pasados' if rol.puede_anular_caja else ''}")
    db.commit()


@router.get("/modulos")
def modulos(_: Sesion = Depends(requerir_permiso("roles"))) -> dict[str, str]:
    return MODULOS


@router.get("")
def listar(s: Sesion = Depends(requerir_permiso("roles")), db: Session = Depends(get_db)) -> list[RolOut]:
    roles = db.scalars(select(Rol).where(Rol.colegio_id == s.colegio.id).order_by(Rol.nombre))
    return [_salida(r) for r in roles]


@router.post("", status_code=201)
def crear(
    datos: DatosRol, s: Sesion = Depends(requerir_permiso("roles", "editar")), db: Session = Depends(get_db),
) -> RolOut:
    rol = Rol(colegio_id=s.colegio.id, nombre=datos.nombre.strip(), solo_sus_secciones=datos.solo_sus_secciones,
              puede_anular_caja=datos.puede_anular_caja)
    rol.permisos = [PermisoRol(colegio_id=s.colegio.id, modulo=m, nivel=n) for m, n in datos.permisos.items()]
    db.add(rol)
    _guardar(db, rol, s, "crear")
    return _salida(rol)


@router.put("/{rol_id}")
def editar(
    rol_id: int, datos: DatosRol,
    s: Sesion = Depends(requerir_permiso("roles", "editar")), db: Session = Depends(get_db),
) -> RolOut:
    rol = _rol(db, s.colegio.id, rol_id)
    if rol.es_director:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El rol del director no se modifica")
    rol.nombre, rol.solo_sus_secciones = datos.nombre.strip(), datos.solo_sus_secciones
    rol.puede_anular_caja = datos.puede_anular_caja
    rol.permisos = [PermisoRol(colegio_id=s.colegio.id, modulo=m, nivel=n) for m, n in datos.permisos.items()]
    _guardar(db, rol, s, "editar")
    return _salida(rol)


@router.delete("/{rol_id}", status_code=204)
def borrar(
    rol_id: int, s: Sesion = Depends(requerir_permiso("roles", "editar")), db: Session = Depends(get_db),
) -> None:
    rol = _rol(db, s.colegio.id, rol_id)
    if rol.es_director:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El rol del director no se borra")
    if db.scalar(select(Usuario.id).where(Usuario.colegio_id == s.colegio.id, Usuario.rol_id == rol.id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Hay personal con este rol")
    configuracion.registrar(db, s.colegio.id, s.usuario, "anular", "roles", "rol", rol.id, f"Borró el rol «{rol.nombre}»")
    db.delete(rol)
    db.commit()
