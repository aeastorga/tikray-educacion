"""Cuaderno de control: comunicados por alcance con firma de lectura, adjuntos fuera de la base,
incidencias, citaciones, justificaciones, permisos de salida (y la portería), respuestas,
docentes que solo ven sus secciones, avisos push en la cola. Y aislamiento entre colegios."""

import json
import uuid
from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import avisos
from app.config import get_settings
from app.fechas import hoy_lima
from app.models import (AdjuntoCuaderno, Alumno, AnioEscolar, Apoderado, ColaAviso, Colegio, DestinoCuaderno,
                        EntradaCuaderno, EntregaAviso, Grado, Matricula, Nivel, Rol, Seccion, SuscripcionPush, Turno,
                        Usuario)
from tests.conftest import (auth, crear_colegio, crear_familia, crear_personal, host, token, token_familia)

HOY = hoy_lima()
PDF = b"%PDF-1.4\n%prueba\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


@dataclass
class Escuela:
    colegio: Colegio
    primaria: Nivel
    grado1: Grado
    sec_a: Seccion
    sec_b: Seccion
    sec_secundaria: Seccion
    a1: Alumno  # 1° A primaria
    a2: Alumno  # 1° B primaria (hermano de a1)
    a3: Alumno  # 1° A secundaria
    madre: Apoderado  # de a1 y a2, con cuenta activa
    padre: Apoderado  # de a1, sin cuenta
    otro: Apoderado  # de a3, con cuenta activa


def preparar(db, sub: str, dni_madre: str = "41234567", dni_otro: str = "42222222") -> Escuela:
    c = crear_colegio(db, sub)
    anio = AnioEscolar(colegio_id=c.id, anio=HOY.year, inicio=date(HOY.year, 1, 1), fin=date(HOY.year, 12, 31),
                       dias_semana="1234567", activo=True)
    prim, secu = Nivel(colegio_id=c.id, nombre="Primaria", orden=1), Nivel(colegio_id=c.id, nombre="Secundaria", orden=2)
    turno = Turno(colegio_id=c.id, nombre="Mañana", hora_entrada=time(0, 5), tolerancia_minutos=0,
                  hora_salida=time(23, 0))
    db.add_all([anio, prim, secu, turno])
    db.flush()
    g1, g1s = Grado(colegio_id=c.id, nivel_id=prim.id, nombre="1°"), Grado(colegio_id=c.id, nivel_id=secu.id, nombre="1°")
    db.add_all([g1, g1s])
    db.flush()
    secs = [Seccion(colegio_id=c.id, anio_id=anio.id, grado_id=g, turno_id=turno.id, nombre=n)
            for g, n in ((g1.id, "A"), (g1.id, "B"), (g1s.id, "A"))]
    db.add_all(secs)
    db.flush()
    alumnos = []
    for i, sec in enumerate(secs):
        a = Alumno(colegio_id=c.id, numero_documento=f"7{i:07d}", nombres=f"Niño{i}", apellidos=f"Ape{i}",
                   codigo=f"{sub[:2].upper()}CUAD{i}"[:8])
        db.add(a)
        db.flush()
        db.add(Matricula(colegio_id=c.id, anio_id=anio.id, alumno_id=a.id, seccion_id=sec.id))
        alumnos.append(a)
    db.commit()
    madre = crear_familia(db, c, dni_madre, alumnos[:2])
    otro = crear_familia(db, c, dni_otro, alumnos[2:])
    padre = Apoderado(colegio_id=c.id, numero_documento="43333333", nombres="Juan", apellidos="Quispe")
    db.add(padre)
    db.flush()
    from app.models import AlumnoApoderado
    db.add(AlumnoApoderado(colegio_id=c.id, alumno_id=alumnos[0].id, apoderado_id=padre.id, parentesco="Padre"))
    db.commit()
    return Escuela(c, prim, g1, *secs, *alumnos, madre, padre, otro)


def escribir(client, h: dict, archivos: list | None = None, **datos):
    datos.setdefault("titulo", "Reunión de padres")
    return client.post("/api/cuaderno/entradas", data={"datos": json.dumps(datos, default=str)},
                       files=archivos or None, headers=h)


def cola_cuaderno(db, colegio: Colegio) -> list[ColaAviso]:
    return db.scalars(select(ColaAviso).where(ColaAviso.colegio_id == colegio.id, ColaAviso.tipo == "cuaderno")
                      .order_by(ColaAviso.id)).all()


@pytest.fixture
def e(db):
    return preparar(db, "alfa")


@pytest.fixture
def h(client, e):
    return auth("alfa", token(client, "alfa"))


@pytest.fixture
def hf(client, e):
    """La madre, desde la dirección de alfa."""
    return auth("alfa", token_familia(client, "alfa"))


# --- Comunicados y alcance --------------------------------------------------------------

@pytest.mark.parametrize("alcance,campo,cuantos", [
    ("colegio", None, 3), ("nivel", "primaria", 2), ("grado", "grado1", 2), ("seccion", "sec_a", 1),
    ("alumno", "a2", 1)])
