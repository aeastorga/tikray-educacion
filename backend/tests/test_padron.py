from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import AnioEscolar, Matricula, Seccion
from app.routers.estructura import es_dia_lectivo
from tests.conftest import auth, crear_colegio, crear_personal, token


def armar(client, sub: str = "alfa") -> tuple[dict, dict]:
    """Año 2026 activo, Primaria con 1° y 2°, turno mañana y secciones 1° A y 1° B."""
    h = auth(sub, token(client, sub))
    anio = client.post("/api/padron/anios", headers=h,
                       json={"anio": 2026, "inicio": "2026-03-02", "fin": "2026-12-18"}).json()
    nivel = client.post("/api/padron/niveles", headers=h, json={"nombre": "Primaria", "orden": 2}).json()
    g1 = client.post("/api/padron/grados", headers=h, json={"nivel_id": nivel["id"], "nombre": "1°", "orden": 1}).json()
    g2 = client.post("/api/padron/grados", headers=h, json={"nivel_id": nivel["id"], "nombre": "2°", "orden": 2}).json()
    turno = client.post("/api/padron/turnos", headers=h, json={
        "nombre": "Mañana", "hora_entrada": "07:45", "tolerancia_minutos": 10, "hora_salida": "13:00"}).json()
    a = client.post("/api/padron/secciones", headers=h,
                    json={"grado_id": g1["id"], "turno_id": turno["id"], "nombre": "a"}).json()
    b = client.post("/api/padron/secciones", headers=h,
                    json={"grado_id": g1["id"], "turno_id": turno["id"], "nombre": "B"}).json()
    return h, {"anio": anio, "nivel": nivel, "g1": g1, "g2": g2, "turno": turno, "a": a, "b": b}


ALUMNO = {"numero_documento": "71234567", "nombres": "  Lucía ", "apellidos": "Quispe  Mamani"}
APODERADO = {"numero_documento": "41234567", "nombres": "Rosa", "apellidos": "Mamani", "parentesco": "Madre",
             "celular": "+51 987 654 321"}


# --- Año escolar ---------------------------------------------------------------

def test_primer_anio_queda_activo_y_solo_uno_activo(client, db):
    crear_colegio(db, "alfa")
    h, e = armar(client)
    assert e["anio"]["activo"] is True
    otro = client.post("/api/padron/anios", headers=h,
                       json={"anio": 2027, "inicio": "2027-03-01", "fin": "2027-12-17"}).json()
    assert otro["activo"] is False
    client.post(f"/api/padron/anios/{otro['id']}/activar", headers=h)
    activos = [a["anio"] for a in client.get("/api/padron/anios", headers=h).json() if a["activo"]]
    assert activos == [2027]


def test_base_impide_dos_anios_activos(db):
    c = crear_colegio(db, "alfa")
    db.add_all([AnioEscolar(colegio_id=c.id, anio=2026, inicio=date(2026, 3, 1), fin=date(2026, 12, 1), activo=True),
                AnioEscolar(colegio_id=c.id, anio=2027, inicio=date(2027, 3, 1), fin=date(2027, 12, 1), activo=True)])
    with pytest.raises(IntegrityError):
        db.commit()


def test_anio_fechas_invalidas(client, db):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    r = client.post("/api/padron/anios", headers=h, json={"anio": 2026, "inicio": "2026-12-01", "fin": "2026-03-01"})
    assert r.status_code == 422


def test_sin_anio_activo_avisa(client, db):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    r = client.get("/api/padron/secciones", headers=h)
    assert r.status_code == 409 and "año escolar" in r.json()["detail"]


# --- Estructura -----------------------------------------------------------------

def test_estructura_y_secciones(client, db):
    crear_colegio(db, "alfa")
    h, e = armar(client)
    est = client.get("/api/padron/estructura", headers=h).json()
    assert [g["nombre"] for g in est["niveles"][0]["grados"]] == ["1°", "2°"]
    assert est["turnos"][0]["hora_entrada"] == "07:45"
    secciones = client.get("/api/padron/secciones", headers=h).json()
    assert [s["etiqueta"] for s in secciones] == ["Primaria · 1° A", "Primaria · 1° B"]


def test_repetidos_y_en_uso(client, db):
    crear_colegio(db, "alfa")
    h, e = armar(client)
    assert client.post("/api/padron/niveles", headers=h, json={"nombre": "Primaria"}).status_code == 409
    r = client.post("/api/padron/secciones", headers=h,
                    json={"grado_id": e["g1"]["id"], "turno_id": e["turno"]["id"], "nombre": "A"})
    assert r.status_code == 409
    assert client.delete(f"/api/padron/niveles/{e['nivel']['id']}", headers=h).status_code == 409
    assert client.delete(f"/api/padron/turnos/{e['turno']['id']}", headers=h).status_code == 409
    assert client.delete(f"/api/padron/grados/{e['g2']['id']}", headers=h).status_code == 204


