"""Despliegue en Render: <servicio>.onrender.com como subdominio del colegio, la PWA servida por
el mismo backend, la IP real detrás del proxy, la URL de la base que da Render y que los secretos
no estén en el repositorio."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import demo, proteccion
from app.config import Settings, get_settings
from app.main import crear_app
from tests.conftest import crear_colegio

RAIZ = Path(__file__).resolve().parents[2]
REDES_RENDER = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10"


@pytest.fixture
def render(monkeypatch):
    monkeypatch.setattr(get_settings(), "dominio_base", "onrender.com")


def test_servicio_de_render_es_el_subdominio_del_colegio(client, db, render):
    crear_colegio(db, "tikray-demo")
    r = client.get("/api/publico/colegio", headers={"Host": "tikray-demo.onrender.com"})
    assert r.status_code == 200 and r.json()["nombre"] == "Colegio tikray-demo"
    # Con puerto o mayúsculas, igual.
    assert client.get("/api/publico/colegio", headers={"Host": "Tikray-Demo.onrender.com:443"}).status_code == 200
    # Otro servicio de Render, un nivel más o el dominio pelado: no es ningún colegio.
    for host in ("otro-servicio.onrender.com", "x.tikray-demo.onrender.com", "onrender.com",
                 "tikray-demo.onrender.com.evil.pe"):
        assert client.get("/api/publico/colegio", headers={"Host": host}).status_code == 404, host
    # Los reservados no se vuelven colegio aunque exista uno con ese nombre.
    assert client.get("/api/publico/colegio", headers={"Host": "api.onrender.com"}).status_code == 404


def test_demo_con_el_nombre_del_servicio_y_su_ingreso(client, db, render):
    r = demo.crear_o_reiniciar(db, "tikray-demo", alumnos_por_seccion=1)
    h = {"Host": "tikray-demo.onrender.com"}
    ingreso = client.post("/api/auth/ingreso", headers=h,
                          json={"usuario": r.credenciales["director"]["usuario"], "clave": demo.CLAVE})
    assert ingreso.status_code == 200, ingreso.text
    yo = client.get("/api/auth/yo", headers=h | {"Authorization": f"Bearer {ingreso.json()['token']}"})
    assert yo.status_code == 200
    # El token de la demo no sirve en otro servicio de Render.
    crear_colegio(db, "otro")
    otro = client.get("/api/auth/yo", headers={"Host": "otro.onrender.com",
                                              "Authorization": f"Bearer {ingreso.json()['token']}"})
    assert otro.status_code == 403


def _peticion(directa: str, xff: str | None = None) -> Request:
    cabeceras = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "client": (directa, 1234), "headers": cabeceras})


def test_ip_real_detras_del_proxy_de_render(monkeypatch):
    redes = Settings.model_construct(proxies_confianza=REDES_RENDER)
    monkeypatch.setattr(proteccion, "get_settings", lambda: redes)
    proteccion._redes_confianza.cache_clear()
    try:
        # El proxy de Render (red privada) agrega la IP del cliente.
        assert proteccion.ip_cliente(_peticion("10.201.3.4", "190.236.12.5")) == "190.236.12.5"
        # El cliente se inventa una IP a la izquierda: se usa la que agregó Render (la de más a la derecha).
        assert proteccion.ip_cliente(_peticion("10.201.3.4", "1.2.3.4, 190.236.12.5")) == "190.236.12.5"
        # Saltos internos de Render (otra IP privada) también se saltan.
        assert proteccion.ip_cliente(_peticion("10.201.3.4", "190.236.12.5, 10.9.8.7")) == "190.236.12.5"
        # Si la conexión no viene de la red de Render, X-Forwarded-For no se lee.
        assert proteccion.ip_cliente(_peticion("190.236.12.5", "1.2.3.4")) == "190.236.12.5"
    finally:
        proteccion._redes_confianza.cache_clear()


def test_salud_ip_muestra_lo_que_llega(client):
    r = client.get("/salud/ip", headers={"X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 200
    # TestClient no es un proxy de confianza: la IP del cliente es la de la conexión.
    assert r.json() == {"ip_cliente": "testclient", "directa": "testclient", "x_forwarded_for": "1.2.3.4"}


@pytest.mark.parametrize("url", ["postgres://u:p@h:5432/tikray", "postgresql://u:p@h:5432/tikray",
                                 "postgresql+psycopg://u:p@h:5432/tikray"])
def test_url_de_la_base_de_render(url):
    s = Settings(secret_key="x" * 32, database_url=url)
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/tikray"


# --- La PWA desde el mismo servidor ------------------------------------------------------------

@pytest.fixture
def con_frontend(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)")
    (dist / "sw.js").write_text("// sw")
    (tmp_path / "secreto.txt").write_text("no")
    monkeypatch.setattr(get_settings(), "carpeta_frontend", str(dist))
    return TestClient(crear_app())


def test_sirve_la_pwa_y_deja_las_rutas_del_backend(con_frontend, db):
    c = con_frontend
    for ruta in ("/", "/panel", "/familia/activar", "/panel/reunion/3"):
        r = c.get(ruta)
        assert r.status_code == 200 and "<title>app</title>" in r.text, ruta
        assert r.headers["cache-control"] == "no-cache"
    js = c.get("/assets/app-abc123.js")
    assert js.status_code == 200 and "immutable" in js.headers["cache-control"]
    assert c.get("/sw.js").headers["cache-control"] == "no-cache"
    # Lo del backend no cae en la app.
    assert c.get("/salud").json() == {"ok": True}
    for ruta in ("/api/no-existe", "/plataforma/no-existe", "/archivos/no-existe.png", "/assets/no-existe.js",
                 "/docs/x"):
        r = c.get(ruta)
        assert r.status_code == 404 and "<title>" not in r.text, ruta
    # Nada fuera de la carpeta.
    for ruta in ("/../secreto.txt", "/%2e%2e/secreto.txt", "/assets/../../secreto.txt"):
        assert "no" != c.get(ruta).text, ruta


def test_sin_index_no_arranca(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "carpeta_frontend", str(tmp_path))
    with pytest.raises(RuntimeError, match="index.html"):
        crear_app()


# --- render.yaml y el arranque ---------------------------------------------------------------

def test_render_yaml_sin_secretos_y_con_migraciones_al_arrancar():
    yaml = pytest.importorskip("yaml")
    conf = yaml.safe_load((RAIZ / "render.yaml").read_text())
    (web,) = conf["services"]
    (base,) = conf["databases"]
    assert web["runtime"] == "docker" and web["plan"] == "free" and base["plan"] == "free"
    variables = {v["key"]: v for v in web["envVars"]}
    assert variables["SECRET_KEY"] == {"key": "SECRET_KEY", "generateValue": True}
    for clave in ("VAPID_CLAVE_PRIVADA", "VAPID_CLAVE_PUBLICA"):
        assert variables[clave] == {"key": clave, "sync": False}
    assert variables["DATABASE_URL"]["fromDatabase"] == {"name": base["name"], "property": "connectionString"}
    assert variables["DOMINIO_BASE"]["value"] == "onrender.com"
    assert variables["PROXIES_CONFIANZA"]["value"] == REDES_RENDER
    assert web["healthCheckPath"] == "/salud"
    # Ningún valor que parezca una clave.
    for v in variables.values():
        assert len(str(v.get("value", ""))) < 80
    # Cambiar a Starter es una línea.
    lineas = [x.strip() for x in (RAIZ / "render.yaml").read_text().splitlines() if x.strip().startswith("plan:")]
    assert len([x for x in lineas if x.startswith("plan: free") and "starter" in x]) == 1

    arranque = (RAIZ / "backend" / "iniciar.sh").read_text()
    assert arranque.index("alembic upgrade head") < arranque.index("exec uvicorn")
    assert "set -e" in arranque and "--no-proxy-headers" in arranque
    docker = (RAIZ / "Dockerfile").read_text()
    assert "CARPETA_FRONTEND=/app/frontend" in docker and 'CMD ["./iniciar.sh"]' in docker
    assert ".env" in (RAIZ / ".dockerignore").read_text()