def test_comunicado_llega_segun_su_alcance(client, db, e, h, alcance, campo, cuantos):
    datos = {"tipo": "comunicado", "alcance": alcance}
    if campo:
        datos[f"{alcance}_id"] = getattr(e, campo).id
    r = escribir(client, h, **datos)
    assert r.status_code == 201, r.text
    assert r.json()["alumnos"] == cuantos
    alumnos = set(db.scalars(select(DestinoCuaderno.alumno_id).where(DestinoCuaderno.entrada_id == r.json()["id"])))
    assert len(alumnos) == cuantos


def test_comunicado_a_todo_el_colegio_avisa_una_vez_por_apoderado_con_app(client, db, e, h):
    r = escribir(client, h, tipo="comunicado", alcance="colegio", pide_firma=True)
    assert r.json() == {"id": r.json()["id"], "alumnos": 3, "apoderados": 3, "avisados": 2, "programado_para": None}
    cola = cola_cuaderno(db, e.colegio)
    # La madre tiene dos hijos en el colegio: un solo aviso. El padre sin cuenta no recibe push.
    assert sorted(a.apoderado_id for a in cola) == sorted([e.madre.id, e.otro.id])
    assert cola[0].datos["url"] == f"/familia/cuaderno/{r.json()['id']}"
    assert "firma de lectura" in cola[0].datos["mensaje"]


def test_destino_vacio_o_incoherente(client, db, e, h):
    vacia = Seccion(colegio_id=e.colegio.id, anio_id=e.sec_a.anio_id, grado_id=e.grado1.id, turno_id=e.sec_a.turno_id,
                    nombre="C")
    db.add(vacia)
    db.commit()
    assert escribir(client, h, tipo="comunicado", alcance="seccion", seccion_id=vacia.id).status_code == 422
    r = escribir(client, h, tipo="incidencia", alcance="colegio")
    assert r.status_code == 422 and "Solo los comunicados" in r.json()["detail"]
    assert escribir(client, h, tipo="citacion", alumno_id=e.a1.id).status_code == 422  # sin fecha
    assert escribir(client, h, tipo="comunicado", alcance="nivel", nivel_id=99999).status_code == 404


def test_firma_de_lectura_y_quien_leyo(client, db, e, h, hf):
    eid = escribir(client, h, tipo="comunicado", alcance="nivel", nivel_id=e.primaria.id, pide_firma=True).json()["id"]
    lista = client.get("/api/familia/cuaderno", headers=hf).json()
    assert [x["id"] for x in lista["entradas"]] == [eid]
    assert lista["entradas"][0]["visto"] is False and lista["entradas"][0]["alumnos"] == ["Niño0", "Niño1"]

    assert client.get(f"/api/familia/cuaderno/{eid}", headers=hf).status_code == 200  # la abre: vista
    resumen = client.get("/api/cuaderno/entradas", headers=h).json()["entradas"][0]
    assert (resumen["apoderados"], resumen["vistos"], resumen["firmados"]) == (2, 1, 0)

    r = client.post(f"/api/familia/cuaderno/{eid}/firmar", headers=hf)
    assert r.status_code == 200
    det = client.get(f"/api/cuaderno/entradas/{eid}", headers=h).json()
    lectores = client.get(f"/api/cuaderno/entradas/{eid}/lectores", headers=h).json()["filas"]
    assert det["familias"] == {"total": 2, "vieron": 1, "firmaron": 1}
    firmas = {(x["alumno"], x["apoderado"]): x["firmado_en"] is not None for x in lectores}
    assert firmas == {("Ape0, Niño0", "Mamani, Rosa"): True, ("Ape1, Niño1", "Mamani, Rosa"): True,
                      ("Ape0, Niño0", "Quispe, Juan"): False}
    assert [x["con_app"] for x in lectores if x["apoderado"] == "Quispe, Juan"] == [False]
    # Solo quienes faltan, y con buscador.
    pend = client.get(f"/api/cuaderno/entradas/{eid}/lectores?pendientes=true", headers=h).json()
    assert pend["total"] == 1 and pend["filas"][0]["apoderado"] == "Quispe, Juan"
    assert client.get(f"/api/cuaderno/entradas/{eid}/lectores?q=mamani", headers=h).json()["total"] == 2
    resumen = client.get("/api/cuaderno/entradas", headers=h).json()["entradas"][0]
    assert (resumen["vistos"], resumen["firmados"]) == (1, 1)


def test_sin_firma_no_se_firma(client, e, h, hf):
    eid = escribir(client, h, tipo="comunicado", alcance="alumno", alumno_id=e.a1.id).json()["id"]
    assert client.post(f"/api/familia/cuaderno/{eid}/firmar", headers=hf).status_code == 400


def test_familia_solo_ve_lo_que_le_llego(client, db, e, h, hf):
    del_otro = escribir(client, h, tipo="incidencia", alumno_id=e.a3.id).json()["id"]
    assert client.get("/api/familia/cuaderno", headers=hf).json()["entradas"] == []
    for metodo, ruta in (("GET", f"/api/familia/cuaderno/{del_otro}"),
                         ("POST", f"/api/familia/cuaderno/{del_otro}/firmar")):
        assert client.request(metodo, ruta, headers=hf).status_code == 404
    r = client.post(f"/api/familia/cuaderno/{del_otro}/respuestas", json={"cuerpo": "Hola"}, headers=hf)
    assert r.status_code == 404


