"""Base para las pruebas de navegador (frontend/e2e): borra el esquema de
E2E_DATABASE_URL, aplica las migraciones y crea un colegio con datos ficticios.

    E2E_DATABASE_URL=postgresql+psycopg:///tikray_e2e python -m tests.e2e_semilla

Imprime en JSON lo que las pruebas necesitan (códigos de carnet, usuario).
"""

import json
import os
import sys
from datetime import UTC, date, datetime, time
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
from app.models.colegio import CONTRATABLES  # noqa: E402
from app.models import (Alumno, AlumnoApoderado, AnioEscolar, Apoderado, Colegio, CuentaFamilia,  # noqa: E402
                        Grado, Matricula, Nivel, Rol, Seccion, Turno, Usuario)
from app.seguridad import hashear_clave  # noqa: E402

SUBDOMINIO = "e2e"
ADMINISTRADOR = {"usuario": "40000001", "clave": "ClaveE2e2026"}
FAMILIA = {"documento": "41234567", "pin": "481937"}  # madre de Lucía, con la cuenta ya activada
ALUMNOS = [("QUISPE MAMANI", "Lucía", "LUCAAAAA"), ("HUAMAN TORRES", "Diego", "DGAAAAAA"),
           ("ROJAS PAREDES", "Ana", "ANAAAAAA")]
EXTRA_APODERADOS = 30


def main() -> None:
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(cfg, "head")

    hoy = hoy_lima()
    with get_sessionmaker()() as db:
        # Con todo contratado (pensiones y caja se contratan aparte), para probarlo en el navegador.
        c = Colegio(nombre="Colegio de Pruebas", subdominio=SUBDOMINIO, modulos_contratados=list(CONTRATABLES))
        db.add(c)
        db.flush()
        rol = Rol(colegio_id=c.id, nombre="Administrador", es_administrador=True)
        anio = AnioEscolar(colegio_id=c.id, anio=hoy.year, inicio=date(hoy.year, 1, 1), fin=date(hoy.year, 12, 31),
                           dias_semana="1234567", activo=True)
        nivel = Nivel(colegio_id=c.id, nombre="Primaria")
        turno = Turno(colegio_id=c.id, nombre="Mañana", hora_entrada=time(7, 45), tolerancia_minutos=10,
                      hora_salida=time(13, 0))
        db.add_all([rol, anio, nivel, turno])
        db.flush()
        db.add(Usuario(colegio_id=c.id, numero_documento=ADMINISTRADOR["usuario"], usuario=ADMINISTRADOR["usuario"],
                       nombres="Directora", apellidos="Pruebas", rol_id=rol.id,
                       clave_hash=hashear_clave(ADMINISTRADOR["clave"]), debe_cambiar_clave=False))
        grado = Grado(colegio_id=c.id, nivel_id=nivel.id, nombre="1°")
        db.add(grado)
        db.flush()
        sec = Seccion(colegio_id=c.id, anio_id=anio.id, grado_id=grado.id, turno_id=turno.id, nombre="A")
        db.add(sec)
        db.flush()
        alumnos = []
        for i, (apellidos, nombres, codigo) in enumerate(ALUMNOS):
            a = Alumno(colegio_id=c.id, numero_documento=f"7900000{i}", nombres=nombres, apellidos=apellidos,
                       codigo=codigo)
            db.add(a)
            db.flush()
            db.add(Matricula(colegio_id=c.id, anio_id=anio.id, alumno_id=a.id, seccion_id=sec.id))
            alumnos.append(a)
        cuenta = CuentaFamilia(tipo_documento="DNI", numero_documento=FAMILIA["documento"],
                               pin_hash=hashear_clave(FAMILIA["pin"]))
        db.add(cuenta)
        db.flush()
        madre = Apoderado(colegio_id=c.id, numero_documento=FAMILIA["documento"], nombres="Rosa", apellidos="Mamani",
                          celular="987654321", cuenta_id=cuenta.id, estado_acceso="activo", activado_en=datetime.now(UTC))
        db.add(madre)
        db.flush()
        db.add(AlumnoApoderado(colegio_id=c.id, alumno_id=alumnos[0].id, apoderado_id=madre.id, parentesco="Madre"))
        # Apoderados sin cuenta ni hijos: llenan más de una página en Cuentas de padres.
        db.add_all([Apoderado(colegio_id=c.id, numero_documento=f"4800{i:04d}", nombres="Carmen", apellidos=f"Zeta {i:02d}")
                    for i in range(EXTRA_APODERADOS)])
        db.commit()
    print(json.dumps({"subdominio": SUBDOMINIO, "administrador": ADMINISTRADOR, "familia": FAMILIA,
                      "alumnos": [{"nombre": f"{ap}, {no}", "codigo": co} for ap, no, co in ALUMNOS]}))


if __name__ == "__main__":
    main()
