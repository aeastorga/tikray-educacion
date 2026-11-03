"""Base para las pruebas de navegador (frontend/e2e): borra el esquema de
E2E_DATABASE_URL, aplica las migraciones y crea un colegio con datos ficticios.

    E2E_DATABASE_URL=postgresql+psycopg:///tikray_e2e python -m tests.e2e_semilla

Imprime en JSON lo que las pruebas necesitan (códigos de carnet, usuario).
"""

import json
import os
import sys
from datetime import date, time
from pathlib import Path

URL = os.environ.get("E2E_DATABASE_URL")
if not URL or not URL.rstrip("/").split("/")[-1].endswith("e2e"):
    sys.exit("E2E_DATABASE_URL debe apuntar a una base cuyo nombre termine en 'e2e' (se borra entera)")
os.environ["DATABASE_URL"] = URL
os.environ.setdefault("SECRET_KEY", "clave-de-pruebas-e2e-" + "x" * 32)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import get_engine, get_sessionmaker  # noqa: E402
from app.fechas import hoy_lima  # noqa: E402
from app.models import (Alumno, AnioEscolar, Colegio, Grado, Matricula, Nivel, Rol, Seccion, Turno,  # noqa: E402
                        Usuario)
from app.seguridad import hashear_clave  # noqa: E402

SUBDOMINIO = "e2e"
DIRECTOR = {"usuario": "40000001", "clave": "ClaveE2e2026"}
ALUMNOS = [("QUISPE MAMANI", "Lucía", "LUCAAAAA"), ("HUAMAN TORRES", "Diego", "DGAAAAAA"),
           ("ROJAS PAREDES", "Ana", "ANAAAAAA")]


def main() -> None:
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(cfg, "head")

    hoy = hoy_lima()
    with get_sessionmaker()() as db:
        c = Colegio(nombre="Colegio de Pruebas", subdominio=SUBDOMINIO)
        db.add(c)
        db.flush()
        rol = Rol(colegio_id=c.id, nombre="Director", es_director=True)
        anio = AnioEscolar(colegio_id=c.id, anio=hoy.year, inicio=date(hoy.year, 1, 1), fin=date(hoy.year, 12, 31),
                           dias_semana="1234567", activo=True)
        nivel = Nivel(colegio_id=c.id, nombre="Primaria")
        turno = Turno(colegio_id=c.id, nombre="Mañana", hora_entrada=time(7, 45), tolerancia_minutos=10,
                      hora_salida=time(13, 0))
        db.add_all([rol, anio, nivel, turno])
        db.flush()
        db.add(Usuario(colegio_id=c.id, numero_documento=DIRECTOR["usuario"], usuario=DIRECTOR["usuario"],
                       nombres="Directora", apellidos="Pruebas", rol_id=rol.id,
                       clave_hash=hashear_clave(DIRECTOR["clave"]), debe_cambiar_clave=False))
        grado = Grado(colegio_id=c.id, nivel_id=nivel.id, nombre="1°")
        db.add(grado)
        db.flush()
        sec = Seccion(colegio_id=c.id, anio_id=anio.id, grado_id=grado.id, turno_id=turno.id, nombre="A")
        db.add(sec)
        db.flush()
        for i, (apellidos, nombres, codigo) in enumerate(ALUMNOS):
            a = Alumno(colegio_id=c.id, numero_documento=f"7900000{i}", nombres=nombres, apellidos=apellidos,
                       codigo=codigo)
            db.add(a)
            db.flush()
            db.add(Matricula(colegio_id=c.id, anio_id=anio.id, alumno_id=a.id, seccion_id=sec.id))
        db.commit()
    print(json.dumps({"subdominio": SUBDOMINIO, "director": DIRECTOR,
                      "alumnos": [{"nombre": f"{ap}, {no}", "codigo": co} for ap, no, co in ALUMNOS]}))


if __name__ == "__main__":
    main()
