from app.codigos import PREFIJO_QR
from tests.conftest import crear_colegio
from tests.test_imagen import PNG
from tests.test_padron import ALUMNO, armar


def _paginas(pdf: bytes) -> int:
    return pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") + pdf.count(b"/Type /Page/")


def test_carnets_de_una_seccion(client, db):
    crear_colegio(db, "alfa")
    h, e = armar(client)
    for i in range(12):
        client.post("/api/padron/alumnos", headers=h,
                    json={**ALUMNO, "numero_documento": f"7100000{i:01d}" if i < 10 else f"710000{i}",
                          "seccion_id": e["a"]["id"]})
    r = client.get(f"/api/padron/carnets?seccion_id={e['a']['id']}", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert _paginas(r.content) == 2  # 12 carnets, 10 por hoja


def test_carnet_de_un_alumno_con_logo(client, db):
    crear_colegio(db, "alfa")
    h, e = armar(client)
    # Logo PNG real de 1x1 para que reportlab lo pueda leer.
    from io import BytesIO

    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, "PNG")
    client.put("/api/colegio/logo", headers=h, files={"archivo": ("l.png", buf.getvalue(), "image/png")})
    a = client.post("/api/padron/alumnos", headers=h, json={**ALUMNO, "seccion_id": e["a"]["id"]}).json()
    r = client.get(f"/api/padron/carnets?alumno_id={a['id']}", headers=h)
    assert r.status_code == 200 and _paginas(r.content) == 1


def test_logo_danado_no_impide_imprimir(client, db):
    crear_colegio(db, "alfa")
    h, e = armar(client)
    client.put("/api/colegio/logo", headers=h, files={"archivo": ("l.png", PNG, "image/png")})  # firma PNG, datos basura
    a = client.post("/api/padron/alumnos", headers=h, json={**ALUMNO, "seccion_id": e["a"]["id"]}).json()
    assert client.get(f"/api/padron/carnets?alumno_id={a['id']}", headers=h).status_code == 200


def test_carnets_piden_seccion_o_alumno(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    assert client.get("/api/padron/carnets", headers=h).status_code == 422


def test_qr_no_lleva_el_dni():
    from app import codigos
    contenido = codigos.contenido_qr("ABCD2345")
    assert contenido == PREFIJO_QR + "ABCD2345" and "7123" not in contenido
