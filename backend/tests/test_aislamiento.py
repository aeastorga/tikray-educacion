"""Aislamiento entre colegios y entre tipos de token."""

import re

import pytest
from fastapi.routing import iter_route_contexts
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError

from app.db import Base, get_engine
from app.main import app
from app.models import Rol, Usuario
from tests.conftest import (auth, crear_admin, crear_colegio, crear_familia, crear_personal, host, token,
                            token_familia, token_plataforma)

# Globales a propósito: la cuenta de familia (y sus passkeys) une hijos de varios colegios.
SIN_COLEGIO = {"colegio", "admin_plataforma", "cuenta_familia", "passkey_familia"}
RUTAS_PUBLICAS = {"/api/auth/ingreso", "/api/publico/colegio", "/plataforma/auth/ingreso",
                  "/api/familia/ingreso", "/api/familia/activacion/revisar", "/api/familia/activacion/completar",
                  "/api/familia/passkey/opciones-ingreso", "/api/familia/passkey/ingreso"}
FAMILIA = "/api/familia/"


def _rutas(prefijo: str, excluir: str | None = None) -> list[tuple[str, str]]:
    salida = []
    for ctx in iter_route_contexts(app.routes):
        if not ctx.methods or not ctx.path.startswith(prefijo) or ctx.path in RUTAS_PUBLICAS:
            continue
        if excluir and ctx.path.startswith(excluir):
            continue
        ruta = re.sub(r"\{[^}]+\}", "1", ctx.path)
        salida += [(m, ruta) for m in ctx.methods if m != "HEAD"]
    assert salida, f"No se encontraron rutas bajo {prefijo}"
    return sorted(salida)


RUTAS_API = _rutas("/api/", excluir=FAMILIA)  # del personal
RUTAS_FAMILIA = _rutas(FAMILIA)
RUTAS_PLATAFORMA = _rutas("/plataforma/")


@pytest.fixture
def dos(db):
    return crear_colegio(db, "alfa"), crear_colegio(db, "beta")


# --- Esquema ---------------------------------------------------------------

def test_toda_tabla_tiene_colegio_id_con_llave_foranea():
    for tabla in Base.metadata.sorted_tables:
        if tabla.name in SIN_COLEGIO:
            continue
        assert "colegio_id" in tabla.c, f"{tabla.name} no tiene colegio_id"
        assert not tabla.c.colegio_id.nullable, f"{tabla.name}.colegio_id acepta NULL"
        destinos = {fk.column.table.name for fk in tabla.c.colegio_id.foreign_keys}
        assert "colegio" in destinos, f"{tabla.name}.colegio_id sin llave foránea a colegio"


def test_las_llaves_existen_en_la_base_migrada():
    insp = sa_inspect(get_engine())
    for tabla in Base.metadata.sorted_tables:
        if tabla.name in SIN_COLEGIO:
            continue
        fks = insp.get_foreign_keys(tabla.name)
        assert any(fk["referred_table"] == "colegio" and fk["constrained_columns"] == ["colegio_id"]
                   for fk in fks), f"Falta FK colegio_id en {tabla.name} (¿migración desactualizada?)"


