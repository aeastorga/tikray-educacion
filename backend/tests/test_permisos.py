import pytest

from app.modulos import MODULOS
from tests.conftest import auth, crear_colegio, crear_personal, token


def test_sin_permiso_da_403(client, db):
    c = crear_colegio(db, "alfa")
    crear_personal(db, c, "20000000", {})
    h = auth("alfa", token(client, "alfa", "20000000"))
    assert client.get("/api/personal", headers=h).status_code == 403
    assert client.get("/api/roles", headers=h).status_code == 403


def test_ver_no_permite_editar(client, db):
    c = crear_colegio(db, "alfa")
    crear_personal(db, c, "20000000", {"personal": "ver"})
    h = auth("alfa", token(client, "alfa", "20000000"))
    assert client.get("/api/personal", headers=h).status_code == 200
    r = client.post("/api/personal", headers=h, json={"numero_documento": "30000000", "nombres": "N", "apellidos": "A",
                                                      "rol_id": 1})
    assert r.status_code == 403


def test_editar_incluye_ver(client, db):
    c = crear_colegio(db, "alfa")
    crear_personal(db, c, "20000000", {"roles": "editar"})
    h = auth("alfa", token(client, "alfa", "20000000"))
    assert client.get("/api/roles", headers=h).status_code == 200


def test_administrador_crea_rol_y_personal(client, db):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    r = client.post("/api/roles", headers=h, json={"nombre": "Portería", "permisos": {"asistencia": "editar"}})
    assert r.status_code == 201
    rol_id = r.json()["id"]

    r = client.post("/api/personal", headers=h, json={"numero_documento": "20000000", "nombres": "Ana", "apellidos": "Q",
                                                      "rol_id": rol_id})
    assert r.status_code == 201
    temporal = r.json()["clave_temporal"]
    r = client.post("/api/auth/ingreso", json={"usuario": "20000000", "clave": temporal},
                    headers={"Host": "alfa.tikray.test"})
    assert r.json()["debe_cambiar_clave"] is True


@pytest.mark.parametrize("tipo,numero,esperado", [
    ("DNI", "1234567", 422), ("DNI", "12345678", 201), ("CE", "001234567", 201), ("CE", "AB12345678XY", 201),
    ("CE", "1234", 422), ("CE", "AB12345678XYZ", 422), ("PAS", "A1234567", 422),
])
def test_documento_del_personal(client, db, tipo, numero, esperado):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    rol_id = client.post("/api/roles", headers=h, json={"nombre": "Docente"}).json()["id"]
    r = client.post("/api/personal", headers=h, json={"tipo_documento": tipo, "numero_documento": numero,
                                                      "nombres": "N", "apellidos": "A", "rol_id": rol_id})
    assert r.status_code == esperado, r.text


def test_ce_entra_con_su_numero(client, db):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    rol_id = client.post("/api/roles", headers=h, json={"nombre": "Docente"}).json()["id"]
    r = client.post("/api/personal", headers=h, json={"tipo_documento": "CE", "numero_documento": "001234567",
                                                      "nombres": "Luis", "apellidos": "García", "rol_id": rol_id})
    clave = r.json()["clave_temporal"]
    assert token(client, "alfa", "001234567", clave)


def test_rol_con_modulo_o_nivel_invalido(client, db):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    assert client.post("/api/roles", headers=h, json={"nombre": "X", "permisos": {"nada": "ver"}}).status_code == 422
    assert client.post("/api/roles", headers=h, json={"nombre": "X", "permisos": {"roles": "todo"}}).status_code == 422


def test_rol_administrador_protegido(client, db):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    administrador = client.get("/api/roles", headers=h).json()[0]
    assert administrador["permisos"] == {m: "editar" for m in MODULOS}
    assert client.put(f"/api/roles/{administrador['id']}", headers=h, json={"nombre": "X"}).status_code == 400
    assert client.delete(f"/api/roles/{administrador['id']}", headers=h).status_code == 400


def test_no_administrador_no_asigna_rol_administrador(client, db):
    c = crear_colegio(db, "alfa")
    crear_personal(db, c, "20000000", {"personal": "editar", "roles": "ver"})
    h = auth("alfa", token(client, "alfa", "20000000"))
    administrador_id = next(r["id"] for r in client.get("/api/roles", headers=h).json() if r["es_administrador"])
    r = client.post("/api/personal", headers=h, json={"numero_documento": "30000000", "nombres": "N", "apellidos": "A",
                                                      "rol_id": administrador_id})
    assert r.status_code == 403


def test_rol_con_personal_no_se_borra(client, db):
    c = crear_colegio(db, "alfa")
    u = crear_personal(db, c, "20000000", {})
    h = auth("alfa", token(client, "alfa"))
    assert client.delete(f"/api/roles/{u.rol_id}", headers=h).status_code == 409


def test_permiso_cambiado_aplica_sin_volver_a_ingresar(client, db):
    c = crear_colegio(db, "alfa")
    u = crear_personal(db, c, "20000000", {"personal": "ver"})
    h_persona = auth("alfa", token(client, "alfa", "20000000"))
    h_dir = auth("alfa", token(client, "alfa"))
    assert client.get("/api/personal", headers=h_persona).status_code == 200
    client.put(f"/api/roles/{u.rol_id}", headers=h_dir, json={"nombre": "Sin nada", "permisos": {}})
    assert client.get("/api/personal", headers=h_persona).status_code == 403
