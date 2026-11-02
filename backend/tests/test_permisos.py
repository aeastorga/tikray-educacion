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
    r = client.post("/api/personal", headers=h, json={"dni": "30000000", "nombres": "N", "apellidos": "A",
                                                      "rol_id": 1})
    assert r.status_code == 403


def test_editar_incluye_ver(client, db):
    c = crear_colegio(db, "alfa")
    crear_personal(db, c, "20000000", {"roles": "editar"})
    h = auth("alfa", token(client, "alfa", "20000000"))
    assert client.get("/api/roles", headers=h).status_code == 200


def test_director_crea_rol_y_personal(client, db):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    r = client.post("/api/roles", headers=h, json={"nombre": "Portería", "permisos": {"asistencia": "editar"}})
    assert r.status_code == 201
    rol_id = r.json()["id"]

    r = client.post("/api/personal", headers=h, json={"dni": "20000000", "nombres": "Ana", "apellidos": "Q",
                                                      "rol_id": rol_id})
    assert r.status_code == 201
    temporal = r.json()["clave_temporal"]
    r = client.post("/api/auth/ingreso", json={"usuario": "20000000", "clave": temporal},
                    headers={"Host": "alfa.tikray.test"})
    assert r.json()["debe_cambiar_clave"] is True


def test_rol_con_modulo_o_nivel_invalido(client, db):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    assert client.post("/api/roles", headers=h, json={"nombre": "X", "permisos": {"nada": "ver"}}).status_code == 422
    assert client.post("/api/roles", headers=h, json={"nombre": "X", "permisos": {"roles": "todo"}}).status_code == 422


def test_rol_director_protegido(client, db):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    director = client.get("/api/roles", headers=h).json()[0]
    assert director["permisos"] == {m: "editar" for m in MODULOS}
    assert client.put(f"/api/roles/{director['id']}", headers=h, json={"nombre": "X"}).status_code == 400
    assert client.delete(f"/api/roles/{director['id']}", headers=h).status_code == 400


def test_no_director_no_asigna_rol_director(client, db):
    c = crear_colegio(db, "alfa")
    crear_personal(db, c, "20000000", {"personal": "editar", "roles": "ver"})
    h = auth("alfa", token(client, "alfa", "20000000"))
    director_id = next(r["id"] for r in client.get("/api/roles", headers=h).json() if r["es_director"])
    r = client.post("/api/personal", headers=h, json={"dni": "30000000", "nombres": "N", "apellidos": "A",
                                                      "rol_id": director_id})
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
