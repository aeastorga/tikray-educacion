"""Código del carnet del alumno: lo que lleva el QR.

Es aleatorio y no es el DNI, para no exponer el documento en el carnet y
para poder invalidar un carnet perdido sin tocar los datos del alumno.
"""

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alumno

ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I
LARGO = 8
PREFIJO_QR = "TK1:"  # versión del formato, para que la portería reconozca el carnet


def generar(db: Session, colegio_id: int, reservados: set[str] | None = None) -> str:
    """Código libre en el colegio. `reservados` son los ya asignados en esta misma operación."""
    reservados = reservados if reservados is not None else set()
    while True:
        codigo = "".join(secrets.choice(ALFABETO) for _ in range(LARGO))
        if codigo in reservados:
            continue
        if db.scalar(select(Alumno.id).where(Alumno.colegio_id == colegio_id, Alumno.codigo == codigo)) is None:
            reservados.add(codigo)
            return codigo


def contenido_qr(codigo: str) -> str:
    return PREFIJO_QR + codigo
