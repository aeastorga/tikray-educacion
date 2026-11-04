"""Etapa 5: panel del director, colegio demo reiniciable y sus endpoints en la plataforma."""

import pytest
from sqlalchemy import func, select

from app import demo
from app.models import Alumno, Apoderado, AsistenciaAlumno, Colegio, CuentaFamilia, EntradaCuaderno, Usuario
from tests.conftest import (auth, crear_admin, crear_colegio, crear_familia, crear_personal, host, token,
                            token_plataforma)


def _contar(db, modelo, cid):
    return db.scalar(select(func.count()).select_from(modelo).where(modelo.colegio_id == cid))


# --- Demo -----------------------------------------------------------------------------------

def test_demo_crea_y_reinicia_sin_duplicar(db):
    r = demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=3)
    cid = r.colegio_id
    assert db.get(Colegio, cid).es_demo
    assert r.alumnos == _contar(db, Alumno, cid) == 25 * 3
    assert _contar(db, AsistenciaAlumno, cid) > 0
    assert _contar(db, EntradaCuaderno, cid) > 0
    cuentas = db.scalar(select(func.count()).select_from(CuentaFamilia).where(
        CuentaFamilia.numero_documento.like(f"D{cid:03d}P%")))
    assert cuentas > 0

    # Lo que se cargó durante la presentación desaparece con el reinicio.
    db.add(Alumno(colegio_id=cid, numero_documento="77777777", nombres="Extra", apellidos="Demo",
                  codigo="ZZZZZZZZ"))
    db.commit()
    r2 = demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=3)
    assert r2.colegio_id == cid
    assert _contar(db, Alumno, cid) == 25 * 3
    assert db.scalar(select(func.count()).select_from(CuentaFamilia).where(
        CuentaFamilia.numero_documento.like(f"D{cid:03d}P%"))) == cuentas


def test_demo_no_toca_un_colegio_real_ni_a_otros(db):
    real = crear_colegio(db, "real")
    crear_familia(db, real)
    with pytest.raises(demo.NoEsDemo):
        demo.crear_o_reiniciar(db, "real")
    db.rollback()
    with pytest.raises(demo.NoEsDemo):
        demo.borrar_datos(db, db.get(Colegio, real.id))
    db.rollback()

    demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=2)
    demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=2)
    assert _contar(db, Usuario, real.id) == 1
    assert _contar(db, Apoderado, real.id) == 1
    assert db.scalar(select(func.count()).select_from(CuentaFamilia).where(
        CuentaFamilia.numero_documento == "41234567")) == 1


def test_credenciales_de_la_demo_funcionan(db, client):
    r = demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=2)
    c = r.credenciales
    token(client, "demo", c["director"]["usuario"], c["director"]["clave"])
    token(client, "demo", c["porteria"]["usuario"], c["porteria"]["clave"])
    tok = token(client, "demo", c["docente"]["usuario"], c["docente"]["clave"])
    # El docente solo ve su sección en el cuaderno.
    secciones = client.get("/api/cuaderno/opciones", headers=auth("demo", tok)).json()["secciones"]
    assert len(secciones) == 1
    f = client.post("/api/familia/ingreso", json={"documento": c["familia"]["documento"], "pin": c["familia"]["pin"]},
                    headers=host("demo"))
    assert f.status_code == 200, f.text


# --- Endpoints de la plataforma --------------------------------------------------------------

