"""Datos nuevos del rediseño: llegadas por tramo, última marcación, detalle del personal, permisos de
salida del día, contadores del menú, tarjeta y asistencia del mes de la familia, menú claro u oscuro.
Todo con el colegio del token: nada de otro colegio se cuela."""

import uuid
from datetime import time, timedelta

from app import asistencia
from app.routers import panel
from app.codigos import contenido_qr
from app.models import AsistenciaAlumno, EntradaCuaderno, LicenciaPersonal, Turno
from tests.conftest import auth, crear_familia, crear_personal, host, hoy, token, token_familia
from tests.test_asistencia import en, preparar


def _reloj(monkeypatch, hh, mm):
    """Fija la hora de Lima que ve el panel (el día sigue siendo hoy)."""
    monkeypatch.setattr(panel, "ahora_lima", lambda: en(hoy(), hh, mm))


def _marcar(db, e, alumno, hh, mm, equipo=None, dia=None, personal=None):
    dia = dia or hoy()
    lectura = asistencia.Lectura(id_cliente=uuid.uuid4().hex, momento=en(dia, hh, mm), origen="qr",
                                 codigo=None if personal else contenido_qr(alumno.codigo),
                                 usuario_id=personal.id if personal else None, equipo=equipo)
    r = asistencia.registrar(db, e.colegio.id, lectura, None, ahora=en(dia, hh, mm) + timedelta(minutes=1))
    db.commit()
    return r


def _panel(client, sub="uno"):
    r = client.get("/api/panel/resumen", headers=auth(sub, token(client, sub)))
    assert r.status_code == 200, r.text
    return r.json()


def test_llegadas_por_tramo_de_10_minutos_y_ultima_marcacion(client, db):
    e = preparar(db, "uno", alumnos=4)  # turno 07:45 con 10 min de tolerancia
    _marcar(db, e, e.alumnos[0], 7, 31, "Puerta 1")
    _marcar(db, e, e.alumnos[1], 7, 38, "Puerta 1")
    _marcar(db, e, e.alumnos[2], 7, 58, "Puerta 2")  # tarde
    # Otro colegio con más llegadas a otra hora: no aparece.
    otro = preparar(db, "dos", alumnos=3)
    for i, a in enumerate(otro.alumnos):
        _marcar(db, otro, a, 6, 10 + i, "Puerta B")

    a = _panel(client)["asistencia"]
    ll = a["llegadas"]
    assert ll["tramo_minutos"] == 10 and ll["limite"] == "07:55"
    assert ll["tramos"] == [
        {"inicio": "07:30", "a_tiempo": 2, "tarde": 0},
        {"inicio": "07:40", "a_tiempo": 0, "tarde": 0},  # tramo vacío entre medio: igual sale
        {"inicio": "07:50", "a_tiempo": 0, "tarde": 1},
    ]
    assert a["ultima_marcacion"] == {"hora": "07:58", "equipo": "Puerta 2", "origen": "qr"}


def test_llegadas_sin_marcaciones(client, db):
    preparar(db, "uno")
    a = _panel(client)["asistencia"]
    assert a["llegadas"] == {"tramo_minutos": 10, "tramos": [], "limite": None}
    assert a["ultima_marcacion"] is None


def test_personal_presentes_y_listas_cortas(client, db, monkeypatch):
    _reloj(monkeypatch, 12, 0)
    e = preparar(db, "uno", dias_semana="1234567")  # clases todos los días: la prueba no depende del día
    otro = preparar(db, "dos")
    turno = e.turno
    nombres = {}
    for dni, nombre in (("20000001", "Ana"), ("20000002", "Beto"), ("20000003", "Carla"), ("20000004", "Dino")):
        u = crear_personal(db, e.colegio, dni)
        u.turno_id, u.nombres = turno.id, nombre
        nombres[nombre] = u
    sin_turno = crear_personal(db, e.colegio, "20000009")  # sin turno: no cuenta
    ajeno = crear_personal(db, otro.colegio, "20000005")
    ajeno.turno_id = otro.turno.id
    db.add(LicenciaPersonal(colegio_id=e.colegio.id, usuario_id=nombres["Dino"].id, tipo="salud",
                            desde=hoy(), hasta=hoy()))
    db.commit()
    _marcar(db, e, None, 7, 40, personal=nombres["Ana"])
    _marcar(db, e, None, 8, 5, personal=nombres["Beto"])  # 20 min tarde

    p = _panel(client)["personal"]
    assert p["total"] == 4 and p["presente"] == 1 and p["tarde"] == 1
    assert p["lista"]["tardanzas"] == [{"nombre": "Beto 20000002", "minutos": 20}]
    assert p["lista"]["licencias"] == [{"nombre": "Dino 20000004", "tipo": "salud"}]
    assert p["con_licencia"] == 1
    # Sin marcar: solo Carla (Dino está de licencia); ni el de otro colegio ni quien no tiene turno.
    assert p["sin_marcar"] == 1 and p["lista"]["sin_marcar"] == [{"nombre": "Carla 20000003"}]
    # Si a Carla ya le cayó la falta automática, sigue sin marcar.
    asistencia.marcar_faltas(db, hoy(), time(23, 59), e.colegio.id, avisar=False)
    db.commit()
    p = _panel(client)["personal"]
    assert p["sin_marcar"] == 1 and p["falta"] == 1
    assert sin_turno.nombres not in str(p)


