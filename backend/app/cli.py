"""Comandos de administración.

    python -m app.cli crear-admin <correo> "<nombre>"
"""

import getpass
import sys

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import AdminPlataforma
from app.proteccion import motivos_clave
from app.seguridad import hashear_clave


def crear_admin(correo: str, nombre: str) -> None:
    correo = correo.strip().lower()
    clave = getpass.getpass("Clave: ")
    if motivos := motivos_clave(clave):
        sys.exit("La clave no cumple: " + ", ".join(motivos))
    if clave != getpass.getpass("Repite la clave: "):
        sys.exit("Las claves no coinciden")
    with get_sessionmaker()() as db:
        if db.scalar(select(AdminPlataforma).where(AdminPlataforma.correo == correo)):
            sys.exit("Ya existe un administrador con ese correo")
        db.add(AdminPlataforma(correo=correo, nombre=nombre, clave_hash=hashear_clave(clave)))
        db.commit()
    print(f"Administrador {correo} creado")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "crear-admin":
        crear_admin(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