def test_cuenta_pendiente_aun_no_ve_el_cuaderno(client, db, e):
    crear_familia(db, e.colegio, "45555555", [e.a3], estado="pendiente")
    hp = auth("alfa", token_familia(client, "alfa", "45555555"))
    r = client.get("/api/familia/cuaderno", headers=hp)
    assert r.status_code == 403 and "aprobación" in r.json()["detail"]


# --- Adjuntos ------------------------------------------------------------------------------

def test_adjuntos_van_al_almacenamiento_privado(client, db, e, h, hf):
    r = escribir(client, h, archivos=[("archivos", ("circular.pdf", PDF, "application/pdf")),
                                      ("archivos", ("foto.png", PNG, "image/png"))],
                 tipo="comunicado", alcance="alumno", alumno_id=e.a1.id)
    assert r.status_code == 201, r.text
    adjs = db.scalars(select(AdjuntoCuaderno).order_by(AdjuntoCuaderno.id)).all()
    assert [(a.nombre, a.tipo_mime, a.tamano) for a in adjs] == [("circular.pdf", "application/pdf", len(PDF)),
                                                                ("foto.png", "image/png", len(PNG))]
    # En la carpeta privada, no en la pública (/archivos) ni en la base.
    privada = Path(get_settings().carpeta_privada)
    assert (privada / adjs[0].clave).read_bytes() == PDF
    assert not (Path(get_settings().carpeta_archivos) / adjs[0].clave).exists()
    assert client.get(f"/archivos/{adjs[0].clave}").status_code == 404

    for hh, ruta in ((h, "/api/cuaderno/adjuntos"), (hf, "/api/familia/cuaderno/adjuntos")):
        r = client.get(f"{ruta}/{adjs[0].id}", headers=hh)
        assert r.status_code == 200 and r.content == PDF
        assert r.headers["content-type"] == "application/pdf"
        assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/cuaderno/adjuntos/{adjs[0].id}", headers=host("alfa")).status_code == 401
    # Otra familia del mismo colegio no lo ve.
    ho = auth("alfa", token_familia(client, "alfa", "42222222"))
    assert client.get(f"/api/familia/cuaderno/adjuntos/{adjs[0].id}", headers=ho).status_code == 404


@pytest.mark.parametrize("archivo,motivo", [
    (("virus.exe", b"MZ\x90\x00", "application/octet-stream"), "solo se aceptan"),
    (("falso.pdf", b"<html><script>", "application/pdf"), "solo se aceptan"),
    (("vacio.pdf", b"", "application/pdf"), "vacío"),
    (("grande.pdf", PDF + b"0" * (10 * 1024 * 1024), "application/pdf"), "10 MB"),
])
def test_adjuntos_rechazados(client, db, e, h, archivo, motivo):
    r = escribir(client, h, archivos=[("archivos", archivo)], tipo="comunicado", alcance="alumno", alumno_id=e.a1.id)
    assert r.status_code == 422 and motivo in r.json()["detail"]
    assert db.scalar(select(EntradaCuaderno.id)) is None


def test_hasta_cinco_adjuntos(client, e, h):
    archivos = [("archivos", (f"{i}.pdf", PDF, "application/pdf")) for i in range(6)]
    r = escribir(client, h, archivos=archivos, tipo="comunicado", alcance="alumno", alumno_id=e.a1.id)
    assert r.status_code == 422


# --- Incidencias, citaciones, respuestas -------------------------------------------------

def test_citacion_con_confirmacion_del_padre(client, db, e, h, hf):
    r = escribir(client, h, tipo="citacion", alumno_id=e.a1.id, titulo="Rendimiento",
                 cita_en=f"{HOY + timedelta(days=2)}T10:30", lugar="Dirección")
    assert r.status_code == 201, r.text
    ent = db.get(EntradaCuaderno, r.json()["id"])
    assert ent.seccion_id == e.sec_a.id  # para que la vea el tutor de la sección
    assert ent.cita_en.astimezone(__import__("app.fechas", fromlist=["LIMA"]).LIMA).strftime("%H:%M") == "10:30"
    assert "Confirma tu asistencia" in cola_cuaderno(db, e.colegio)[0].datos["mensaje"]
    assert client.post(f"/api/familia/cuaderno/{ent.id}/firmar", headers=hf).status_code == 200
    det = client.get(f"/api/cuaderno/entradas/{ent.id}", headers=h).json()
    assert det["pide_firma"] and det["familias"]["firmaron"] == 1


