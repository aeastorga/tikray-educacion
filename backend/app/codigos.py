"""Código del carnet del alumno: lo que lleva el QR.

Es aleatorio y no es el DNI, para no exponer el documento en el carnet y
para poder invalidar un carnet perdido sin tocar los datos del alumno.
"""

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I
LARGO = 8
PREFIJO_QR = "TK1:"  # versión del formato, para que la portería reconozca el carnet
PREFIJO_QR_PERSONAL = "TK1P:"


def aleatorio() -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(LARGO))


def leer_qr(texto: str) -> tuple[str | None, str] | None:
    """('alumno' | 'personal' | None, código) a partir de lo que leyó la cámara o el lector USB.
    Sin prefijo (código tecleado a mano) el tipo queda en None y se busca en ambos."""
    t = (texto or "").strip().upper()
    if t.startswith(PREFIJO_QR_PERSONAL):
        tipo, t = "personal", t[len(PREFIJO_QR_PERSONAL):]
    elif t.startswith(PREFIJO_QR):
        tipo, t = "alumno", t[len(PREFIJO_QR):]
    else:
        tipo = None
    if len(t) != LARGO or any(c not in ALFABETO for c in t):
        return None
    return tipo, t


def generar(db: Session, colegio_id: int, reservados: set[str] | None = None) -> str:
    """Código de alumno libre en el colegio. `reservados` son los ya asignados en esta misma operación."""
    from app.models import Alumno

    reservados = reservados if reservados is not None else set()
    while True:
        codigo = aleatorio()
        if codigo in reservados:
            continue
        if db.scalar(select(Alumno.id).where(Alumno.colegio_id == colegio_id, Alumno.codigo == codigo)) is None:
            reservados.add(codigo)
            return codigo


def contenido_qr(codigo: str, personal: bool = False) -> str:
    return (PREFIJO_QR_PERSONAL if personal else PREFIJO_QR) + codigo
