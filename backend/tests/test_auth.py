import ipaddress

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


def _ingreso(client, usuario, clave, cabeceras=None):
    return client.post("/api/auth/ingreso", json={"usuario": usuario, "clave": clave},
                       headers={**host("alfa"), **(cabeceras or {})})


def test_bloqueo_tras_5_fallos_de_la_cuenta(client, db):
    crear_colegio(db, "alfa")
    for _ in range(5):
        _ingreso(client, "10000000", "mal")
    assert _ingreso(client, "10000000", CLAVE).status_code == 401


def test_fallos_de_otros_no_bloquean_al_colegio(client, db):
    """Todo el colegio sale por la misma IP: 5 docentes que se equivocan no dejan fuera al resto."""
    c = crear_colegio(db, "alfa")
    for i in range(10):
        crear_personal(db, c, f"2000000{i}", {})
        _ingreso(client, f"2000000{i}", "mal")
    assert _ingreso(client, "10000000", CLAVE).status_code == 200


def test_limite_por_ip(client, db, monkeypatch):
    from app import proteccion
    monkeypatch.setattr(proteccion.FALLOS_IP, "maximo", 3)
    crear_colegio(db, "alfa")
    for i in range(3):
        _ingreso(client, f"3000000{i}", "mal")
    assert _ingreso(client, "10000000", CLAVE).status_code == 401


def test_x_forwarded_for_solo_de_proxy_de_confianza(monkeypatch):
    from starlette.requests import Request

    from app import proteccion

    def peticion(directa, xff):
        return Request({"type": "http", "client": (directa, 1234),
                        "headers": [(b"x-forwarded-for", xff.encode())]})

    monkeypatch.setattr(proteccion, "_redes_confianza", lambda: ())
    assert proteccion.ip_cliente(peticion("1.2.3.4", "9.9.9.9")) == "1.2.3.4"  # sin proxies: se ignora

    redes = (ipaddress.ip_network("10.0.0.0/8"),)
    monkeypatch.setattr(proteccion, "_redes_confianza", lambda: redes)
    assert proteccion.ip_cliente(peticion("10.1.1.1", "200.1.1.1")) == "200.1.1.1"
    # El cliente puede escribir lo que quiera a la izquierda; vale la primera IP ajena desde la derecha.
    assert proteccion.ip_cliente(peticion("10.1.1.1", "6.6.6.6, 200.1.1.1, 10.2.2.2")) == "200.1.1.1"
    assert proteccion.ip_cliente(peticion("1.2.3.4", "200.1.1.1")) == "1.2.3.4"  # no viene del proxy


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


def test_limite_de_intentos_queda_en_la_base(client, db):
    """Vale entre instancias del servidor y tras un reinicio: otra instancia del limitador lee lo mismo."""
    from sqlalchemy import select

    from app import proteccion
    from app.models import IntentoFallido
    crear_colegio(db, "alfa")
    for _ in range(5):
        _ingreso(client, "10000000", "ClaveMala1")
    otra_instancia = proteccion.LimitadorVentana("cuenta", maximo=5, segundos=15 * 60)
    assert otra_instancia.hay_cupo(next(iter(db.scalars(select(IntentoFallido.clave)
                                                        .where(IntentoFallido.ambito == "cuenta"))))) is False
    assert _ingreso(client, "10000000", CLAVE).status_code == 401  # bloqueado aunque la clave sea buena
    claves = db.scalars(select(IntentoFallido.clave)).all()
    assert len(claves) == 10 and not any("ClaveMala1" in c for c in claves)  # no guarda lo intentado


def test_limite_de_intentos_vence_con_la_ventana(client, db):
    from sqlalchemy import text

    from app import proteccion
    crear_colegio(db, "alfa")
    for _ in range(5):
        _ingreso(client, "10000000", "ClaveMala1")
    assert _ingreso(client, "10000000", CLAVE).status_code == 401
    db.execute(text("UPDATE intento_fallido SET momento = momento - interval '16 minutes'"))
    db.commit()
    assert _ingreso(client, "10000000", CLAVE).status_code == 200
    assert proteccion.FALLOS_CUENTA.fallos("colegio:1:10000000") == 0