def test_respuestas_en_el_hilo(client, db, e, h, hf):
    eid = escribir(client, h, tipo="incidencia", alumno_id=e.a1.id, titulo="Se golpeó en el recreo").json()["id"]
    assert client.get("/api/cuaderno/entradas?pendientes=true", headers=h).json()["entradas"] == []
    r = client.post(f"/api/familia/cuaderno/{eid}/respuestas", json={"cuerpo": "Gracias, lo recojo"}, headers=hf)
    assert r.status_code == 201
    pend = client.get("/api/cuaderno/entradas?pendientes=true", headers=h).json()["entradas"]
    assert [(x["id"], x["respuestas"], x["espera_al_colegio"]) for x in pend] == [(eid, 1, True)]

    antes = len(cola_cuaderno(db, e.colegio))
    r = client.post(f"/api/cuaderno/entradas/{eid}/respuestas", json={"cuerpo": "Está bien"}, headers=h)
    assert r.status_code == 201
    assert len(cola_cuaderno(db, e.colegio)) == antes + 1  # solo la madre tiene app
    assert client.get("/api/cuaderno/entradas?pendientes=true", headers=h).json()["entradas"] == []
    hilo = client.get(f"/api/familia/cuaderno/{eid}", headers=hf).json()["mensajes"]
    assert [(m["autor"], m["de_familia"]) for m in hilo] == [("Tú", True), ("Dir alfa", False)]


# --- Justificaciones y permisos de salida -------------------------------------------------

def test_justificacion_del_padre_y_aprobacion(client, db, e, h, hf):
    r = client.post("/api/familia/cuaderno/justificaciones", headers=hf, data={"datos": json.dumps({
        "alumno_id": e.a1.id, "desde": str(HOY - timedelta(days=2)), "hasta": str(HOY - timedelta(days=1)),
        "motivo": "Fiebre"})}, files=[("archivos", ("certificado.pdf", PDF, "application/pdf"))])
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert r.json()["estado"] == "pendiente"
    ent = db.get(EntradaCuaderno, eid)
    assert ent.apoderado_autor_id == e.madre.id and ent.creado_por_id is None
    # Quien la envió no recibe aviso de su propia justificación; el padre no tiene app.
    assert cola_cuaderno(db, e.colegio) == []

    det = client.get(f"/api/cuaderno/entradas/{eid}", headers=h).json()
    assert det["de_familia"] and det["autor"] == "Rosa Mamani" and len(det["adjuntos"]) == 1
    assert client.get("/api/cuaderno/entradas?pendientes=true", headers=h).json()["entradas"][0]["id"] == eid

    r = client.post(f"/api/cuaderno/entradas/{eid}/resolver", json={"estado": "aprobada"}, headers=h)
    assert r.status_code == 200
    assert [a.datos["mensaje"] for a in cola_cuaderno(db, e.colegio)] == ["Justificación de Niño0: aprobada."]
    assert client.post(f"/api/cuaderno/entradas/{eid}/resolver", json={"estado": "rechazada"},
                       headers=h).status_code == 409
    assert client.get(f"/api/familia/cuaderno/{eid}", headers=hf).json()["estado"] == "aprobada"


def test_justificacion_solo_de_sus_hijos_y_en_fechas_validas(client, e, hf):
    def justificar(**datos):
        base = {"alumno_id": e.a1.id, "desde": str(HOY), "motivo": "Cita médica"}
        return client.post("/api/familia/cuaderno/justificaciones", headers=hf,
                           data={"datos": json.dumps(base | datos)})

    assert justificar(alumno_id=e.a3.id).status_code == 404  # no es su hijo
    assert justificar(desde=str(HOY - timedelta(days=200))).status_code == 422
    assert justificar(hasta=str(HOY - timedelta(days=1))).status_code == 422
    assert justificar().status_code == 201


def test_resolver_solo_justificaciones_y_permisos(client, e, h):
    eid = escribir(client, h, tipo="incidencia", alumno_id=e.a1.id).json()["id"]
    assert client.post(f"/api/cuaderno/entradas/{eid}/resolver", json={"estado": "aprobada"},
                       headers=h).status_code == 400


def test_lo_que_registra_el_colegio_ya_queda_aprobado(client, db, e, h):
    r = escribir(client, h, tipo="justificacion", alumno_id=e.a1.id, desde=str(HOY), titulo="Trajo constancia")
    assert db.get(EntradaCuaderno, r.json()["id"]).estado == "aprobada"


def test_permiso_de_salida_en_la_porteria(client, db, e, h, hf):
    r = client.post("/api/familia/cuaderno/permisos-salida", headers=hf, json={
        "alumno_id": e.a1.id, "fecha": str(HOY), "hora": "10:30", "recoge": "Rosa Mamani (madre)",
        "motivo": "Cita médica"})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert client.post("/api/familia/cuaderno/permisos-salida", headers=hf, json={
        "alumno_id": e.a1.id, "fecha": str(HOY - timedelta(days=1)), "hora": "10:30", "recoge": "X",
        "motivo": "Y"}).status_code == 422

    padron = client.get("/api/asistencia/porteria", headers=h).json()
    assert padron["permisos_salida"] == {str(e.a1.id): {"hora": "10:30", "recoge": "Rosa Mamani (madre)",
                                                        "motivo": "Cita médica", "estado": "pendiente"}}
    client.post(f"/api/cuaderno/entradas/{eid}/resolver", json={"estado": "aprobada"}, headers=h)
    padron = client.get("/api/asistencia/porteria", headers=h).json()
    assert padron["permisos_salida"][str(e.a1.id)]["estado"] == "aprobada"

    # Al marcar la salida, la portería recibe el permiso.
    def marca(minutos_atras):
        from datetime import UTC, datetime
        momento = (datetime.now(UTC) - timedelta(minutes=minutos_atras)).isoformat()
        return client.post("/api/asistencia/marcaciones", headers=h, json={"marcaciones": [
            {"id_cliente": uuid.uuid4().hex, "alumno_id": e.a1.id, "momento": momento}]}).json()["resultados"][0]

    entrada, salida = marca(60), marca(0)
    if HOY != (__import__("datetime").datetime.now(__import__("app.fechas", fromlist=["LIMA"]).LIMA)
               - timedelta(minutes=60)).date():
        pytest.skip("Corre justo después de medianoche")
    assert entrada["resultado"] == "entrada" and "permiso_salida" not in entrada
    assert salida["resultado"] == "salida"
    assert salida["permiso_salida"]["recoge"] == "Rosa Mamani (madre)"


