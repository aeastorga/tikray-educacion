from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.fechas import hoy_lima
from tests.conftest import auth, crear_admin, host, token_plataforma

NUEVO = {
    "nombre": "IE San Martín",
    "subdominio": "sanmartin",
    "administrador": {"numero_documento": "12345678", "nombres": "Rosa", "apellidos": "Quispe"},
}


def _h(client, db) -> dict:
    crear_admin(db)
    return {"Authorization": f"Bearer {token_plataforma(client)}"}


def test_crear_colegio_y_administrador_ingresa(client, db):
    h = _h(client, db)
    r = client.post("/plataforma/colegios", headers=h, json=NUEVO)
    assert r.status_code == 201, r.text
    clave = r.json()["administrador_clave_temporal"]

    r = client.post("/api/auth/ingreso", json={"usuario": "12345678", "clave": clave}, headers=host("sanmartin"))
    assert r.status_code == 200 and r.json()["debe_cambiar_clave"] is True
    yo = client.get("/api/auth/yo", headers=auth("sanmartin", r.json()["token"])).json()
    assert yo["rol"] == "Administrador"


def test_subdominio_repetido_o_reservado(client, db):
    h = _h(client, db)
    assert client.post("/plataforma/colegios", headers=h, json=NUEVO).status_code == 201
    assert client.post("/plataforma/colegios", headers=h, json=NUEVO).status_code == 409
    assert client.post("/plataforma/colegios", headers=h, json={**NUEVO, "subdominio": "www"}).status_code == 422
    assert client.post("/plataforma/colegios", headers=h, json={**NUEVO, "subdominio": "San_Martin"}).status_code == 422


def test_suspender_y_reactivar(client, db):
    h = _h(client, db)
    cid = client.post("/plataforma/colegios", headers=h, json=NUEVO).json()["colegio"]["id"]
    r = client.patch(f"/plataforma/colegios/{cid}", headers=h, json={"estado": "suspendido"}).json()
    assert r["estado"] == "suspendido" and r["disponible"] is False
    assert client.get("/api/publico/colegio", headers=host("sanmartin")).status_code == 403
    client.patch(f"/plataforma/colegios/{cid}", headers=h, json={"estado": "activo"})
    assert client.get("/api/publico/colegio", headers=host("sanmartin")).status_code == 200


def test_prueba_vigente_y_vencida(client, db):
    h = _h(client, db)
    hoy = hoy_lima()
    r = client.post("/plataforma/colegios", headers=h,
                    json={**NUEVO, "estado": "prueba", "vence_en": hoy.isoformat()})
    assert r.status_code == 201
    cid = r.json()["colegio"]["id"]
    assert client.get("/api/publico/colegio", headers=host("sanmartin")).status_code == 200  # vence hoy: aún entra
    ayer = (hoy - timedelta(days=1)).isoformat()
    r = client.patch(f"/plataforma/colegios/{cid}", headers=h, json={"vence_en": ayer}).json()
    assert r["disponible"] is False
    assert client.get("/api/publico/colegio", headers=host("sanmartin")).status_code == 403


def test_activo_con_vencimiento_tambien_vence(client, db):
    h = _h(client, db)
    ayer = (hoy_lima() - timedelta(days=1)).isoformat()
    client.post("/plataforma/colegios", headers=h, json={**NUEVO, "vence_en": ayer})
    assert client.get("/api/publico/colegio", headers=host("sanmartin")).status_code == 403


def test_prueba_exige_vencimiento(client, db):
    h = _h(client, db)
    assert client.post("/plataforma/colegios", headers=h, json={**NUEVO, "estado": "prueba"}).status_code == 422
    cid = client.post("/plataforma/colegios", headers=h, json=NUEVO).json()["colegio"]["id"]
    r = client.patch(f"/plataforma/colegios/{cid}", headers=h, json={"estado": "prueba"})
    assert r.status_code == 422


def test_base_exige_vencimiento_en_prueba(db):
    from app.models import Colegio
    db.add(Colegio(nombre="X", subdominio="x", estado="prueba"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_administrador_con_carne_de_extranjeria(client, db):
    h = _h(client, db)
    r = client.post("/plataforma/colegios", headers=h, json={
        **NUEVO, "administrador": {"tipo_documento": "CE", "numero_documento": "ab1234567", "nombres": "Ana",
                              "apellidos": "Pérez"}})
    assert r.status_code == 201 and r.json()["administrador_usuario"] == "AB1234567"


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
