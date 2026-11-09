"""Límite de usuarios del personal según el plan del colegio (lo fija solo Tikray Labs).

Cuentan los usuarios del personal activos, incluido el administrador; los padres no. Un usuario
desactivado libera su cupo. Si Tikray Labs baja el límite por debajo de los activos, no se desactiva a
nadie: solo no se pueden agregar más hasta bajar.
"""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Colegio, Usuario


def mensaje(maximo: int) -> str:
    return f"Tu plan permite {maximo} usuarios. Para más, contacta a Tikray Labs"


def usuarios_activos(db: Session, colegio_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Usuario)
                     .where(Usuario.colegio_id == colegio_id, Usuario.activo)) or 0


def excede(db: Session, colegio_id: int, agregar: int) -> int | None:
    """El límite si sumar `agregar` activos lo pasa; None si cabe o no hay límite. Bloquea la fila del
    colegio hasta el fin de la transacción para que dos altas simultáneas no se cuelen."""
    maximo = db.scalar(select(Colegio.max_usuarios).where(Colegio.id == colegio_id).with_for_update())
    if maximo is None or agregar <= 0:
        return None
    return maximo if usuarios_activos(db, colegio_id) + agregar > maximo else None


def verificar_cupo(db: Session, colegio_id: int, agregar: int = 1) -> None:
    if (maximo := excede(db, colegio_id, agregar)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, mensaje(maximo))
