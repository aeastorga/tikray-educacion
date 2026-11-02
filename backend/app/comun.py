"""Ayudas para las rutas: buscar dentro del colegio y guardar con errores claros."""

from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

T = TypeVar("T")


def obtener(db: Session, modelo: type[T], colegio_id: int, id_: int, nombre: str = "Registro") -> T:
    """Busca por id solo dentro del colegio: el de otro colegio da 404, igual que uno inexistente."""
    fila = db.scalar(select(modelo).where(modelo.id == id_, modelo.colegio_id == colegio_id))
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{nombre} no encontrado")
    return fila


def guardar(db: Session, repetido: str = "Ya existe un registro igual",
            en_uso: str = "No se puede borrar: está en uso", solo_flush: bool = False) -> None:
    """Commit (o flush, si aún falta trabajo en la misma transacción) que traduce
    las reglas de la base en respuestas 409."""
    try:
        db.flush() if solo_flush else db.commit()
    except IntegrityError as e:
        db.rollback()
        codigo = getattr(e.orig, "sqlstate", None)
        if codigo == "23503":  # foreign_key_violation
            raise HTTPException(status.HTTP_409_CONFLICT, en_uso) from None
        if codigo == "23505":  # unique_violation
            raise HTTPException(status.HTTP_409_CONFLICT, repetido) from None
        raise
