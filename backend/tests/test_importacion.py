import base64
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook, load_workbook

from app.importacion import COL_ALUMNOS, COL_APODERADO, COL_PERSONAL
from app.models import Alumno, AlumnoApoderado, Apoderado, Usuario
from tests.conftest import auth, crear_colegio, crear_personal, token
from tests.test_padron import armar

CAB_ALUMNOS = list(COL_ALUMNOS.values()) + [f"Apoderado {n} {v}" for n in (1, 2) for v in COL_APODERADO.values()]


def excel(alumnos: list[list] | None = None, personal: list[list] | None = None,
          cab_alumnos: list[str] = CAB_ALUMNOS) -> bytes:
    libro = Workbook()
    libro.remove(libro.active)
    if alumnos is not None:
        ws = libro.create_sheet("Alumnos")
        ws.append(cab_alumnos)
        for f in alumnos:
            ws.append(f)
    if personal is not None:
        ws = libro.create_sheet("Personal")
        ws.append(list(COL_PERSONAL.values()))
        for f in personal:
            ws.append(f)
    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()


def fila(doc="71234567", ap="Quispe", nom="Lucía", nivel="Primaria", grado="1°", sec="A", apo1=None, apo2=None,
         tipo="DNI", nac=None):
    base = [tipo, doc, ap, nom, nac, nivel, grado, sec]
    vacio = [None] * len(COL_APODERADO)
    return base + (apo1 or vacio) + (apo2 or vacio)


def madre(doc="41234567", nombres="Rosa", cel="987654321"):
    return ["DNI", doc, "Mamani", nombres, "Madre", cel, None]