# --- Docentes: solo sus secciones -------------------------------------------------------------

def docente(client, db, e: Escuela, secciones: list[Seccion], dni: str = "50000000") -> dict:
    u = crear_personal(db, e.colegio, dni, {"cuaderno": "editar"})
    u.rol.solo_sus_secciones = True
    db.commit()
    hd = auth("alfa", token(client, "alfa"))
    r = client.put(f"/api/cuaderno/secciones/{secciones[0].id}/docentes", json={"usuario_ids": [u.id]}, headers=hd)
    assert r.status_code == 200, r.text
    return auth("alfa", token(client, "alfa", dni))


def test_docente_solo_ve_y_escribe_en_sus_secciones(client, db, e, h):
    de_a = escribir(client, h, tipo="incidencia", alumno_id=e.a1.id).json()["id"]
    de_b = escribir(client, h, tipo="incidencia", alumno_id=e.a2.id).json()["id"]
    todos = escribir(client, h, tipo="comunicado", alcance="colegio").json()["id"]
    hd = docente(client, db, e, [e.sec_a])

    assert [x["id"] for x in client.get("/api/cuaderno/entradas", headers=hd).json()["entradas"]] == [de_a]
    assert client.get(f"/api/cuaderno/entradas/{de_b}", headers=hd).status_code == 404
    assert client.get(f"/api/cuaderno/entradas/{todos}", headers=hd).status_code == 404
    assert client.post(f"/api/cuaderno/entradas/{de_b}/respuestas", json={"cuerpo": "x"},
                       headers=hd).status_code == 404

    assert escribir(client, hd, tipo="comunicado", alcance="colegio").status_code == 403
    assert escribir(client, hd, tipo="comunicado", alcance="seccion", seccion_id=e.sec_b.id).status_code == 403
    assert escribir(client, hd, tipo="incidencia", alumno_id=e.a2.id).status_code == 403
    assert escribir(client, hd, tipo="comunicado", alcance="seccion", seccion_id=e.sec_a.id).status_code == 201
    assert escribir(client, hd, tipo="incidencia", alumno_id=e.a1.id).status_code == 201

    op = client.get("/api/cuaderno/opciones", headers=hd).json()
    assert op["todo_el_colegio"] is False and [s["id"] for s in op["secciones"]] == [e.sec_a.id]
    assert [a["id"] for a in client.get("/api/cuaderno/alumnos?q=ape", headers=hd).json()] == [e.a1.id]
    # El mismo rol sin la marca ve todo el colegio.
    rol = db.scalar(select(Rol).where(Rol.nombre == "Rol 50000000"))
    rol.solo_sus_secciones = False
    db.commit()
    assert len(client.get("/api/cuaderno/entradas", headers=hd).json()["entradas"]) == 5


def test_docente_sin_secciones_no_ve_nada(client, db, e, h):
    escribir(client, h, tipo="incidencia", alumno_id=e.a1.id)
    u = crear_personal(db, e.colegio, "50000001", {"cuaderno": "ver"})
    u.rol.solo_sus_secciones = True
    db.commit()
    hd = auth("alfa", token(client, "alfa", "50000001"))
    assert client.get("/api/cuaderno/entradas", headers=hd).json()["entradas"] == []


def test_marca_del_rol_desde_el_panel(client, e, h):
    r = client.post("/api/roles", headers=h, json={"nombre": "Tutor", "permisos": {"cuaderno": "editar"},
                                                    "solo_sus_secciones": True})
    assert r.status_code == 201 and r.json()["solo_sus_secciones"] is True
    roles = {x["nombre"]: x["solo_sus_secciones"] for x in client.get("/api/roles", headers=h).json()}
    assert roles == {"Director": False, "Tutor": True}


