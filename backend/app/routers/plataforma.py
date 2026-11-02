"""Panel de Tikray Labs: /plataforma.

Usa su propio token ("plataforma") y su propia tabla de usuarios. Un token de
colegio nunca entra aquí, y un token de plataforma nunca entra a /api.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import SUBDOMINIOS_RESERVADOS, admin_plataforma
from app.models import AdminPlataforma, Colegio, Rol, Usuario
from app.proteccion import FALLOS_PLATAFORMA, generar_clave_temporal
from app.seguridad import emitir_token, hashear_clave, verificar_clave_o_simular

publico = APIRouter(prefix="/plataforma", tags=["plataforma"])
router = APIRouter(prefix="/plataforma", tags=["plataforma"], dependencies=[Depends(admin_plataforma)])

SUBDOMINIO = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"


class Ingreso(BaseModel):
    correo: str = Field(max_length=254)
    clave: str = Field(max_length=200)


class Director(BaseModel):
    dni: str = Field(pattern=r"^\d{8}$")
    nombres: str = Field(min_length=1, max_length=120)
    apellidos: str = Field(min_length=1, max_length=120)


def _dominio(v: str | None) -> str | None:
    return v.strip().lower().rstrip(".") or None if v else None


class NuevoColegio(BaseModel):
    nombre: str = Field(min_length=1, max_length=200)
    subdominio: str = Field(pattern=SUBDOMINIO)
    dominio_propio: str | None = Field(default=None, max_length=253)
    director: Director

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
    activo: bool | None = None

    _norm_dominio = field_validator("dominio_propio")(classmethod(lambda cls, v: _dominio(v)))


class ColegioOut(BaseModel):
    id: int
    nombre: str
    subdominio: str
    dominio_propio: str | None
    activo: bool


class ColegioCreado(BaseModel):
    colegio: ColegioOut
    director_usuario: str
    director_clave_temporal: str  # se muestra una sola vez


def _salida(c: Colegio) -> ColegioOut:
    return ColegioOut(id=c.id, nombre=c.nombre, subdominio=c.subdominio,
                      dominio_propio=c.dominio_propio, activo=c.activo)


def _conflicto() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "El subdominio o dominio ya está en uso")


@publico.post("/auth/ingreso")
def ingresar(datos: Ingreso, request: Request, db: Session = Depends(get_db)) -> dict:
    correo = datos.correo.strip().lower()
    ip = request.client.host if request.client else "?"
    claves = (f"c:{correo}", f"ip:{ip}")
    if not all(FALLOS_PLATAFORMA.hay_cupo(k) for k in claves):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales incorrectas")
    admin = db.scalar(select(AdminPlataforma).where(AdminPlataforma.correo == correo))
    ok = verificar_clave_o_simular(datos.clave, admin.clave_hash if admin else None)
    if not ok or not admin.activo:
        for k in claves:
            FALLOS_PLATAFORMA.registrar(k)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales incorrectas")
    token = emitir_token("plataforma", admin.id, admin.version_sesion, get_settings().token_plataforma_minutos)
    return {"token": token, "nombre": admin.nombre}


@router.get("/colegios")
def listar(db: Session = Depends(get_db)) -> list[ColegioOut]:
    return [_salida(c) for c in db.scalars(select(Colegio).order_by(Colegio.nombre))]


@router.post("/colegios", status_code=201)
def crear(datos: NuevoColegio, db: Session = Depends(get_db)) -> ColegioCreado:
    colegio = Colegio(nombre=datos.nombre.strip(), subdominio=datos.subdominio,
                      dominio_propio=datos.dominio_propio)
    db.add(colegio)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _conflicto()
    rol = Rol(colegio_id=colegio.id, nombre="Director", es_director=True)
    db.add(rol)
    db.flush()
    clave = generar_clave_temporal()
    d = datos.director
    db.add(Usuario(
        colegio_id=colegio.id, dni=d.dni, usuario=d.dni, nombres=d.nombres.strip(),
        apellidos=d.apellidos.strip(), rol_id=rol.id, clave_hash=hashear_clave(clave),
    ))
    db.commit()
    return ColegioCreado(colegio=_salida(colegio), director_usuario=d.dni, director_clave_temporal=clave)


@router.patch("/colegios/{colegio_id}")
def editar(colegio_id: int, datos: CambioColegio, db: Session = Depends(get_db)) -> ColegioOut:
    colegio = db.get(Colegio, colegio_id)
    if colegio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Colegio no encontrado")
    cambios = datos.model_dump(exclude_unset=True)
    for campo, valor in cambios.items():
        if campo != "dominio_propio" and valor is None:
            continue
        setattr(colegio, campo, valor.strip() if campo == "nombre" else valor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflicto()
    return _salida(colegio)


@router.get("/resumen")
def resumen(db: Session = Depends(get_db)) -> dict:
    return {
        "colegios": db.scalar(select(func.count()).select_from(Colegio)),
        "colegios_activos": db.scalar(select(func.count()).select_from(Colegio).where(Colegio.activo)),
        "personal": db.scalar(select(func.count()).select_from(Usuario)),
    }