def test_permisos_de_salida_de_hoy(client, db):
    e = preparar(db, "uno", alumnos=2)
    otro = preparar(db, "dos", alumnos=1)

    def permiso(esc, alumno, dia, hora, estado="aprobada"):
        db.add(EntradaCuaderno(colegio_id=esc.colegio.id, tipo="permiso_salida", alcance="alumno",
                               alumno_id=alumno.id, seccion_id=esc.seccion.id, titulo="Permiso de salida",
                               desde=dia, hora_salida=hora, estado=estado))
    permiso(e, e.alumnos[0], hoy(), time(11, 30))
    permiso(e, e.alumnos[1], hoy(), time(10, 0), "pendiente")
    permiso(e, e.alumnos[1], hoy(), time(9, 0), "rechazada")  # no sale
    permiso(e, e.alumnos[0], hoy() + timedelta(days=1), time(9, 0))  # mañana
    permiso(otro, otro.alumnos[0], hoy(), time(8, 0))  # otro colegio
    db.commit()

    salidas = _panel(client)["cuaderno"]["permisos_salida_hoy"]
    assert [(s["alumno"], s["hora"], s["estado"]) for s in salidas] == [
        ("Niño1 Apellido001", "10:00", "pendiente"), ("Niño0 Apellido000", "11:30", "aprobada")]


def test_menu_con_anio_y_contadores_segun_permisos(client, db):
    e = preparar(db, "uno")
    otro = preparar(db, "dos")
    for esc in (e, otro):
        db.add(EntradaCuaderno(colegio_id=esc.colegio.id, tipo="justificacion", alcance="alumno",
                               alumno_id=esc.alumnos[0].id, seccion_id=esc.seccion.id, titulo="Falta",
                               desde=hoy(), hasta=hoy(), estado="pendiente"))
    db.commit()
    crear_familia(db, e.colegio, "41111111", estado="pendiente")
    crear_familia(db, otro.colegio, "42222222", estado="pendiente")
    crear_familia(db, otro.colegio, "43333333", estado="pendiente")

    m = client.get("/api/panel/menu", headers=auth("uno", token(client, "uno"))).json()
    assert m == {"anio": hoy().year, "cuaderno_pendientes": 1, "padres_por_aprobar": 1}
    crear_personal(db, e.colegio, "20000000", {"asistencia": "ver"})
    m = client.get("/api/panel/menu", headers=auth("uno", token(client, "uno", "20000000"))).json()
    assert m == {"anio": hoy().year}
    assert client.get("/api/panel/menu", headers=host("uno")).status_code == 401


def test_tarjeta_de_la_familia_con_puerta_salida_y_tardanzas_del_mes(client, db):
    e = preparar(db, "uno", alumnos=2)
    crear_familia(db, e.colegio, alumnos=[e.alumnos[0]])
    inicio = hoy().replace(day=1)
    # Una tardanza antes en el mes (si hoy no es el primero) y otra hoy.
    previas = 0
    if hoy() > inicio:
        db.add(AsistenciaAlumno(colegio_id=e.colegio.id, alumno_id=e.alumnos[0].id, fecha=inicio,
                                seccion_id=e.seccion.id, estado="tarde", minutos_tarde=5))
        db.add(AsistenciaAlumno(colegio_id=e.colegio.id, alumno_id=e.alumnos[0].id,
                                fecha=inicio - timedelta(days=1), seccion_id=e.seccion.id, estado="tarde"))
        db.commit()
        previas = 1
    _marcar(db, e, e.alumnos[0], 8, 0, "Puerta principal")  # 15 min tarde
    _marcar(db, e, e.alumnos[0], 9, 0, "Puerta lateral")  # salida: la puerta es la del ingreso

    h = client.get("/api/familia/hijos", headers=auth("uno", token_familia(client, "uno"))).json()["hijos"]
    assert len(h) == 1
    assert h[0]["puerta"] == "Puerta principal" and h[0]["hora_salida"] == "13:00"
    assert h[0]["tardanzas_mes"] == previas + 1