def test_permisos_del_modulo(client, db, e, h):
    eid = escribir(client, h, tipo="incidencia", alumno_id=e.a1.id).json()["id"]
    crear_personal(db, e.colegio, "50000002", {"cuaderno": "ver"})
    crear_personal(db, e.colegio, "50000003", {"asistencia": "editar"})
    hv = auth("alfa", token(client, "alfa", "50000002"))
    hn = auth("alfa", token(client, "alfa", "50000003"))
    assert client.get(f"/api/cuaderno/entradas/{eid}", headers=hv).status_code == 200
    assert escribir(client, hv, tipo="incidencia", alumno_id=e.a1.id).status_code == 403
    assert client.post(f"/api/cuaderno/entradas/{eid}/respuestas", json={"cuerpo": "x"}, headers=hv).status_code == 403
    assert client.get("/api/cuaderno/entradas", headers=hn).status_code == 403
    assert client.get("/api/cuaderno/docentes", headers=hv).status_code == 403  # asignar es del padrón


# --- Envío por push ---------------------------------------------------------------------------

def test_la_cola_envia_el_aviso_del_cuaderno(client, db, e, h):
    db.add(SuscripcionPush(colegio_id=e.colegio.id, cuenta_id=e.madre.cuenta_id, endpoint="https://push.test/1",
                           p256dh="k", auth="a"))
    db.commit()
    eid = escribir(client, h, tipo="comunicado", alcance="alumno", alumno_id=e.a1.id, titulo="Paseo").json()["id"]
    enviados = []
    avisos.procesar_cola(db, enviar=lambda sus, m: enviados.append(m) or "ok")
    assert enviados == [{"titulo": "Colegio alfa", "cuerpo": "Comunicado: Paseo",
                         "url": f"/familia/cuaderno/{eid}", "etiqueta": f"cuaderno-{cola_cuaderno(db, e.colegio)[0].id}"}]
    entrega = db.scalar(select(EntregaAviso).where(EntregaAviso.apoderado_id == e.madre.id))
    assert entrega.estado == "enviado"


def test_aviso_del_cuaderno_no_llega_a_cuenta_bloqueada(client, db, e, h):
    escribir(client, h, tipo="comunicado", alcance="alumno", alumno_id=e.a1.id)
    e.madre.estado_acceso = "bloqueado"
    db.commit()
    avisos.procesar_cola(db, enviar=lambda sus, m: "ok")
    assert cola_cuaderno(db, e.colegio)[0].estado == "sin_destinatarios"


# --- Aislamiento entre colegios -------------------------------------------------------------

def test_otro_colegio_no_ve_ni_toca_el_cuaderno(client, db, e, h, hf):
    beta = preparar(db, "beta")
    eid = escribir(client, h, archivos=[("archivos", ("a.pdf", PDF, "application/pdf"))],
                   tipo="justificacion", alumno_id=e.a1.id, desde=str(HOY)).json()["id"]
    adj = db.scalar(select(AdjuntoCuaderno.id))
    hb = auth("beta", token(client, "beta"))
    assert client.get("/api/cuaderno/entradas", headers=hb).json()["entradas"] == []
    for metodo, ruta, cuerpo in (
            ("GET", f"/api/cuaderno/entradas/{eid}", None),
            ("POST", f"/api/cuaderno/entradas/{eid}/respuestas", {"cuerpo": "x"}),
            ("POST", f"/api/cuaderno/entradas/{eid}/resolver", {"estado": "rechazada"}),
            ("GET", f"/api/cuaderno/adjuntos/{adj}", None),
            ("PUT", f"/api/cuaderno/secciones/{e.sec_a.id}/docentes", {"usuario_ids": []})):
        assert client.request(metodo, ruta, json=cuerpo, headers=hb).status_code == 404, ruta
    # Escribir a un nivel, sección o alumno de alfa desde beta: 404, como si no existiera.
    for datos in ({"alcance": "nivel", "nivel_id": e.primaria.id}, {"alcance": "grado", "grado_id": e.grado1.id},
                  {"alcance": "seccion", "seccion_id": e.sec_a.id}, {"alcance": "alumno", "alumno_id": e.a1.id}):
        assert escribir(client, hb, tipo="comunicado", **datos).status_code == 404, datos
    # Asignar a una sección de beta a alguien de alfa.
    dir_alfa = db.scalar(select(Usuario.id).where(Usuario.colegio_id == e.colegio.id))
    r = client.put(f"/api/cuaderno/secciones/{beta.sec_a.id}/docentes", json={"usuario_ids": [dir_alfa]}, headers=hb)
    assert r.status_code == 422
    # La portería de beta no ve permisos de alfa.
    assert client.get("/api/asistencia/porteria", headers=hb).json()["permisos_salida"] == {}
    assert db.get(EntradaCuaderno, eid).estado == "aprobada"


def test_familia_de_otro_colegio_no_ve_el_cuaderno(client, db, e, h):
    # La misma persona es apoderada en beta: con la dirección de beta solo ve lo de beta.
    beta = preparar(db, "beta")
    eid = escribir(client, h, tipo="incidencia", alumno_id=e.a1.id,
                   archivos=[("archivos", ("a.pdf", PDF, "application/pdf"))]).json()["id"]
    adj = db.scalar(select(AdjuntoCuaderno.id))
    hfb = auth("beta", token_familia(client, "beta"))
    assert client.get("/api/familia/cuaderno", headers=hfb).json()["entradas"] == []
    for metodo, ruta in (("GET", f"/api/familia/cuaderno/{eid}"), ("POST", f"/api/familia/cuaderno/{eid}/firmar"),
                         ("GET", f"/api/familia/cuaderno/adjuntos/{adj}")):
        assert client.request(metodo, ruta, headers=hfb).status_code == 404, ruta
    # Pedir algo para un hijo de alfa desde beta.
    r = client.post("/api/familia/cuaderno/permisos-salida", headers=hfb, json={
        "alumno_id": e.a1.id, "fecha": str(HOY), "hora": "10:00", "recoge": "X", "motivo": "Y"})
    assert r.status_code == 404
    assert beta.a1.id != e.a1.id


