"""Resolución del colegio por Host y control de acceso.

Toda ruta de colegio cuelga de un router que depende de `colegio_del_host`.
Las privadas además dependen de `usuario_actual`, que exige que el
`colegio_id` del token sea el mismo colegio del Host (si no, 403).
`tests/test_aislamiento.py` recorre todas las rutas para comprobarlo.
"""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.fechas import hoy_lima
from app.models import AdminPlataforma, Apoderado, Colegio, CuentaFamilia, Usuario
from app.modulos import NIVELES
from app.seguridad import leer_token

SUBDOMINIOS_RESERVADOS = {"www", "api", "admin", "plataforma", "app", "static", "mail"}

_bearer = HTTPBearer(auto_error=False)


def _host(request: Request) -> str:
    return request.headers.get("host", "").split(":")[0].strip().lower().rstrip(".")


def colegio_del_host(request: Request, db: Session = Depends(get_db)) -> Colegio:
    host = _host(request)
    base = get_settings().dominio_base.lower()
    colegio = None
    if host.endswith("." + base):
        sub = host[: -len(base) - 1]
        if sub and "." not in sub and sub not in SUBDOMINIOS_RESERVADOS:
            colegio = db.scalar(select(Colegio).where(Colegio.subdominio == sub))
    elif host:
        colegio = db.scalar(select(Colegio).where(func.lower(Colegio.dominio_propio) == host))
    if colegio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Colegio no encontrado")
    if not colegio.disponible(hoy_lima()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El acceso a este colegio está suspendido")
    return colegio


def _no_autenticado() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Sesión no válida", headers={"WWW-Authenticate": "Bearer"},
    )


@dataclass
class Sesion:
    colegio: Colegio
    usuario: Usuario


def usuario_sesion(
    colegio: Colegio = Depends(colegio_del_host),
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Sesion:
    """Sesión válida del colegio del Host, aunque tenga pendiente el cambio de clave."""
    datos = leer_token("colegio", cred.credentials) if cred else None
    if datos is None:
        raise _no_autenticado()
    if datos.get("col") != colegio.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El token no corresponde a este colegio")
    usuario = db.scalar(
        select(Usuario).where(Usuario.id == int(datos["sub"]), Usuario.colegio_id == colegio.id)
    )
    if usuario is None or not usuario.activo or usuario.version_sesion != datos["ver"]:
        raise _no_autenticado()
    return Sesion(colegio=colegio, usuario=usuario)


def usuario_actual(sesion: Sesion = Depends(usuario_sesion)) -> Sesion:
    if sesion.usuario.debe_cambiar_clave:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Debe cambiar su clave temporal")
    return sesion


def tiene_permiso(usuario: Usuario, modulo: str, nivel: str) -> bool:
    if usuario.rol.es_director:
        return True
    for p in usuario.rol.permisos:
        if p.modulo == modulo:
            return NIVELES.index(p.nivel) >= NIVELES.index(nivel)
    return False


def _modulo_apagado() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, "Este módulo no está activo en el colegio")


def puede(sesion: Sesion, modulo: str, nivel: str = "ver") -> bool:
    """El módulo está activo en el colegio y el rol tiene el permiso (el director, todos los activos)."""
    return sesion.colegio.modulo_activo(modulo) and tiene_permiso(sesion.usuario, modulo, nivel)


def requerir_permiso(modulo: str, nivel: str = "ver"):
    def dependencia(sesion: Sesion = Depends(usuario_actual)) -> Sesion:
        # Un módulo apagado no se usa aunque el rol tenga el permiso (ni el director).
        if not sesion.colegio.modulo_activo(modulo):
            raise _modulo_apagado()
        if not tiene_permiso(sesion.usuario, modulo, nivel):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso para este módulo")
        return sesion

    return dependencia


def modulo_encendido(modulo: str):
    """Para rutas de la familia o públicas de un módulo contratable: 403 si el colegio lo apagó."""
    def dependencia(colegio: Colegio = Depends(colegio_del_host)) -> Colegio:
        if not colegio.modulo_activo(modulo):
            raise _modulo_apagado()
        return colegio

    return dependencia


def solo_director(sesion: Sesion = Depends(usuario_actual)) -> Sesion:
    if not sesion.usuario.rol.es_director:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el director")
    return sesion


def admin_plataforma(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AdminPlataforma:
    datos = leer_token("plataforma", cred.credentials) if cred else None
    if datos is None:
        raise _no_autenticado()
    admin = db.get(AdminPlataforma, int(datos["sub"]))
    if admin is None or not admin.activo or admin.version_sesion != datos["ver"]:
        raise _no_autenticado()
    return admin


# --- Familias ----------------------------------------------------------------

@dataclass
class SesionFamilia:
    colegio: Colegio
    cuenta: CuentaFamilia
    apoderado: Apoderado  # el de este colegio (por cuya dirección entró)


def familia_sesion(
    colegio: Colegio = Depends(colegio_del_host),
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> SesionFamilia:
    """Padre o apoderado con sesión en el colegio del Host. Como el personal: el token de
    otro colegio da 403. El colegio puede cerrar sus sesiones o bloquearlo en cualquier momento."""
    datos = leer_token("familia", cred.credentials) if cred else None
    if datos is None:
        raise _no_autenticado()
    if datos.get("col") != colegio.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El token no corresponde a este colegio")
    ap = db.scalar(select(Apoderado).where(Apoderado.colegio_id == colegio.id, Apoderado.id == datos.get("apo"),
                                           Apoderado.cuenta_id == int(datos["sub"])))
    if ap is None or ap.estado_acceso not in ("activo", "pendiente") or ap.version_sesion != datos["ver"]:
        raise _no_autenticado()
    return SesionFamilia(colegio=colegio, cuenta=db.get(CuentaFamilia, ap.cuenta_id), apoderado=ap)
