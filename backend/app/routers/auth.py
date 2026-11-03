from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import Sesion, colegio_del_host, usuario_actual, usuario_sesion
from app.models import Colegio, Usuario
from app.modulos import MODULOS
from app.proteccion import exigir_clave_valida, ip_cliente, permitir_intento, registrar_fallo
from app.seguridad import emitir_token, hashear_clave, verificar_clave, verificar_clave_o_simular

publico = APIRouter(prefix="/auth", tags=["auth"])
sesion = APIRouter(prefix="/auth", tags=["auth"])


class Ingreso(BaseModel):
    usuario: str = Field(min_length=1, max_length=60)
    clave: str = Field(min_length=1, max_length=200)


class CambioClave(BaseModel):
    clave_actual: str = Field(max_length=200)
    clave_nueva: str = Field(max_length=200)


class Token(BaseModel):
    token: str
    debe_cambiar_clave: bool


def _token(usuario: Usuario) -> Token:
    t = emitir_token(
        "colegio", usuario.id, usuario.version_sesion, get_settings().token_colegio_minutos,
        col=usuario.colegio_id,
    )
    return Token(token=t, debe_cambiar_clave=usuario.debe_cambiar_clave)


@publico.post("/ingreso")
def ingresar(
    datos: Ingreso, request: Request,
    colegio: Colegio = Depends(colegio_del_host), db: Session = Depends(get_db),
) -> Token:
    nombre = datos.usuario.strip()
    # Por cuenta (5) frena a quien prueba claves de un usuario; por IP (50), a quien prueba usuarios.
    cuenta, ip = f"colegio:{colegio.id}:{nombre}", f"colegio:{ip_cliente(request)}"
    if not permitir_intento(cuenta, ip):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o clave incorrectos")
    usuario = db.scalar(
        select(Usuario).where(Usuario.colegio_id == colegio.id, Usuario.usuario == nombre)
    )
    ok = verificar_clave_o_simular(datos.clave, usuario.clave_hash if usuario else None)
    if not ok or not usuario.activo:
        registrar_fallo(cuenta, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o clave incorrectos")
    return _token(usuario)


@sesion.post("/cambiar-clave")
def cambiar_clave(
    datos: CambioClave, s: Sesion = Depends(usuario_sesion), db: Session = Depends(get_db),
) -> Token:
    u = s.usuario
    if not verificar_clave(datos.clave_actual, u.clave_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La clave actual no es correcta")
    if datos.clave_nueva == datos.clave_actual:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La clave nueva debe ser distinta")
    exigir_clave_valida(datos.clave_nueva)
    u.clave_hash = hashear_clave(datos.clave_nueva)
    u.debe_cambiar_clave = False
    u.version_sesion += 1  # cierra las demás sesiones
    db.commit()
    return _token(u)


@sesion.get("/yo")
def yo(s: Sesion = Depends(usuario_sesion)) -> dict:
    u = s.usuario
    if u.rol.es_director:
        permisos = {m: "editar" for m in MODULOS}
    else:
        permisos = {p.modulo: p.nivel for p in u.rol.permisos}
    # Un módulo apagado no figura: desaparece del menú aunque el rol tenga permiso.
    permisos = {m: n for m, n in permisos.items() if s.colegio.modulo_activo(m)}
    return {
        "id": u.id,
        "usuario": u.usuario,
        "nombres": u.nombres,
        "apellidos": u.apellidos,
        "rol": u.rol.nombre,
        "es_director": u.rol.es_director,
        "debe_cambiar_clave": u.debe_cambiar_clave,
        "permisos": permisos,
    }


@sesion.post("/cerrar-sesiones", status_code=204)
def cerrar_sesiones(s: Sesion = Depends(usuario_actual), db: Session = Depends(get_db)) -> None:
    s.usuario.version_sesion += 1
    db.commit()