def test_turno_horas_invalidas(client, db):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    r = client.post("/api/padron/turnos", headers=h,
                    json={"nombre": "X", "hora_entrada": "13:00", "hora_salida": "08:00"})
    assert r.status_code == 422


def test_estructura_de_otro_colegio_no_se_usa(client, db):
    crear_colegio(db, "alfa")
    crear_colegio(db, "beta")
    _, e_alfa = armar(client, "alfa")
    h_beta, e_beta = armar(client, "beta")
    r = client.post("/api/padron/secciones", headers=h_beta,
                    json={"grado_id": e_alfa["g1"]["id"], "turno_id": e_beta["turno"]["id"], "nombre": "C"})
    assert r.status_code == 404
    r = client.post("/api/padron/alumnos", headers=h_beta, json={**ALUMNO, "seccion_id": e_alfa["a"]["id"]})
    assert r.status_code == 404


def test_base_impide_matricula_en_seccion_de_otro_anio(client, db):
    c = crear_colegio(db, "alfa")
    h, e = armar(client)
    otro = AnioEscolar(colegio_id=c.id, anio=2027, inicio=date(2027, 3, 1), fin=date(2027, 12, 1))
    db.add(otro)
    db.flush()
    alumno = client.post("/api/padron/alumnos", headers=h, json=ALUMNO).json()
    db.add(Matricula(colegio_id=c.id, anio_id=otro.id, alumno_id=alumno["id"], seccion_id=e["a"]["id"]))
    with pytest.raises(IntegrityError):
        db.commit()


# --- Días no lectivos -----------------------------------------------------------