def test_base_rechaza_colegio_inexistente(db):
    db.add(Rol(colegio_id=9999, nombre="Fantasma"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_base_rechaza_rol_de_otro_colegio(db, dos):
    a, b = dos
    rol_b = db.query(Rol).filter_by(colegio_id=b.id).first()
    db.add(Usuario(colegio_id=a.id, numero_documento="20000000", usuario="20000000", nombres="X", apellidos="Y",
                   rol_id=rol_b.id, clave_hash="x"))
    with pytest.raises(IntegrityError):
        db.commit()


# --- Host ------------------------------------------------------------------

@pytest.mark.parametrize("h", ["nadie.tikray.test", "www.tikray.test", "a.b.tikray.test", "tikray.test",
                               "otro-sitio.com"])
def test_host_desconocido_da_404(client, dos, h):
    assert client.get("/api/publico/colegio", headers={"Host": h}).status_code == 404


def test_dominio_propio(client, db):
    crear_colegio(db, "gamma", dominio_propio="colegiogamma.edu.pe")
    r = client.get("/api/publico/colegio", headers={"Host": "ColegioGamma.edu.pe:443"})
    assert r.status_code == 200 and r.json()["nombre"] == "Colegio gamma"


def test_colegio_suspendido_no_responde(client, db):
    c = crear_colegio(db, "alfa")
    tok = token(client, "alfa")
    c.estado = "suspendido"
    db.commit()
    assert client.get("/api/auth/yo", headers=auth("alfa", tok)).status_code == 403
    r = client.get("/api/publico/colegio", headers=host("alfa"))
    assert r.status_code == 403 and r.json()["detail"] == "El acceso a este colegio está suspendido"


# --- Token de un colegio en el Host de otro: 403 en todas las rutas ----------

@pytest.mark.parametrize("metodo,ruta", RUTAS_API)
def test_token_de_otro_colegio_da_403(client, dos, metodo, ruta):
    tok_alfa = token(client, "alfa")
    r = client.request(metodo, ruta, headers=auth("beta", tok_alfa))
    assert r.status_code == 403, (metodo, ruta, r.status_code)
    assert r.json()["detail"] == "El token no corresponde a este colegio"


@pytest.mark.parametrize("metodo,ruta", RUTAS_API)
def test_rutas_api_exigen_token(client, dos, metodo, ruta):
    assert client.request(metodo, ruta, headers=host("alfa")).status_code == 401


# --- Plataforma y colegio no se mezclan ------------------------------------

@pytest.mark.parametrize("metodo,ruta", RUTAS_API)
def test_token_plataforma_no_entra_a_colegio(client, db, dos, metodo, ruta):
    crear_admin(db)
    tok = token_plataforma(client)
    assert client.request(metodo, ruta, headers=auth("alfa", tok)).status_code == 401


@pytest.mark.parametrize("metodo,ruta", RUTAS_PLATAFORMA)
def test_token_colegio_no_entra_a_plataforma(client, dos, metodo, ruta):
    tok = token(client, "alfa")
    r = client.request(metodo, ruta, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401, (metodo, ruta, r.status_code)


@pytest.mark.parametrize("metodo,ruta", RUTAS_PLATAFORMA)
def test_plataforma_exige_token(client, metodo, ruta):
    assert client.request(metodo, ruta).status_code == 401


def test_director_no_entra_por_ingreso_de_plataforma(client, dos):
    r = client.post("/plataforma/auth/ingreso", json={"correo": "10000000", "clave": "ClaveBuena123"})
    assert r.status_code == 401


# --- Datos de otro colegio -------------------------------------------------

def test_listados_solo_del_propio_colegio(client, db, dos):
    a, b = dos
    crear_personal(db, b, "30000000", {"personal": "ver"})
    h = auth("alfa", token(client, "alfa"))
    personal = client.get("/api/personal", headers=h).json()
    assert [p["numero_documento"] for p in personal] == ["10000000"]
    roles = client.get("/api/roles", headers=h).json()
    assert [r["nombre"] for r in roles] == ["Director"]


def test_no_toca_recursos_de_otro_colegio_por_id(client, db, dos):
    a, b = dos
    otro = crear_personal(db, b, "30000000", {"personal": "ver"})
    h = auth("alfa", token(client, "alfa"))
    assert client.put(f"/api/roles/{otro.rol_id}", json={"nombre": "X"}, headers=h).status_code == 404
    assert client.delete(f"/api/roles/{otro.rol_id}", headers=h).status_code == 404
    assert client.post(f"/api/personal/{otro.id}/reiniciar-clave", headers=h).status_code == 404
    r = client.post("/api/personal", headers=h, json={
        "numero_documento": "40000000", "nombres": "N", "apellidos": "A", "rol_id": otro.rol_id})
    assert r.status_code == 422


def test_colegio_id_del_navegador_se_ignora(client, db, dos):
    a, b = dos
    h = auth("alfa", token(client, "alfa"))
    r = client.post("/api/roles", headers=h, json={"nombre": "Docente", "colegio_id": b.id})
    assert r.status_code == 201
    rol = db.get(Rol, r.json()["id"])
    assert rol.colegio_id == a.id


def test_mismo_dni_en_dos_colegios_son_cuentas_distintas(client, dos):
    tok_a, tok_b = token(client, "alfa"), token(client, "beta")
    yo_a = client.get("/api/auth/yo", headers=auth("alfa", tok_a)).json()
    yo_b = client.get("/api/auth/yo", headers=auth("beta", tok_b)).json()
    assert yo_a["apellidos"] == "alfa" and yo_b["apellidos"] == "beta"


# --- Familias: su propio token, también atado al colegio del Host ------------------

@pytest.mark.parametrize("metodo,ruta", RUTAS_FAMILIA)
def test_token_familia_de_otro_colegio_da_403(client, db, dos, metodo, ruta):
    a, b = dos
    crear_familia(db, a)
    crear_familia(db, b)  # la misma persona también es apoderada en beta
    tok = token_familia(client, "alfa")
    r = client.request(metodo, ruta, headers=auth("beta", tok))
    assert r.status_code == 403, (metodo, ruta, r.status_code)
    assert r.json()["detail"] == "El token no corresponde a este colegio"


@pytest.mark.parametrize("metodo,ruta", RUTAS_FAMILIA)
def test_rutas_familia_exigen_token_de_familia(client, db, dos, metodo, ruta):
    assert client.request(metodo, ruta, headers=host("alfa")).status_code == 401
    personal = token(client, "alfa")  # el token del personal no sirve como el de un padre
    assert client.request(metodo, ruta, headers=auth("alfa", personal)).status_code == 401


@pytest.mark.parametrize("metodo,ruta", RUTAS_API)
def test_token_familia_no_entra_a_rutas_del_personal(client, db, dos, metodo, ruta):
    crear_familia(db, dos[0])
    tok = token_familia(client, "alfa")
    assert client.request(metodo, ruta, headers=auth("alfa", tok)).status_code == 401