def test_base_rechaza_cuaderno_cruzado(db, e):
    beta = preparar(db, "beta")
    ent = EntradaCuaderno(colegio_id=e.colegio.id, tipo="incidencia", alcance="alumno", alumno_id=beta.a1.id,
                          titulo="x")
    db.add(ent)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    ent = EntradaCuaderno(colegio_id=e.colegio.id, tipo="incidencia", alcance="alumno", alumno_id=e.a1.id, titulo="x")
    db.add(ent)
    db.commit()
    db.add(DestinoCuaderno(colegio_id=e.colegio.id, entrada_id=ent.id, alumno_id=e.a1.id, apoderado_id=beta.madre.id))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize("campos", [
    {"tipo": "incidencia", "alcance": "colegio"},  # solo los comunicados van a varios
    {"tipo": "citacion", "alcance": "alumno"},  # sin fecha
    {"tipo": "justificacion", "alcance": "alumno", "estado": "pendiente"},  # sin fechas
    {"tipo": "comunicado", "alcance": "alumno", "estado": "pendiente"},  # un comunicado no se aprueba
])
def test_base_rechaza_entradas_incoherentes(db, e, campos):
    if campos["alcance"] == "alumno":
        campos["alumno_id"] = e.a1.id
    db.add(EntradaCuaderno(colegio_id=e.colegio.id, titulo="x", **campos))
    with pytest.raises(IntegrityError):
        db.commit()


def test_borrar_la_seccion_conserva_las_entradas(db, e):
    ent = EntradaCuaderno(colegio_id=e.colegio.id, tipo="comunicado", alcance="alumno", alumno_id=e.a3.id,
                          seccion_id=e.sec_secundaria.id, titulo="x")
    db.add(ent)
    db.commit()
    db.execute(Matricula.__table__.delete().where(Matricula.seccion_id == e.sec_secundaria.id))
    db.delete(e.sec_secundaria)
    db.commit()
    db.refresh(ent)
    assert ent.seccion_id is None and ent.colegio_id == e.colegio.id


# --- Justificación aprobada -> falta "justificada" ------------------------------------------

def _falta(db, e: Escuela, alumno: Alumno, fecha: date) -> None:
    from app.models import AsistenciaAlumno
    db.add(AsistenciaAlumno(colegio_id=e.colegio.id, alumno_id=alumno.id, fecha=fecha, seccion_id=e.sec_a.id,
                            estado="falta"))
    db.add(ColaAviso(colegio_id=e.colegio.id, alumno_id=alumno.id, fecha=fecha, tipo="falta"))
    db.commit()


def _estado(db, alumno: Alumno, fecha: date) -> tuple[str, int | None]:
    from app.models import AsistenciaAlumno
    db.expire_all()
    f = db.scalar(select(AsistenciaAlumno).where(AsistenciaAlumno.alumno_id == alumno.id,
                                                 AsistenciaAlumno.fecha == fecha))
    return (f.estado, f.justificacion_id) if f else (None, None)


def _justificar(client, hf, alumno, desde, hasta=None):
    r = client.post("/api/familia/cuaderno/justificaciones", headers=hf, data={"datos": json.dumps({
        "alumno_id": alumno.id, "desde": str(desde), "hasta": str(hasta or desde), "motivo": "Fiebre"})})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_justificacion_aprobada_cambia_la_falta_y_se_revierte_al_anular(client, db, e, h, hf):
    ayer, anteayer = HOY - timedelta(days=1), HOY - timedelta(days=2)
    _falta(db, e, e.a1, ayer)
    _falta(db, e, e.a1, anteayer)
    eid = _justificar(client, hf, e.a1, anteayer, ayer)
    assert _estado(db, e.a1, ayer) == ("falta", None)  # pendiente: aún no cambia nada

    r = client.post(f"/api/cuaderno/entradas/{eid}/resolver", json={"estado": "aprobada"}, headers=h)
    assert r.json()["faltas_justificadas"] == 2
    assert _estado(db, e.a1, ayer) == ("justificada", eid)
    # El aviso de falta que no había salido ya no sale.
    assert db.scalar(select(ColaAviso.id).where(ColaAviso.tipo == "falta")) is None
    # En los reportes.
    dia = client.get(f"/api/asistencia/dia?fecha={ayer}", headers=h).json()
    assert dia["totales"]["justificada"] == 1 and dia["totales"]["falta"] == 0
    detalle = client.get(f"/api/asistencia/dia?fecha={ayer}&seccion_id={e.sec_a.id}", headers=h).json()
    assert [a["estado"] for a in detalle["alumnos"]] == ["justificada"]
    hoja = client.get(f"/api/asistencia/mensual.xlsx?anio={ayer.year}&mes={ayer.month}&seccion_id={e.sec_a.id}",
                      headers=h)
    from io import BytesIO

    from openpyxl import load_workbook
    ws = load_workbook(BytesIO(hoja.content)).active
    assert "J" in [c.value for c in ws[3]] and ws.cell(2, ws.max_column).value == "Justificadas"

    r = client.post(f"/api/cuaderno/entradas/{eid}/anular", json={"motivo": "Certificado no válido"}, headers=h)
    assert r.status_code == 200 and r.json() == {"id": eid, "estado": "anulada", "faltas_restituidas": 2}
    assert _estado(db, e.a1, ayer) == ("falta", None)
    assert "anulada" in cola_cuaderno(db, e.colegio)[-1].datos["mensaje"]
    det = client.get(f"/api/cuaderno/entradas/{eid}", headers=h).json()
    assert det["motivo_anulacion"] == "Certificado no válido" and det["anulada_por"] == "Dir alfa"
    assert client.post(f"/api/cuaderno/entradas/{eid}/anular", json={"motivo": "x"}, headers=h).status_code == 409