def test_plataforma_crea_y_reinicia_la_demo(db, client):
    crear_admin(db)
    h = {"Authorization": f"Bearer {token_plataforma(client)}"}
    assert client.post("/plataforma/demo", json={}).status_code == 401
    r = client.post("/plataforma/demo", json={"subdominio": "muestra", "alumnos_por_seccion": 1}, headers=h)
    assert r.status_code == 201, r.text
    cid = r.json()["colegio"]["id"]
    assert r.json()["colegio"]["es_demo"] is True
    assert r.json()["credenciales"]["director"]["usuario"]

    r = client.post(f"/plataforma/colegios/{cid}/reiniciar-demo", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["colegio"]["id"] == cid

    real = crear_colegio(db, "real")
    assert client.post(f"/plataforma/colegios/{real.id}/reiniciar-demo", headers=h).status_code == 409
    assert client.post("/plataforma/demo", json={"subdominio": "real"}, headers=h).status_code == 409
    assert client.post("/plataforma/colegios/999999/reiniciar-demo", headers=h).status_code == 404
    assert _contar(db, Usuario, real.id) == 1
    # Un director de colegio no puede usar la plataforma.
    tok = token(client, "real")
    assert client.post(f"/plataforma/colegios/{cid}/reiniciar-demo",
                       headers={"Authorization": f"Bearer {tok}"}).status_code == 401


# --- Panel del director ----------------------------------------------------------------------

def test_panel_del_director_con_la_demo(db, client):
    r = demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=4)
    tok = token(client, "demo", r.credenciales["director"]["usuario"], r.credenciales["director"]["clave"])
    p = client.get("/api/panel/resumen", headers=auth("demo", tok))
    assert p.status_code == 200, p.text
    d = p.json()
    assert d["asistencia"]["alumnos"] == 100
    assert len(d["asistencia"]["tendencia"]) == 10
    assert any(t["registrados"] for t in d["asistencia"]["tendencia"])
    assert d["cuaderno"]["por_aprobar"]
    assert d["familias"]["apoderados"] > 0 and d["familias"]["activos"] > 0
    assert d["personal_activo"] == r.personal


def test_panel_muestra_solo_los_modulos_permitidos(db, client):
    c = crear_colegio(db, "a")
    crear_personal(db, c, "20000000", {"asistencia": "ver"})
    crear_personal(db, c, "30000000", {})
    d = client.get("/api/panel/resumen", headers=auth("a", token(client, "a", "20000000"))).json()
    assert "asistencia" in d and "cuaderno" not in d and "familias" not in d and "personal_activo" not in d
    d = client.get("/api/panel/resumen", headers=auth("a", token(client, "a", "30000000"))).json()
    assert set(d) == {"fecha", "colegio"}
    assert client.get("/api/panel/resumen", headers=host("a")).status_code == 401


def test_panel_no_mezcla_colegios(db, client):
    demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=2)
    crear_colegio(db, "b")
    d = client.get("/api/panel/resumen", headers=auth("b", token(client, "b"))).json()
    assert d["asistencia"]["alumnos"] == 0
    assert d["familias"]["apoderados"] == 0
    assert d["cuaderno"]["firmas"] == [] and d["cuaderno"]["por_aprobar"] == {}
    assert all(t["registrados"] == 0 for t in d["asistencia"]["tendencia"])


# --- Prueba de carga (versión corta, contra la app en proceso) --------------------------------

def test_prueba_de_carga_corta(db, client):
    from app import carga

    demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=2)
    cab = carga.ingresar(client, host("demo"), "90000004", demo.CLAVE)
    lista = carga.codigos(client, cab)
    assert len(lista) == 50
    res = carga.ejecutar(client, cab, lista, total=60, segundos=0, porterias=3)
    assert len(res.latencias_ms) == 60 and not res.errores, res.informe()
    # 50 entradas y 10 segundas lecturas (duplicado o salida, según la hora); ninguna se pierde.
    assert sum(res.resultados.values()) == 60
    assert res.informe().startswith("Marcaciones: 60 ")


def test_cuaderno_de_la_demo_en_hora_escolar(db):
    """Nada de entradas a las 2 a. m.: lo que escribe el colegio cae entre 7:00 a. m. y 5:00 p. m. de Lima."""
    from datetime import time

    from app.fechas import LIMA
    from app.models import EntradaCuaderno
    r = demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=2)
    horas = [e.creado_en.astimezone(LIMA).time() for e in db.scalars(
        select(EntradaCuaderno).where(EntradaCuaderno.colegio_id == r.colegio_id))]
    assert horas and all(time(7) <= h <= time(17) for h in horas), sorted(horas)
