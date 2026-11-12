"""Etapa 5: panel del administrador, colegio demo reiniciable y sus endpoints en la plataforma."""

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
    token(client, "demo", c["administrador"]["usuario"], c["administrador"]["clave"])
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
    assert r.json()["credenciales"]["administrador"]["usuario"]

    r = client.post(f"/plataforma/colegios/{cid}/reiniciar-demo", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["colegio"]["id"] == cid

    real = crear_colegio(db, "real")
    assert client.post(f"/plataforma/colegios/{real.id}/reiniciar-demo", headers=h).status_code == 409
    assert client.post("/plataforma/demo", json={"subdominio": "real"}, headers=h).status_code == 409
    assert client.post("/plataforma/colegios/999999/reiniciar-demo", headers=h).status_code == 404
    assert _contar(db, Usuario, real.id) == 1
    # Un administrador de colegio no puede usar la plataforma.
    tok = token(client, "real")
    assert client.post(f"/plataforma/colegios/{cid}/reiniciar-demo",
                       headers={"Authorization": f"Bearer {tok}"}).status_code == 401


# --- Panel del administrador ----------------------------------------------------------------------

def test_panel_del_administrador_con_la_demo(db, client):
    r = demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=4)
    tok = token(client, "demo", r.credenciales["administrador"]["usuario"], r.credenciales["administrador"]["clave"])
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


def test_demo_trae_recojo_y_autorizaciones_sin_avisos(db):
    """Recojo seguro y autorizaciones no salen vacías en la demo, y esos datos no encolan ningún aviso."""
    from app import autorizaciones as reglas
    from app.fechas import hoy_lima
    from app.models import (AlumnoAutorizacion, Apoderado, AutorizacionRecojoDia, AutorizadoRecojo, Autorizacion,
                            ColaAviso, Recojo, RespuestaAutorizacion)

    demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=3)
    r = demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=3)  # reiniciar dos veces seguidas no falla
    cid, hoy = r.colegio_id, hoy_lima()
    hijo = db.scalar(select(Alumno).where(Alumno.colegio_id == cid).order_by(Alumno.id))

    # Recojo: autorizados (con el hijo de la familia de prueba), uno por hoy y recojos de días pasados.
    autorizados = db.scalars(select(AutorizadoRecojo).where(AutorizadoRecojo.colegio_id == cid)).all()
    assert autorizados and hijo.id in {x.alumno_id for x in autorizados}
    assert all(x.numero_documento.startswith("D") and x.foto_clave is None for x in autorizados)
    assert db.scalar(select(func.count()).select_from(AutorizacionRecojoDia).where(
        AutorizacionRecojoDia.colegio_id == cid, AutorizacionRecojoDia.fecha == hoy)) == 1
    recojos = db.scalars(select(Recojo).where(Recojo.colegio_id == cid)).all()
    assert recojos and all(x.fecha < hoy for x in recojos)
    assert 1 <= sum(x.fuera_de_lista for x in recojos) <= 3
    assert {x.tipo for x in recojos} >= {"apoderado", "autorizado", "otro"}
    # Cada recojo va con la salida que la demo ya tenía, a la misma hora.
    for x in recojos:
        salida = db.scalar(select(AsistenciaAlumno.salida).where(
            AsistenciaAlumno.colegio_id == cid, AsistenciaAlumno.alumno_id == x.alumno_id,
            AsistenciaAlumno.fecha == x.fecha))
        assert salida == x.momento

    # Autorizaciones: las cuatro, en sus estados.
    lista = {a.titulo: a for a in db.scalars(select(Autorizacion).where(Autorizacion.colegio_id == cid))}
    estados = {reglas.estado(a, hoy): a for a in lista.values()}
    assert set(estados) == {"publicada", "cerrada", "borrador", "anulada"} and len(lista) == 4
    publicada, cerrada = estados["publicada"], estados["cerrada"]
    assert estados["anulada"].anulado_motivo
    assert not db.scalar(select(func.count()).select_from(AlumnoAutorizacion).where(
        AlumnoAutorizacion.autorizacion_id == estados["borrador"].id))
    # La publicada: respuestas variadas, un cambio y el hijo de la familia de prueba sin responder.
    alumnos_publicada = reglas.alumnos_de(db, publicada)
    assert hijo.id in alumnos_publicada
    historial = db.scalars(select(RespuestaAutorizacion).where(
        RespuestaAutorizacion.autorizacion_id == publicada.id)).all()
    vig = reglas.vigentes(db, cid, [publicada.id])
    assert {r.autoriza for r in vig.values()} == {True, False}
    assert any(not r.autoriza and r.comentario for r in vig.values())
    assert len(historial) > len(vig)  # alguien cambió su respuesta
    assert (publicada.id, hijo.id) not in vig and len(vig) < len(alumnos_publicada)
    # A6 en todas: responde un apoderado del alumno que recibe avisos y tiene la cuenta activa.
    todas = db.scalars(select(RespuestaAutorizacion).where(RespuestaAutorizacion.colegio_id == cid)).all()
    assert all(reglas.puede_responder(db, cid, x.apoderado_id, x.alumno_id) for x in todas)
    assert all(db.get(Apoderado, x.apoderado_id).numero_documento == x.apoderado_documento for x in todas)
    # La cerrada: casi todas respondidas, antes de la fecha límite.
    resp_cerrada = reglas.vigentes(db, cid, [cerrada.id])
    assert len(resp_cerrada) >= len(reglas.alumnos_de(db, cerrada)) // 2
    assert all(x.respondido_en.astimezone(demo.LIMA).date() <= cerrada.fecha_limite for x in resp_cerrada.values())

    # Ningún aviso por estos datos: nada de autorizaciones y nada de días pasados (la demo solo simula hoy).
    assert not db.scalar(select(func.count()).select_from(ColaAviso).where(
        ColaAviso.colegio_id == cid, (ColaAviso.tipo == "autorizar") | (ColaAviso.fecha < hoy)))
