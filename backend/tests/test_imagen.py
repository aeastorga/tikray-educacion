from pathlib import Path

from app.config import get_settings
from tests.conftest import auth, crear_colegio, crear_personal, host, token

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def test_colores(client, db):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    r = client.put("/api/colegio/imagen", headers=h, json={"color_primario": "#aa0000", "color_secundario": "#00bb00"})
    assert r.status_code == 200
    publico = client.get("/api/publico/colegio", headers=host("alfa")).json()
    assert publico["color_primario"] == "#AA0000"
    bad = client.put("/api/colegio/imagen", headers=h, json={"color_primario": "red", "color_secundario": "#00bb00"})
    assert bad.status_code == 422


def test_subir_reemplazar_y_quitar_logo(client, db):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    url1 = client.put("/api/colegio/logo", headers=h, files={"archivo": ("l.png", PNG, "image/png")}).json()["logo_url"]
    assert url1.startswith("/archivos/colegios/") and url1.endswith(".png")
    assert client.get(url1).content == PNG

    url2 = client.put("/api/colegio/logo", headers=h, files={"archivo": ("l.png", PNG, "image/png")}).json()["logo_url"]
    assert url2 != url1
    carpeta = Path(get_settings().carpeta_archivos)
    assert not (carpeta / url1.removeprefix("/archivos/")).exists()

    assert client.delete("/api/colegio/logo", headers=h).json()["logo_url"] is None
    assert not (carpeta / url2.removeprefix("/archivos/")).exists()


def test_logo_rechaza_svg_y_pesado(client, db):
    crear_colegio(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert client.put("/api/colegio/logo", headers=h,
                      files={"archivo": ("l.png", svg, "image/png")}).status_code == 415
    grande = PNG + b"\x00" * (200 * 1024)
    assert client.put("/api/colegio/logo", headers=h,
                      files={"archivo": ("l.png", grande, "image/png")}).status_code == 413


def test_imagen_requiere_permiso_configuracion(client, db):
    c = crear_colegio(db, "alfa")
    crear_personal(db, c, "20000000", {"configuracion": "ver"})
    h = auth("alfa", token(client, "alfa", "20000000"))
    r = client.put("/api/colegio/imagen", headers=h, json={"color_primario": "#000000", "color_secundario": "#000000"})
    assert r.status_code == 403