def test_falta_marcada_despues_ya_nace_justificada(client, db, e, h, hf):
    from app import asistencia
    eid = _justificar(client, hf, e.a1, HOY)
    client.post(f"/api/cuaderno/entradas/{eid}/resolver", json={"estado": "aprobada"}, headers=h)
    asistencia.marcar_faltas(db, HOY)
    db.commit()
    assert _estado(db, e.a1, HOY) == ("justificada", eid)
    assert _estado(db, e.a2, HOY) == ("falta", None)
    avisos_falta = db.scalars(select(ColaAviso.alumno_id).where(ColaAviso.tipo == "falta")).all()
    assert sorted(avisos_falta) == [e.a2.id, e.a3.id]  # al justificado no se le avisa falta


def test_anular_una_deja_la_otra_justificacion(client, db, e, h, hf):
    ayer = HOY - timedelta(days=1)
    _falta(db, e, e.a1, ayer)
    primera = _justificar(client, hf, e.a1, ayer)
    segunda = _justificar(client, hf, e.a1, ayer - timedelta(days=1), ayer)
    for eid in (primera, segunda):
        client.post(f"/api/cuaderno/entradas/{eid}/resolver", json={"estado": "aprobada"}, headers=h)
    assert _estado(db, e.a1, ayer) == ("justificada", primera)
    client.post(f"/api/cuaderno/entradas/{primera}/anular", json={"motivo": "Duplicada"}, headers=h)
    assert _estado(db, e.a1, ayer) == ("justificada", segunda)


def test_si_llega_el_dia_justificado_queda_presente(client, db, e, h, hf):
    from datetime import UTC, datetime
    eid = _justificar(client, hf, e.a1, HOY)
    client.post(f"/api/cuaderno/entradas/{eid}/resolver", json={"estado": "aprobada"}, headers=h)
    r = client.post("/api/asistencia/marcaciones", headers=h, json={"marcaciones": [
        {"id_cliente": uuid.uuid4().hex, "alumno_id": e.a1.id, "momento": datetime.now(UTC).isoformat()}]})
    assert r.json()["resultados"][0]["estado_dia"] in ("presente", "tarde")


def test_solo_se_anula_lo_aprobado(client, db, e, h, hf):
    pendiente = _justificar(client, hf, e.a1, HOY)
    assert client.post(f"/api/cuaderno/entradas/{pendiente}/anular", json={"motivo": "x"},
                       headers=h).status_code == 409
    incidencia = escribir(client, h, tipo="incidencia", alumno_id=e.a1.id).json()["id"]
    assert client.post(f"/api/cuaderno/entradas/{incidencia}/anular", json={"motivo": "x"},
                       headers=h).status_code == 409


def test_otro_colegio_no_anula(client, db, e, h, hf):
    preparar(db, "beta")
    eid = _justificar(client, hf, e.a1, HOY)
    client.post(f"/api/cuaderno/entradas/{eid}/resolver", json={"estado": "aprobada"}, headers=h)
    hb = auth("beta", token(client, "beta"))
    assert client.post(f"/api/cuaderno/entradas/{eid}/anular", json={"motivo": "x"}, headers=hb).status_code == 404
    assert db.get(EntradaCuaderno, eid).estado == "aprobada"


def test_base_rechaza_justificacion_de_otro_colegio_en_la_asistencia(db, e):
    from app.models import AsistenciaAlumno
    beta = preparar(db, "beta")
    j = EntradaCuaderno(colegio_id=beta.colegio.id, tipo="justificacion", alcance="alumno", alumno_id=beta.a1.id,
                        titulo="x", desde=HOY, hasta=HOY, estado="aprobada")
    db.add(j)
    db.commit()
    db.add(AsistenciaAlumno(colegio_id=e.colegio.id, alumno_id=e.a1.id, fecha=HOY, estado="justificada",
                            justificacion_id=j.id))
    with pytest.raises(IntegrityError):
        db.commit()
