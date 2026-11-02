import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.conftest import CLAVE, auth, crear_colegio, crear_personal, host, token


def test_sin_secret_key_no_arranca(monkeypatch):
    monkeypatch.delenv("SECRET_KEY")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_secret_key_corta_no_arranca(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "corta")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_clave_incorrecta(client, db):
    crear_colegio(db, "alfa")
    r = client.post("/api/auth/ingreso", json={"usuario": "10000000", "clave": "otra"}, headers=host("alfa"))
    assert r.status_code == 401


def test_bloqueo_tras_5_fallos(client, db):
    crear_colegio(db, "alfa")
    for _ in range(5):
        client.post("/api/auth/ingreso", json={"usuario": "10000000", "clave": "mal"}, headers=host("alfa"))
    r = client.post("/api/auth/ingreso", json={"usuario": "10000000", "clave": CLAVE}, headers=host("alfa"))
    assert r.status_code == 401


def test_clave_temporal_obliga_a_cambiarla(client, db):
    c = crear_colegio(db, "alfa")
    crear_personal(db, c, "20000000", {"personal": "editar"}, debe_cambiar_clave=True)
    r = client.post("/api/auth/ingreso", json={"usuario": "20000000", "clave": CLAVE}, headers=host("alfa"))
    assert r.json()["debe_cambiar_clave"] is True
    viejo = r.json()["token"]
    h = auth("alfa", viejo)

    assert client.get("/api/personal", headers=h).status_code == 403
    assert client.get("/api/auth/yo", headers=h).status_code == 200

    debil = client.post("/api/auth/cambiar-clave", headers=h, json={"clave_actual": CLAVE, "clave_nueva": "corta"})
    assert debil.status_code == 422
    assert "Una mayúscula" in debil.json()["detail"]["motivos"]

    r = client.post("/api/auth/cambiar-clave", headers=h,
                    json={"clave_actual": CLAVE, "clave_nueva": "NuevaClave456"})
    assert r.status_code == 200 and r.json()["debe_cambiar_clave"] is False
    assert client.get("/api/auth/yo", headers=h).status_code == 401  # el token viejo ya no sirve
    assert client.get("/api/personal", headers=auth("alfa", r.json()["token"])).status_code == 200


def test_cerrar_sesiones(client, db):
    crear_colegio(db, "alfa")
    h1 = auth("alfa", token(client, "alfa"))
    h2 = auth("alfa", token(client, "alfa"))
    assert client.post("/api/auth/cerrar-sesiones", headers=h1).status_code == 204
    assert client.get("/api/auth/yo", headers=h2).status_code == 401


def test_usuario_desactivado_pierde_acceso(client, db):
    c = crear_colegio(db, "alfa")
    u = crear_personal(db, c, "20000000", {"personal": "ver"})
    h = auth("alfa", token(client, "alfa", "20000000"))
    u.activo = False
    db.commit()
    assert client.get("/api/auth/yo", headers=h).status_code == 401


def test_token_manipulado(client, db):
    crear_colegio(db, "alfa")
    tok = token(client, "alfa")
    assert client.get("/api/auth/yo", headers=auth("alfa", tok[:-2] + "xx")).status_code == 401