def test_asistencia_del_mes_solo_de_sus_hijos(client, db):
    e = preparar(db, "uno", alumnos=2)
    otro = preparar(db, "dos", alumnos=1)
    crear_familia(db, e.colegio, alumnos=[e.alumnos[0]])
    _marcar(db, e, e.alumnos[0], 8, 0)
    _marcar(db, e, e.alumnos[1], 7, 30)
    tok = token_familia(client, "uno")
    r = client.get(f"/api/familia/hijos/{e.alumnos[0].id}/asistencia", headers=auth("uno", tok))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["mes"] == hoy().strftime("%Y-%m") and d["resumen"]["tarde"] == 1
    assert d["dias"] == [{"fecha": hoy().isoformat(), "estado": "tarde", "entrada": "08:00", "salida": None,
                          "minutos_tarde": 15}]
    # El compañero de aula y el alumno de otro colegio: no existen para esta cuenta.
    for alumno in (e.alumnos[1], otro.alumnos[0]):
        assert client.get(f"/api/familia/hijos/{alumno.id}/asistencia", headers=auth("uno", tok)).status_code == 404
    # Un mes anterior sin datos y un mes mal escrito.
    previo = (hoy().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    r = client.get(f"/api/familia/hijos/{e.alumnos[0].id}/asistencia?mes={previo}", headers=auth("uno", tok))
    assert r.json()["dias"] == []
    assert client.get(f"/api/familia/hijos/{e.alumnos[0].id}/asistencia?mes=2026-13",
                      headers=auth("uno", tok)).status_code == 422
    # El personal del colegio no entra por aquí.
    assert client.get(f"/api/familia/hijos/{e.alumnos[0].id}/asistencia",
                      headers=auth("uno", token(client, "uno"))).status_code == 401


def test_cuenta_bloqueada_en_un_colegio_no_ve_esos_hijos(client, db):
    e = preparar(db, "uno", alumnos=1)
    otro = preparar(db, "dos", alumnos=1)
    crear_familia(db, e.colegio, alumnos=[e.alumnos[0]])
    crear_familia(db, otro.colegio, alumnos=[otro.alumnos[0]], estado="bloqueado")
    tok = token_familia(client, "uno")
    assert client.get(f"/api/familia/hijos/{otro.alumnos[0].id}/asistencia",
                      headers=auth("uno", tok)).status_code == 404


def test_menu_claro_lo_elige_quien_configura(client, db):
    preparar(db, "uno")
    preparar(db, "dos")
    tok = token(client, "uno")
    assert client.get("/api/publico/colegio", headers=host("uno")).json()["menu_claro"] is False
    colores = {"color_primario": "#0F766E", "color_secundario": "#F2A900"}
    r = client.put("/api/colegio/imagen", json={**colores, "menu_claro": True}, headers=auth("uno", tok))
    assert r.status_code == 200 and r.json()["menu_claro"] is True
    # Sin el campo, se queda como estaba.
    assert client.put("/api/colegio/imagen", json=colores, headers=auth("uno", tok)).json()["menu_claro"] is True
    assert client.get("/api/publico/colegio", headers=host("dos")).json()["menu_claro"] is False
    crear_personal(db, _colegio(db, "uno"), "20000000", {"configuracion": "ver"})
    r = client.put("/api/colegio/imagen", json={**colores, "menu_claro": False},
                   headers=auth("uno", token(client, "uno", "20000000")))
    assert r.status_code == 403


def _colegio(db, sub):
    from sqlalchemy import select

    from app.models import Colegio
    return db.scalar(select(Colegio).where(Colegio.subdominio == sub))


def test_sin_marcar_solo_despues_de_la_hora_de_su_turno(client, db, monkeypatch):
    e = preparar(db, "uno", dias_semana="1234567")  # turno Mañana 07:45
    tarde = Turno(colegio_id=e.colegio.id, nombre="Tarde", hora_entrada=time(13, 0), tolerancia_minutos=10,
                  hora_salida=time(18, 0))
    db.add(tarde)
    db.flush()
    manana_u = crear_personal(db, e.colegio, "20000001")
    tarde_u = crear_personal(db, e.colegio, "20000002")
    manana_u.turno_id, tarde_u.turno_id = e.turno.id, tarde.id
    # Otro colegio con un turno temprano y alguien sin marcar: no cuenta aquí.
    otro = preparar(db, "dos")
    ajeno = crear_personal(db, otro.colegio, "20000003")
    ajeno.turno_id = otro.turno.id
    db.commit()

    def sin_marcar():
        p = _panel(client)["personal"]
        return p["sin_marcar"], [x["nombre"] for x in p["lista"]["sin_marcar"]]

    _reloj(monkeypatch, 7, 30)  # nadie debía haber llegado todavía
    assert sin_marcar() == (0, [])
    _reloj(monkeypatch, 7, 45)  # justo a la hora: todavía no pasó
    assert sin_marcar() == (0, [])
    _reloj(monkeypatch, 7, 46)  # ya pasó la hora de la mañana
    assert sin_marcar() == (1, ["P 20000001"])
    _reloj(monkeypatch, 13, 5)  # ya pasó también la de la tarde
    assert sin_marcar() == (2, ["P 20000001", "P 20000002"])
    # El total con turno no depende de la hora.
    assert _panel(client)["personal"]["total"] == 2


# --- Permisos en Inicio ------------------------------------------------------------------------

def _panel_de(client, dni, sub="uno"):
    r = client.get("/api/panel/resumen", headers=auth(sub, token(client, sub, usuario=dni)))
    assert r.status_code == 200, r.text
    return r.json()


def test_tarjeta_del_personal_solo_con_permiso(client, db):
    e = preparar(db, "uno")
    crear_personal(db, e.colegio, "30000001", {"asistencia": "ver"})
    crear_personal(db, e.colegio, "30000002", {"asistencia": "ver", "personal": "ver"})
    sin = _panel_de(client, "30000001")
    assert "asistencia" in sin and "personal" not in sin
    con = _panel_de(client, "30000002")
    assert con["personal"]["total"] == 0
    assert "personal" in _panel(client)  # el administrador ve todo


def test_docente_con_solo_sus_secciones_ve_solo_lo_suyo(client, db):
    from app.models import SeccionDocente, Seccion

    e = preparar(db, "uno", alumnos=5, dias_semana="1234567")
    otra = Seccion(colegio_id=e.colegio.id, anio_id=e.seccion.anio_id, grado_id=e.seccion.grado_id,
                   turno_id=e.turno.id, nombre="B")
    db.add(otra)
    db.flush()
    from app.models import Matricula
    for a in e.alumnos[3:]:
        db.execute(Matricula.__table__.update().where(Matricula.alumno_id == a.id).values(seccion_id=otra.id))
    docente = crear_personal(db, e.colegio, "30000003", {"asistencia": "ver", "cuaderno": "editar"})
    docente.rol.solo_sus_secciones = True
    db.add(SeccionDocente(colegio_id=e.colegio.id, seccion_id=e.seccion.id, usuario_id=docente.id))
    db.commit()

    _marcar(db, e, e.alumnos[0], 7, 35, "Puerta A")             # sección A
    _marcar(db, e, e.alumnos[3], 7, 52, "Puerta B")             # sección B
    _marcar(db, e, e.alumnos[4], 8, 5, "Puerta B")              # sección B, tarde y la última
    for a, sec in ((e.alumnos[1], e.seccion.id), (e.alumnos[2], e.seccion.id)):
        db.add(AsistenciaAlumno(colegio_id=e.colegio.id, alumno_id=a.id, fecha=hoy(), seccion_id=sec,
                                estado="falta", minutos_tarde=0))
    db.commit()

    d = _panel_de(client, "30000003")
    assert "personal" not in d
    a = d["asistencia"]
    assert a["solo_sus_secciones"] is True
    assert a["alumnos"] == 3
    assert a["hoy"]["presente"] == 1 and a["hoy"]["tarde"] == 0 and a["hoy"]["falta"] == 2
    assert sum(t["a_tiempo"] + t["tarde"] for t in a["llegadas"]["tramos"]) == 1
    assert a["ultima_marcacion"]["equipo"] == "Puerta A"
    assert {s["id"] for s in a["secciones_con_faltas"]} <= {e.seccion.id}

    todo = _panel(client)["asistencia"]
    assert todo["solo_sus_secciones"] is False and todo["alumnos"] == 5
    assert todo["ultima_marcacion"]["hora"] == "08:05"
    assert sum(t["a_tiempo"] + t["tarde"] for t in todo["llegadas"]["tramos"]) == 3
