"""Comandos de administración.

    python -m app.cli crear-admin <correo> "<nombre>"
    python -m app.cli faltas [AAAA-MM-DD]
    python -m app.cli claves-push

`faltas` sin fecha hace lo mismo que el proceso del servidor (hoy, turnos cuyo
corte ya pasó). Con fecha cierra ese día completo, sin avisar a las familias:
sirve si el servidor estuvo caído.
"""

import getpass
import sys
from datetime import date, datetime

from sqlalchemy import select

from app import asistencia
from app.db import get_sessionmaker
from app.fechas import LIMA
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


def faltas(fecha: str | None) -> None:
    with get_sessionmaker()() as db:
        if fecha:
            n = asistencia.marcar_faltas(db, date.fromisoformat(fecha), avisar=False)
        else:
            ahora = datetime.now(LIMA)
            n = asistencia.marcar_faltas(db, ahora.date(), ahora.time().replace(tzinfo=None))
        db.commit()
    print(f"{n} faltas o licencias registradas")


def claves_push() -> None:
    """Par de llaves VAPID para Web Push. Se generan una vez y no se cambian: si cambian,
    todos los padres tienen que volver a aceptar las notificaciones."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02
    from py_vapid.utils import b64urlencode

    v = Vapid02()
    v.generate_keys()
    privada = b64urlencode(v.private_key.private_numbers().private_value.to_bytes(32, "big"))
    publica = b64urlencode(v.public_key.public_bytes(serialization.Encoding.X962,
                                                     serialization.PublicFormat.UncompressedPoint))
    print(f"VAPID_CLAVE_PRIVADA={privada}\nVAPID_CLAVE_PUBLICA={publica}")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "crear-admin":
        crear_admin(sys.argv[2], sys.argv[3])
    elif sys.argv[1:] == ["claves-push"]:
        claves_push()
    elif len(sys.argv) in (2, 3) and sys.argv[1] == "faltas":
        faltas(sys.argv[2] if len(sys.argv) == 3 else None)
    else:
        sys.exit(__doc__)
