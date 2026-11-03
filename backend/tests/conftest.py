"""Pruebas contra PostgreSQL real (las llaves foráneas y CHECK son parte de lo que se prueba).

Usa TEST_DATABASE_URL (por defecto la base local `tikray_test`). El esquema se
crea con las migraciones de Alembic, así que también se prueban.
"""

import os
import tempfile

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg:///tikray_test")
os.environ["DATABASE_URL"] = TEST_DB
os.environ["SECRET_KEY"] = "clave-de-pruebas-" + "x" * 32
os.environ["DOMINIO_BASE"] = "tikray.test"
os.environ["TAREAS_EN_FONDO"] = "false"
os.environ["CARPETA_ARCHIVOS"] = tempfile.mkdtemp(prefix="tikray-archivos-")

from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import Base, get_engine, get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (AdminPlataforma, Alumno, AlumnoApoderado, Apoderado, Colegio, CuentaFamilia,  # noqa: E402
                        PermisoRol, Rol, Usuario)
from app.proteccion import limpiar_limites  # noqa: E402
from app.seguridad import hashear_clave  # noqa: E402

CLAVE = "ClaveBuena123"
_HASH = hashear_clave(CLAVE)
PIN = "481937"
_HASH_PIN = hashear_clave(PIN)


@pytest.fixture(scope="session", autouse=True)
def esquema():
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def limpiar():
    yield
    tablas = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tablas} RESTART IDENTITY CASCADE"))
    limpiar_limites()


@pytest.fixture
def db():
    with get_sessionmaker()() as s:
        yield s


@pytest.fixture
def client():
    return TestClient(app)


def host(sub: str) -> dict:
    return {"Host": f"{sub}.tikray.test"}


def crear_colegio(db, sub: str, **extra) -> Colegio:
    """Colegio con su rol Director y un director (usuario = DNI) que ya cambió la clave."""
    c = Colegio(nombre=f"Colegio {sub}", subdominio=sub, **extra)
    db.add(c)
    db.flush()
    rol = Rol(colegio_id=c.id, nombre="Director", es_director=True)
    db.add(rol)
    db.flush()
    db.add(Usuario(colegio_id=c.id, numero_documento="10000000", usuario="10000000", nombres="Dir", apellidos=sub,
                   rol_id=rol.id, clave_hash=_HASH, debe_cambiar_clave=False))
    db.commit()
    return c


def crear_personal(db, colegio: Colegio, dni: str, permisos: dict[str, str] | None = None,
                   debe_cambiar_clave: bool = False) -> Usuario:
    rol = Rol(colegio_id=colegio.id, nombre=f"Rol {dni}")
    rol.permisos = [PermisoRol(colegio_id=colegio.id, modulo=m, nivel=n) for m, n in (permisos or {}).items()]
    u = Usuario(colegio_id=colegio.id, numero_documento=dni, usuario=dni, nombres="P", apellidos=dni, rol=rol,
                clave_hash=_HASH, debe_cambiar_clave=debe_cambiar_clave)
    db.add(u)
    db.commit()
    return u


def token(client, sub: str, usuario: str = "10000000", clave: str = CLAVE) -> str:
    r = client.post("/api/auth/ingreso", json={"usuario": usuario, "clave": clave}, headers=host(sub))
    assert r.status_code == 200, r.text
    return r.json()["token"]


def auth(sub: str, tok: str) -> dict:
    return {**host(sub), "Authorization": f"Bearer {tok}"}


def crear_admin(db, correo: str = "admin@tikray.pe") -> AdminPlataforma:
    a = AdminPlataforma(correo=correo, nombre="Admin", clave_hash=_HASH)
    db.add(a)
    db.commit()
    return a


def token_plataforma(client, correo: str = "admin@tikray.pe") -> str:
    r = client.post("/plataforma/auth/ingreso", json={"correo": correo, "clave": CLAVE})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def crear_familia(db, colegio: Colegio, dni: str = "41234567", alumnos: list[Alumno] | None = None,
                  estado: str = "activo") -> Apoderado:
    """Apoderado con cuenta de familia (PIN = PIN) ya activada en el colegio. Reusa la cuenta si
    la persona ya tiene una (mismo DNI en otro colegio)."""
    from sqlalchemy import select

    cuenta = db.scalar(select(CuentaFamilia).where(CuentaFamilia.numero_documento == dni))
    if cuenta is None:
        cuenta = CuentaFamilia(tipo_documento="DNI", numero_documento=dni, pin_hash=_HASH_PIN)
        db.add(cuenta)
        db.flush()
    ap = Apoderado(colegio_id=colegio.id, numero_documento=dni, nombres="Rosa", apellidos="Mamani",
                   celular="987654321", cuenta_id=cuenta.id, estado_acceso=estado,
                   activado_en=datetime.now(UTC) if estado == "activo" else None)
    db.add(ap)
    db.flush()
    for a in alumnos or []:
        db.add(AlumnoApoderado(colegio_id=colegio.id, alumno_id=a.id, apoderado_id=ap.id, parentesco="Madre"))
    db.commit()
    return ap


def token_familia(client, sub: str, dni: str = "41234567", pin: str = PIN) -> str:
    r = client.post("/api/familia/ingreso", json={"documento": dni, "pin": pin}, headers=host(sub))
    assert r.status_code == 200, r.text
    return r.json()["token"]
