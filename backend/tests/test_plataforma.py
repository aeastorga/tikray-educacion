from tests.conftest import auth, crear_admin, host, token_plataforma

NUEVO = {
    "nombre": "IE San Martín",
    "subdominio": "sanmartin",
    "director": {"dni": "12345678", "nombres": "Rosa", "apellidos": "Quispe"},
}


def _h(client, db) -> dict:
    crear_admin(db)
    return {"Authorization": f"Bearer {token_plataforma(client)}"}


def test_crear_colegio_y_director_ingresa(client, db):
    h = _h(client, db)
    r = client.post("/plataforma/colegios", headers=h, json=NUEVO)
    assert r.status_code == 201, r.text
    clave = r.json()["director_clave_temporal"]

    r = client.post("/api/auth/ingreso", json={"usuario": "12345678", "clave": clave}, headers=host("sanmartin"))
    assert r.status_code == 200 and r.json()["debe_cambiar_clave"] is True
    yo = client.get("/api/auth/yo", headers=auth("sanmartin", r.json()["token"])).json()
    assert yo["rol"] == "Director"


def test_subdominio_repetido_o_reservado(client, db):
    h = _h(client, db)
    assert client.post("/plataforma/colegios", headers=h, json=NUEVO).status_code == 201
    assert client.post("/plataforma/colegios", headers=h, json=NUEVO).status_code == 409
    assert client.post("/plataforma/colegios", headers=h, json={**NUEVO, "subdominio": "www"}).status_code == 422
    assert client.post("/plataforma/colegios", headers=h, json={**NUEVO, "subdominio": "San_Martin"}).status_code == 422


def test_suspender_colegio(client, db):
    h = _h(client, db)
    cid = client.post("/plataforma/colegios", headers=h, json=NUEVO).json()["colegio"]["id"]
    assert client.patch(f"/plataforma/colegios/{cid}", headers=h, json={"activo": False}).json()["activo"] is False
    assert client.get("/api/publico/colegio", headers=host("sanmartin")).status_code == 404


def test_dominio_propio_se_normaliza(client, db):
    h = _h(client, db)
    cid = client.post("/plataforma/colegios", headers=h, json=NUEVO).json()["colegio"]["id"]
    r = client.patch(f"/plataforma/colegios/{cid}", headers=h, json={"dominio_propio": " IESanMartin.edu.pe. "})
    assert r.json()["dominio_propio"] == "iesanmartin.edu.pe"
    assert client.get("/api/publico/colegio", headers={"Host": "iesanmartin.edu.pe"}).status_code == 200


def test_admin_desactivado_pierde_acceso(client, db):
    h = _h(client, db)
    from app.models import AdminPlataforma
    db.query(AdminPlataforma).update({"activo": False})
    db.commit()
    assert client.get("/plataforma/colegios", headers=h).status_code == 401