def subir(client, h, contenido, paso="vista-previa"):
    return client.post(f"/api/padron/importacion/{paso}", headers=h,
                       files={"archivo": ("padron.xlsx", contenido,
                                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})


def test_plantilla_trae_hojas_y_referencias(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    r = client.get("/api/padron/importacion/plantilla", headers=h)
    assert r.status_code == 200
    libro = load_workbook(BytesIO(r.content))
    assert {"Alumnos", "Personal", "Secciones (referencia)", "Roles (referencia)"} <= set(libro.sheetnames)
    secciones = [tuple(f) for f in libro["Secciones (referencia)"].iter_rows(min_row=2, values_only=True)]
    assert ("Primaria", "1°", "A") in secciones


def test_plantilla_termina_en_la_fila_de_encabezados(client, db):
    """Si la plantilla marcara miles de filas vacías, lo que se agregue al final caería en la fila 3002."""
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    libro = load_workbook(BytesIO(client.get("/api/padron/importacion/plantilla", headers=h).content))
    assert libro["Alumnos"].max_row == 1 and libro["Personal"].max_row == 1
    assert libro["Alumnos"].column_dimensions["B"].number_format == "@"  # documento como texto


def test_direccion_de_la_carta_es_https_fuera_de_local():
    from starlette.requests import Request

    from app.routers.importacion import direccion_publica

    def con_host(host):
        return Request({"type": "http", "scheme": "http", "headers": [(b"host", host.encode())]})
    assert direccion_publica(con_host("fatima.plataforma.pe")) == "https://fatima.plataforma.pe"
    assert direccion_publica(con_host("colegiofatima.edu.pe")) == "https://colegiofatima.edu.pe"
    assert direccion_publica(con_host("fatima.localhost:5173")) == "http://fatima.localhost:5173"


def test_plantilla_vacia_se_puede_subir(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    contenido = client.get("/api/padron/importacion/plantilla", headers=h).content
    r = subir(client, h, contenido)
    assert r.status_code == 200 and r.json()["total_errores"] == 0


def test_vista_previa_no_guarda_y_confirmar_si(client, db):
    c = crear_colegio(db, "alfa")
    h, _ = armar(client)
    contenido = excel([
        fila(apo1=madre(), nac=datetime(2019, 5, 3)),
        fila(doc="71234568", nom="Mateo", sec="b", apo1=madre(cel=None)),  # mismo apoderado, hermano
    ])
    r = subir(client, h, contenido).json()
    assert r["total_errores"] == 0, r["errores"]
    assert r["resumen"]["alumnos_nuevos"] == 2 and r["resumen"]["apoderados_nuevos"] == 1
    assert r["resumen"]["vinculos_nuevos"] == 2
    assert db.query(Alumno).count() == 0

    r = subir(client, h, contenido, "confirmar")
    assert r.status_code == 200, r.text
    assert db.query(Alumno).filter_by(colegio_id=c.id).count() == 2
    assert db.query(Apoderado).count() == 1 and db.query(AlumnoApoderado).count() == 2
    assert db.query(Apoderado).one().celular == "987654321"
    lucia = db.query(Alumno).filter_by(numero_documento="71234567").one()
    assert lucia.fecha_nacimiento.isoformat() == "2019-05-03"


def test_reimportar_actualiza_y_no_duplica(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    subir(client, h, excel([fila(apo1=madre())]), "confirmar")
    r = subir(client, h, excel([fila(nom="Lucía Isabel", sec="B", apo1=madre())])).json()
    assert r["resumen"]["alumnos_nuevos"] == 0 and r["resumen"]["alumnos_actualizados"] == 1
    assert r["resumen"]["cambios_seccion"] == 1 and r["resumen"]["vinculos_nuevos"] == 0
    subir(client, h, excel([fila(nom="Lucía Isabel", sec="B", apo1=madre())]), "confirmar")
    assert db.query(Alumno).count() == 1 and db.query(AlumnoApoderado).count() == 1
    assert db.query(Alumno).one().nombres == "Lucía Isabel"


def test_errores_con_fila_y_columna(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    contenido = excel([
        fila(doc="123"),                                  # fila 2: DNI corto
        fila(doc="71234568", sec="Z"),                    # fila 3: sección inexistente
        fila(doc="71234569", apo1=madre(cel="12345")),    # fila 4: celular
        fila(doc="71234569"),                             # fila 5: repetido
        fila(doc="71234570", apo1=madre(nombres="Otra")), # fila 6: ok
        fila(doc="71234571", apo1=madre(nombres="Rosa")), # fila 7: mismo apoderado con otro nombre
        fila(doc="71234572", nac="31/02/2019"),           # fila 8: fecha
    ])
    r = subir(client, h, contenido).json()
    errores = {(e["fila"], e["columna"]) for e in r["errores"]}
    assert (2, "documento") in errores
    assert (3, "Sección") in errores
    assert (4, "Apoderado 1 celular") in errores
    assert (5, "N° documento") in errores
    assert (7, "Apoderado 1 nombres") in errores
    assert (8, "Fecha de nacimiento") in errores
    assert not any(f == 6 for f, _ in errores)

    r = subir(client, h, contenido, "confirmar")
    assert r.status_code == 422 and r.json()["detail"]["total_errores"] == r.json()["detail"]["total_errores"] > 0
    assert db.query(Alumno).count() == 0  # todo o nada


def test_dni_numerico_sin_cero_inicial(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    subir(client, h, excel([fila(doc=1234567)]), "confirmar")
    assert db.query(Alumno).one().numero_documento == "01234567"


def test_encabezados_sin_tildes_y_en_otro_orden(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    cab = ["NOMBRES", "apellidos", "dni", "nivel", "GRADO", "seccion"]
    libro = Workbook()
    ws = libro.active
    ws.title = "alumnos"
    ws.append(cab)
    ws.append(["Ana", "Ríos", "73333333", "primaria", "1", "a"])
    salida = BytesIO()
    libro.save(salida)
    r = subir(client, h, salida.getvalue()).json()
    assert r["total_errores"] == 0, r["errores"]
    assert r["resumen"]["alumnos_nuevos"] == 1


def test_faltan_columnas(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    r = subir(client, h, excel([["x"]], cab_alumnos=["Nombres"])).json()
    assert r["total_errores"] == 1 and "Faltan columnas" in r["errores"][0]["mensaje"]


def test_archivo_que_no_es_excel(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    assert subir(client, h, b"no soy un excel").status_code == 422


def test_personal_con_cartas_de_acceso(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    client.post("/api/roles", headers=h, json={"nombre": "Docente"})
    contenido = excel(personal=[
        ["DNI", "45678901", "Torres", "Ana", "docente", "987111222", "ana@correo.pe"],
        ["CE", "001234567", "García", "Luis", "Docente", None, None],
    ])
    r = subir(client, h, contenido, "confirmar").json()
    assert r["personal_nuevo"] == 2
    pdf = base64.b64decode(r["cartas_pdf"])
    assert pdf.startswith(b"%PDF") and pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") >= 1
    ana = db.query(Usuario).filter_by(numero_documento="45678901").one()
    assert ana.debe_cambiar_clave and ana.celular == "987111222" and ana.rol.nombre == "Docente"
    # Reimportar no crea de nuevo ni cambia claves.
    r = subir(client, h, contenido, "confirmar").json()
    assert r["personal_nuevo"] == 0 and r["cartas_pdf"] is None


def test_personal_errores(client, db):
    crear_colegio(db, "alfa")
    h, _ = armar(client)
    client.post("/api/roles", headers=h, json={"nombre": "Docente"})
    r = subir(client, h, excel(personal=[
        ["PAS", "AB123456", "X", "Y", "Docente", None, None],      # tipo no permitido para personal
        ["DNI", "45678901", "X", "Y", "Inexistente", None, None],  # rol no existe
        ["DNI", "10000000", "Dir", "alfa", "Director", None, None],  # el director ya existe, ok
    ])).json()
    columnas = {(e["fila"], e["columna"]) for e in r["errores"]}
    assert (2, "tipo doc") in columnas and (3, "Rol") in columnas and r["total_errores"] == 2


def test_personal_requiere_permiso_de_personal(client, db):
    c = crear_colegio(db, "alfa")
    armar(client)
    crear_personal(db, c, "20000000", {"padron": "editar"})
    h = auth("alfa", token(client, "alfa", "20000000"))
    r = subir(client, h, excel(personal=[["DNI", "45678901", "X", "Y", "Director", None, None]])).json()
    assert "permiso" in r["errores"][0]["mensaje"]


def test_no_director_no_asigna_director_por_excel(client, db):
    c = crear_colegio(db, "alfa")
    armar(client)
    crear_personal(db, c, "20000000", {"padron": "editar", "personal": "editar"})
    h = auth("alfa", token(client, "alfa", "20000000"))
    r = subir(client, h, excel(personal=[["DNI", "45678901", "X", "Y", "Director", None, None]])).json()
    assert r["errores"][0]["columna"] == "Rol"


def test_importacion_no_cruza_colegios(client, db):
    crear_colegio(db, "alfa")
    crear_colegio(db, "beta")
    h_alfa, _ = armar(client, "alfa")
    h_beta, _ = armar(client, "beta")
    subir(client, h_alfa, excel([fila(apo1=madre())]), "confirmar")
    r = subir(client, h_beta, excel([fila(apo1=madre())])).json()
    # En beta el mismo DNI es un alumno nuevo: los datos de alfa no existen para beta.
    assert r["resumen"]["alumnos_nuevos"] == 1 and r["resumen"]["apoderados_nuevos"] == 1