def test_rango_de_vacaciones_solo_dias_de_clase(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    # 27/07/2026 es lunes: dos semanas = 10 días de clase.
    r = client.post("/api/padron/dias-no-lectivos", headers=h,
                    json={"desde": "2026-07-27", "hasta": "2026-08-09", "motivo": "Vacaciones de medio año"})
    assert r.json()["agregados"] == 10
    r = client.post("/api/padron/dias-no-lectivos", headers=h,
                    json={"desde": "2026-07-27", "hasta": "2026-07-31", "motivo": "Otra vez"})
    assert r.json()["agregados"] == 0
    assert len(client.get("/api/padron/dias-no-lectivos", headers=h).json()) == 10


def test_dia_fuera_del_anio(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    r = client.post("/api/padron/dias-no-lectivos", headers=h, json={"desde": "2026-01-05", "motivo": "X"})
    assert r.status_code == 422


def test_es_dia_lectivo(client, db):
    c = crear_colegio(db, "alfa")
    h, e = armar(client)
    client.post("/api/padron/dias-no-lectivos", headers=h, json={"desde": "2026-06-29", "motivo": "San Pedro"})
    assert es_dia_lectivo(db, c.id, date(2026, 6, 30)) is True   # martes
    assert es_dia_lectivo(db, c.id, date(2026, 6, 29)) is False  # feriado marcado
    assert es_dia_lectivo(db, c.id, date(2026, 7, 4)) is False   # sábado
    assert es_dia_lectivo(db, c.id, date(2026, 2, 2)) is False   # antes del inicio
    # Colegio con clases los sábados: lo configura el administrador en el año.
    anio = e["anio"]
    client.put(f"/api/padron/anios/{anio['id']}", headers=h,
               json={"anio": 2026, "inicio": anio["inicio"], "fin": anio["fin"], "dias_semana": "123456"})
    db.expire_all()
    assert es_dia_lectivo(db, c.id, date(2026, 7, 4)) is True


# --- Alumnos y apoderados -------------------------------------------------------

def test_crear_alumno_normaliza_y_matricula(client, db):
    crear_colegio(db, "alfa")
    h, e = armar(client)
    r = client.post("/api/padron/alumnos", headers=h, json={**ALUMNO, "seccion_id": e["a"]["id"]})
    assert r.status_code == 201, r.text
    al = r.json()
    assert (al["nombres"], al["apellidos"]) == ("Lucía", "Quispe Mamani")
    assert al["seccion"] == "Primaria · 1° A" and len(al["codigo"]) == 8
    assert client.post("/api/padron/alumnos", headers=h, json=ALUMNO).status_code == 409


def test_editar_con_documento_de_otro_alumno(client, db):
    crear_colegio(db, "alfa")
    h, e = armar(client)
    client.post("/api/padron/alumnos", headers=h, json=ALUMNO)
    otro = client.post("/api/padron/alumnos", headers=h, json={**ALUMNO, "numero_documento": "72222222"}).json()
    r = client.put(f"/api/padron/alumnos/{otro['id']}", headers=h, json={**ALUMNO, "seccion_id": e["a"]["id"]})
    assert r.status_code == 409


def test_cambio_de_seccion_en_el_mismo_anio(client, db):
    crear_colegio(db, "alfa")
    h, e = armar(client)
    al = client.post("/api/padron/alumnos", headers=h, json={**ALUMNO, "seccion_id": e["a"]["id"]}).json()
    r = client.put(f"/api/padron/alumnos/{al['id']}", headers=h, json={**ALUMNO, "seccion_id": e["b"]["id"]}).json()
    assert r["seccion"] == "Primaria · 1° B" and len(r["matriculas"]) == 1


def test_documentos_de_alumno(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    for tipo, num, esperado in [("DNI", "123", 422), ("CE", "001234567", 201), ("PAS", "AB123456", 201),
                                ("XX", "1", 422)]:
        r = client.post("/api/padron/alumnos", headers=h,
                        json={**ALUMNO, "tipo_documento": tipo, "numero_documento": num})
        assert r.status_code == esperado, (tipo, num, r.text)


def test_apoderado_n_a_n(client, db):
    """Dos hermanos con la misma madre; uno además con el padre."""
    crear_colegio(db, "alfa")
    h, e = armar(client)
    a1 = client.post("/api/padron/alumnos", headers=h, json=ALUMNO).json()
    a2 = client.post("/api/padron/alumnos", headers=h, json={**ALUMNO, "numero_documento": "71234568",
                                                              "nombres": "Mateo"}).json()
    m1 = client.post(f"/api/padron/alumnos/{a1['id']}/apoderados", headers=h, json=APODERADO).json()
    m2 = client.post(f"/api/padron/alumnos/{a2['id']}/apoderados", headers=h,
                     json={**APODERADO, "celular": None}).json()
    assert m1["id"] == m2["id"] and m1["celular"] == "987654321"
    assert m2["celular"] == "987654321"  # un dato vacío no borra el que ya estaba
    client.post(f"/api/padron/alumnos/{a1['id']}/apoderados", headers=h,
                json={**APODERADO, "numero_documento": "41234568", "nombres": "Juan", "parentesco": "Padre"})
    d1 = client.get(f"/api/padron/alumnos/{a1['id']}", headers=h).json()
    d2 = client.get(f"/api/padron/alumnos/{a2['id']}", headers=h).json()
    assert sorted(p["parentesco"] for p in d1["apoderados"]) == ["Madre", "Padre"]
    assert [p["nombres"] for p in d2["apoderados"]] == ["Rosa"]
    client.delete(f"/api/padron/alumnos/{a1['id']}/apoderados/{m1['id']}", headers=h)
    assert len(client.get(f"/api/padron/alumnos/{a1['id']}", headers=h).json()["apoderados"]) == 1
    assert len(client.get(f"/api/padron/alumnos/{a2['id']}", headers=h).json()["apoderados"]) == 1


def test_celular_invalido(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    a = client.post("/api/padron/alumnos", headers=h, json=ALUMNO).json()
    r = client.post(f"/api/padron/alumnos/{a['id']}/apoderados", headers=h, json={**APODERADO, "celular": "123"})
    assert r.status_code == 422


def test_listado_busqueda_y_filtro(client, db):
    crear_colegio(db, "alfa")
    h, e = armar(client)
    client.post("/api/padron/alumnos", headers=h, json={**ALUMNO, "seccion_id": e["a"]["id"]})
    client.post("/api/padron/alumnos", headers=h, json={**ALUMNO, "numero_documento": "72222222",
                                                         "apellidos": "Torres", "seccion_id": e["b"]["id"]})
    assert client.get("/api/padron/alumnos", headers=h).json()["total"] == 2
    assert [a["apellidos"] for a in client.get("/api/padron/alumnos?q=torr", headers=h).json()["alumnos"]] == ["Torres"]
    r = client.get(f"/api/padron/alumnos?seccion_id={e['a']['id']}", headers=h).json()
    assert [a["apellidos"] for a in r["alumnos"]] == ["Quispe Mamani"]
    assert client.get("/api/padron/secciones", headers=h).json()[0]["alumnos"] == 1


def test_nuevo_codigo_invalida_el_anterior(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    a = client.post("/api/padron/alumnos", headers=h, json=ALUMNO).json()
    nuevo = client.post(f"/api/padron/alumnos/{a['id']}/nuevo-codigo", headers=h).json()["codigo"]
    assert nuevo != a["codigo"]


def test_padron_requiere_permiso(client, db):
    c = crear_colegio(db, "alfa")
    armar(client)
    crear_personal(db, c, "20000000", {"padron": "ver"})
    h = auth("alfa", token(client, "alfa", "20000000"))
    assert client.get("/api/padron/alumnos", headers=h).status_code == 200
    assert client.post("/api/padron/alumnos", headers=h, json=ALUMNO).status_code == 403
    assert client.post("/api/padron/niveles", headers=h, json={"nombre": "Inicial"}).status_code == 403


def test_seccion_de_otro_colegio_en_bd(db, client):
    a = crear_colegio(db, "alfa")
    crear_colegio(db, "beta")
    _, e_beta = armar(client, "beta")
    sec = db.get(Seccion, e_beta["a"]["id"])
    db.add(Seccion(colegio_id=a.id, anio_id=sec.anio_id, grado_id=sec.grado_id, turno_id=sec.turno_id, nombre="Z"))
    with pytest.raises(IntegrityError):
        db.commit()
