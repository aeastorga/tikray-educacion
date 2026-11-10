"""Autorizaciones: crear, publicar y a quién va; responder por cada hijo (A2, A3, A4, A6); conteos y lista por
sección (docente con "solo sus secciones"); avisos al publicar, recordatorio del día anterior y "Recordar" (solo a
pendientes, sin repetir, con el horario sin molestar); anular, cerrar, adjunto, PDF y Excel, módulo apagado,
aislamiento y migración."""

import os
from datetime import UTC, datetime, time, timedelta
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy import select, text

from app import autorizaciones, avisos
from app.db import get_engine
from app.fechas import LIMA
from app.models import (AlumnoApoderado, ColaAviso, Colegio, RegistroActividad, RespuestaAutorizacion,
                        SeccionDocente)
from app.models.colegio import INCLUIDOS
from tests.conftest import auth, crear_familia, crear_personal, hoy, token, token_familia
from tests.test_familias import Push, fam, suscribir
from tests.test_pensiones import preparar as preparar_escuela

PDF = b"%PDF-1.4\n%prueba\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


def preparar(db, sub: str, otra: bool = False):
    """a1 (Primaria 1° A) y a2 (Primaria 2° A), hijos de la madre (con cuenta); a1 también tiene un padre sin
    cuenta. a3 (Secundaria 1° A); con `otra`, hijo de otra madre (con cuenta)."""
    e = preparar_escuela(db, sub)
    if otra:
        e.otra = crear_familia(db, e.colegio, "42222222", [e.a3])
    return e


def crear(client, h, titulo="Paseo al zoológico", esperado=201, publicar=True, **extra) -> dict:
    datos = {"titulo": titulo, "fecha_limite": (hoy() + timedelta(days=5)).isoformat(), **extra}
    r = client.post("/api/autorizaciones", headers=h, json=datos)
    assert r.status_code == esperado, r.text
    if esperado != 201 or not publicar:
        return r.json()
    p = client.post(f"/api/autorizaciones/{r.json()['id']}/publicar", headers=h)
    assert p.status_code == 200, p.text
    return p.json()


def responder(client, hf, aid: int, alumno_id: int, autoriza=True, esperado=200, **extra):
    r = client.post(f"/api/familia/autorizaciones/{aid}/respuestas", headers=hf,
                    json={"alumno_id": alumno_id, "autoriza": autoriza, **extra})
    assert r.status_code == esperado, r.text
    return r.json()


def cola(db) -> list[ColaAviso]:
    db.expire_all()
    return list(db.scalars(select(ColaAviso).where(ColaAviso.tipo == "autorizar").order_by(ColaAviso.id)))


def enviar(db, ahora: datetime | None = None) -> list[str]:
    push = Push()
    avisos.procesar_cola(db, push, ahora=ahora or datetime.now(UTC) + timedelta(seconds=5))
    return [m["cuerpo"] for _, m in push.enviados]


def detalle(client, h, aid: int) -> dict:
    r = client.get(f"/api/autorizaciones/{aid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def docente(client, db, e, secciones, dni="50000000", nivel="editar") -> dict:
    u = crear_personal(db, e.colegio, dni, {"autorizaciones": nivel})
    u.rol.solo_sus_secciones = True
    db.add_all([SeccionDocente(colegio_id=e.colegio.id, seccion_id=s.id, usuario_id=u.id) for s in secciones])
    db.commit()
    return auth(e.colegio.subdominio, token(client, e.colegio.subdominio, dni))


# --- Crear y publicar -------------------------------------------------------------------------------

def test_borrador_publicar_y_a_quien_va(client, db):
    e = preparar(db, "alfa", otra=True)
    h = auth("alfa", token(client, "alfa"))
    hf = fam("alfa", token_familia(client, "alfa"))
    b = crear(client, h, "Uso de fotos", publicar=False, alcance="niveles", niveles=[e.primaria.id],
              descripcion="Para la web del colegio.\nNo se publican nombres.")
    assert b["estado"] == "borrador" and b["para"] == "Primaria" and b["conteo"]["total"] == 2
    assert client.get("/api/familia/autorizaciones", headers=hf).json() == []  # un borrador no sale
    assert cola(db) == []
    # En borrador se cambia todo; luego se publica.
    r = client.put(f"/api/autorizaciones/{b['id']}", headers=h, json={
        "titulo": "Uso de fotos", "fecha_limite": (hoy() + timedelta(days=3)).isoformat(), "alcance": "secciones",
        "secciones": [e.s1.id]})
    assert r.status_code == 200 and r.json()["conteo"]["total"] == 1, r.text
    p = client.post(f"/api/autorizaciones/{b['id']}/publicar", headers=h).json()
    assert p["estado"] == "publicada" and p["avisos"] == 1
    assert client.post(f"/api/autorizaciones/{b['id']}/publicar", headers=h).status_code == 409
    # Publicada: los textos y las fechas sí; a quién va, no.
    otra = {"titulo": "Uso de fotos 2026", "fecha_limite": (hoy() + timedelta(days=4)).isoformat(),
            "alcance": "secciones", "secciones": [e.s1.id]}
    assert client.put(f"/api/autorizaciones/{b['id']}", headers=h, json=otra).status_code == 200
    assert client.put(f"/api/autorizaciones/{b['id']}", headers=h,
                      json=otra | {"secciones": [e.s1.id, e.s2.id]}).status_code == 409
    # Alumnos sueltos y todo el colegio.
    sueltos = crear(client, h, "Taller", alcance="alumnos", alumnos=[e.a2.id, e.a3.id])
    assert sueltos["para"] == "2 alumnos" and sueltos["conteo"]["total"] == 2
    todos = crear(client, h, "Actuación", alcance="colegio")
    assert todos["conteo"]["total"] == 3
    # La familia ve solo las de sus hijos y por cuál.
    lista = {x["titulo"]: [hj["nombre"] for hj in x["hijos"]]
             for x in client.get("/api/familia/autorizaciones", headers=hf).json()}
    assert lista == {"Uso de fotos 2026": ["Niño0"], "Taller": ["Niño1"], "Actuación": ["Niño0", "Niño1"]}
    acciones = set(db.scalars(select(RegistroActividad.accion).where(RegistroActividad.modulo == "autorizaciones")))
    assert {"crear", "editar"} <= acciones


def test_validaciones(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    ayer = (hoy() - timedelta(days=1)).isoformat()
    crear(client, h, fecha_limite=ayer, esperado=422)
    crear(client, h, alcance="secciones", esperado=422)  # sin secciones
    crear(client, h, alcance="alumnos", alumnos=[999999], esperado=422)
    crear(client, h, fecha_actividad=hoy().isoformat(), esperado=422)  # el límite después de la actividad
    crear(client, h, titulo="  ", esperado=422)


# --- Responder ---------------------------------------------------------------------------------------

def test_responder_cambiar_y_rechazo_despues_de_la_fecha_limite(client, db):
    """A3: se cambia hasta la fecha límite y cada cambio queda; A4: después ya no, y sin respuesta no cuenta."""
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    hf = fam("alfa", token_familia(client, "alfa"))
    a = crear(client, h, alcance="secciones", secciones=[e.s1.id, e.s2.id])
    r = responder(client, hf, a["id"], e.a1.id, False, comentario="  Tiene   fiebre ")
    hijo = next(x for x in r["hijos"] if x["alumno_id"] == e.a1.id)
    assert hijo["respuesta"]["autoriza"] is False and hijo["respuesta"]["comentario"] == "Tiene fiebre"
    assert hijo["respuesta"]["mia"] is True and hijo["respuesta"]["apoderado"].startswith(e.madre.nombres)
    responder(client, hf, a["id"], e.a1.id, True)
    d = detalle(client, h, a["id"])
    assert d["conteo"] == {"total": 2, "autorizan": 1, "no_autorizan": 0, "faltan": 1}
    fila = next(f for s in d["por_seccion"] for f in s["alumnos"] if f["alumno_id"] == e.a1.id)
    assert [x["autoriza"] for x in fila["historial"]] == [False, True] and fila["estado"] == "autoriza"
    guardadas = db.scalars(select(RespuestaAutorizacion)).all()  # Ley 29733: fecha, hora y quién
    assert all(x.respondido_en and x.apoderado_documento == e.madre.numero_documento for x in guardadas)
    # Vence: la fecha límite queda en el pasado.
    db.execute(text("UPDATE autorizacion SET fecha_limite = :f"), {"f": hoy() - timedelta(days=1)})
    db.commit()
    responder(client, hf, a["id"], e.a2.id, True, esperado=409)
    d = detalle(client, h, a["id"])
    assert d["estado"] == "cerrada" and d["conteo"]["faltan"] == 1 and d["conteo"]["autorizan"] == 1
    assert client.get("/api/familia/autorizaciones", headers=hf).json()[0]["pendiente"] is False


def test_dos_apoderados_responden_distinto_vale_la_ultima(client, db):
    """A2: basta la respuesta de uno; si responden distinto, vale la última y quedan las dos en el historial."""
    e = preparar(db, "alfa")
    crear_familia(db, e.colegio, "42222222", [e.a1])
    h = auth("alfa", token(client, "alfa"))
    madre = fam("alfa", token_familia(client, "alfa"))
    otro = fam("alfa", token_familia(client, "alfa", dni="42222222"))
    a = crear(client, h, alcance="alumnos", alumnos=[e.a1.id])
    responder(client, madre, a["id"], e.a1.id, True)
    r = responder(client, otro, a["id"], e.a1.id, False)
    assert r["hijos"][0]["respuesta"]["autoriza"] is False and r["hijos"][0]["respuesta"]["mia"] is True
    vista_madre = client.get("/api/familia/autorizaciones", headers=madre).json()[0]["hijos"][0]["respuesta"]
    assert vista_madre["autoriza"] is False and vista_madre["mia"] is False
    d = detalle(client, h, a["id"])
    assert d["conteo"] == {"total": 1, "autorizan": 0, "no_autorizan": 1, "faltan": 0}
    assert [x["autoriza"] for x in d["por_seccion"][0]["alumnos"][0]["historial"]] == [True, False]
    guardadas = db.scalars(select(RespuestaAutorizacion).order_by(RespuestaAutorizacion.id)).all()
    assert [(x.apoderado_documento, x.autoriza) for x in guardadas] == [(e.madre.numero_documento, True),
                                                                         ("42222222", False)]


def test_solo_responde_quien_recibe_avisos(client, db):
    """A6: el apoderado que no recibe los avisos de ese alumno ve la autorización pero no responde."""
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    hf = fam("alfa", token_familia(client, "alfa"))
    vinculo = db.scalar(select(AlumnoApoderado).where(AlumnoApoderado.alumno_id == e.a2.id,
                                                      AlumnoApoderado.apoderado_id == e.madre.id))
    vinculo.recibe_avisos = False
    db.commit()
    a = crear(client, h, alcance="alumnos", alumnos=[e.a1.id, e.a2.id])
    hijos = {x["alumno_id"]: x["puede_responder"]
             for x in client.get("/api/familia/autorizaciones", headers=hf).json()[0]["hijos"]}
    assert hijos == {e.a1.id: True, e.a2.id: False}
    responder(client, hf, a["id"], e.a2.id, True, esperado=403)
    responder(client, hf, a["id"], e.a1.id, True)


def test_pendientes_arriba_en_la_familia(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    hf = fam("alfa", token_familia(client, "alfa"))
    vieja = crear(client, h, "Respondida", alcance="alumnos", alumnos=[e.a1.id])
    responder(client, hf, vieja["id"], e.a1.id, True)
    crear(client, h, "Lejana", alcance="alumnos", alumnos=[e.a1.id], fecha_limite=(hoy() + timedelta(days=9)).isoformat())
    crear(client, h, "Cercana", alcance="alumnos", alumnos=[e.a1.id], fecha_limite=(hoy() + timedelta(days=2)).isoformat())
    lista = client.get("/api/familia/autorizaciones", headers=hf).json()
    assert [x["titulo"] for x in lista] == ["Cercana", "Lejana", "Respondida"]
    assert [x["pendiente"] for x in lista] == [True, True, False]


# --- Seguimiento -------------------------------------------------------------------------------------

def test_conteos_y_lista_por_seccion_y_docente_solo_sus_secciones(client, db):
    e = preparar(db, "alfa", otra=True)
    h = auth("alfa", token(client, "alfa"))
    madre = fam("alfa", token_familia(client, "alfa"))
    otra = fam("alfa", token_familia(client, "alfa", dni="42222222"))
    a = crear(client, h, alcance="colegio")
    responder(client, madre, a["id"], e.a1.id, True)
    responder(client, otra, a["id"], e.a3.id, False)
    d = detalle(client, h, a["id"])
    assert d["conteo"] == {"total": 3, "autorizan": 1, "no_autorizan": 1, "faltan": 1}
    assert [(s["seccion"], s["conteo"]["autorizan"], s["conteo"]["no_autorizan"], s["conteo"]["faltan"])
            for s in d["por_seccion"]] == [("1° A Primaria", 1, 0, 0), ("2° A Primaria", 0, 0, 1),
                                         ("1° A Secundaria", 0, 1, 0)]
    # Docente de 1° A Primaria: solo su sección (en la lista, el detalle, los conteos y los archivos).
    hd = docente(client, db, e, [e.s1])
    [visto] = client.get("/api/autorizaciones", headers=hd).json()
    assert visto["conteo"] == {"total": 1, "autorizan": 1, "no_autorizan": 0, "faltan": 0}
    dd = detalle(client, hd, a["id"])
    assert [s["seccion"] for s in dd["por_seccion"]] == ["1° A Primaria"] and dd["conteo"]["total"] == 1
    hoja = load_workbook(BytesIO(client.get(f"/api/autorizaciones/{a['id']}/lista.xlsx", headers=hd).content)).active
    assert [f[1] for f in hoja.iter_rows(min_row=3, values_only=True)] == ["Ape0, Niño0"]
    # No la cambia (va a todo el colegio) y no crea para otras secciones.
    assert client.post(f"/api/autorizaciones/{a['id']}/recordar", headers=hd).status_code == 403
    crear(client, hd, alcance="colegio", esperado=403)
    crear(client, hd, alcance="secciones", secciones=[e.s2.id], esperado=403)
    crear(client, hd, alcance="alumnos", alumnos=[e.a3.id], esperado=403)
    suya = crear(client, hd, "De mi sección", alcance="secciones", secciones=[e.s1.id])
    assert client.post(f"/api/autorizaciones/{suya['id']}/cerrar", headers=hd).status_code == 200
    # Otra que no toca sus secciones: no la ve (ni con el id).
    ajena = crear(client, h, "Secundaria", alcance="secciones", secciones=[e.ss.id])
    assert client.get(f"/api/autorizaciones/{ajena['id']}", headers=hd).status_code == 404
    assert {x["titulo"] for x in client.get("/api/autorizaciones", headers=hd).json()} == {
        "Paseo al zoológico", "De mi sección"}
    # Las opciones solo traen sus secciones; la búsqueda de alumnos, solo los suyos.
    o = client.get("/api/autorizaciones/opciones", headers=hd).json()
    assert [s["id"] for s in o["secciones"]] == [e.s1.id] and o["niveles"] == []
    assert [x["id"] for x in client.get("/api/autorizaciones/alumnos?q=Ape", headers=hd).json()] == [e.a1.id]


def test_lista_en_pdf_y_excel_por_seccion(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    hf = fam("alfa", token_familia(client, "alfa"))
    a = crear(client, h, alcance="niveles", niveles=[e.primaria.id], fecha_actividad=(hoy() + timedelta(days=8)).isoformat())
    responder(client, hf, a["id"], e.a2.id, False, comentario="Viaja")
    r = client.get(f"/api/autorizaciones/{a['id']}/lista.pdf", headers=h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"
    hoja = load_workbook(BytesIO(client.get(f"/api/autorizaciones/{a['id']}/lista.xlsx", headers=h).content)).active
    filas = list(hoja.iter_rows(min_row=3, values_only=True))
    assert [(f[0], f[1], f[2], f[5]) for f in filas] == [
        ("1° A Primaria", "Ape0, Niño0", "Sin respuesta", None), ("2° A Primaria", "Ape1, Niño1", "No autoriza", "Viaja")]
    solo = load_workbook(BytesIO(client.get(f"/api/autorizaciones/{a['id']}/lista.xlsx?seccion_id={e.s2.id}",
                                            headers=h).content)).active
    assert [f[1] for f in solo.iter_rows(min_row=3, values_only=True)] == ["Ape1, Niño1"]
    borrador = crear(client, h, "Sin publicar", publicar=False)
    assert client.get(f"/api/autorizaciones/{borrador['id']}/lista.pdf", headers=h).status_code == 409


# --- Avisos -------------------------------------------------------------------------------------------

def test_aviso_al_publicar_uno_por_apoderado(client, db):
    e = preparar(db, "alfa", otra=True)
    h = auth("alfa", token(client, "alfa"))
    suscribir(client, "alfa")
    a = crear(client, h, alcance="colegio")
    assert a["avisos"] == 2  # la madre (dos hijos, un aviso) y la otra madre; el padre no tiene cuenta
    assert sorted(x.apoderado_id for x in cola(db)) == sorted([e.madre.id, e.otra.id])
    [cuerpo] = enviar(db)  # solo la madre está suscrita
    assert cuerpo.startswith("Autorización: Paseo al zoológico. Responde hasta el ")


def test_recordatorio_del_dia_anterior_solo_a_pendientes_y_sin_repetir(client, db):
    e = preparar(db, "alfa", otra=True)
    h = auth("alfa", token(client, "alfa"))
    hf = fam("alfa", token_familia(client, "alfa"))
    limite = hoy() + timedelta(days=4)
    a = crear(client, h, alcance="colegio", fecha_limite=limite.isoformat())
    responder(client, hf, a["id"], e.a1.id, True)
    responder(client, hf, a["id"], e.a2.id, False)
    antes = len(cola(db))
    assert autorizaciones.revisar_recordatorios(db, limite - timedelta(days=2)) == 0  # todavía no
    assert autorizaciones.revisar_recordatorios(db, limite - timedelta(days=1)) == 1  # solo la otra madre
    nuevos = cola(db)[antes:]
    assert [x.apoderado_id for x in nuevos] == [e.otra.id] and nuevos[0].datos["que"] == "recordatorio"
    assert nuevos[0].datos["mensaje"] == "Falta tu respuesta: Paseo al zoológico. Vence mañana."
    assert autorizaciones.revisar_recordatorios(db, limite - timedelta(days=1)) == 0  # sin repetir
    # Si cambia la fecha límite, vuelve a tocar.
    r = client.put(f"/api/autorizaciones/{a['id']}", headers=h, json={
        "titulo": "Paseo al zoológico", "fecha_limite": (limite + timedelta(days=3)).isoformat(), "alcance": "colegio"})
    assert r.status_code == 200, r.text
    assert autorizaciones.revisar_recordatorios(db, limite + timedelta(days=2)) == 1


def test_con_fecha_limite_manana_el_aviso_de_publicacion_hace_de_recordatorio(client, db):
    preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    crear(client, h, fecha_limite=(hoy() + timedelta(days=1)).isoformat())
    n = len(cola(db))
    assert autorizaciones.revisar_recordatorios(db, hoy()) == 0 and len(cola(db)) == n


def test_boton_recordar_solo_a_pendientes_una_vez_al_dia(client, db):
    e = preparar(db, "alfa", otra=True)
    h = auth("alfa", token(client, "alfa"))
    hf = fam("alfa", token_familia(client, "alfa"))
    a = crear(client, h, alcance="colegio")
    responder(client, hf, a["id"], e.a1.id, True)
    antes = len(cola(db))
    # La madre tiene a a2 sin respuesta: le llega (una vez, aunque tenga dos hijos), y a la otra madre también.
    assert client.post(f"/api/autorizaciones/{a['id']}/recordar", headers=h).json() == {"avisos": 2}
    responder(client, hf, a["id"], e.a2.id, True)
    assert client.post(f"/api/autorizaciones/{a['id']}/recordar", headers=h).status_code == 409  # ya hoy
    db.execute(text("UPDATE autorizacion SET recordado_en = recordado_en - interval '1 day'"))
    db.commit()
    assert client.post(f"/api/autorizaciones/{a['id']}/recordar", headers=h).json() == {"avisos": 1}  # la otra
    nuevos = cola(db)[antes:]
    assert [x.apoderado_id for x in nuevos] == sorted([e.madre.id, e.otra.id]) + [e.otra.id]
    assert all(x.datos["que"] == "recordar" for x in nuevos)


def test_avisos_respetan_el_horario_sin_molestar_y_se_apagan(client, db):
    e = preparar(db, "alfa")
    e.colegio.silencio_desde, e.colegio.silencio_hasta = time(21, 0), time(6, 0)
    db.commit()
    h = auth("alfa", token(client, "alfa"))
    suscribir(client, "alfa")
    crear(client, h)
    noche = datetime.combine(hoy(), time(23, 0), LIMA).astimezone(UTC)
    [aviso] = cola(db)
    aviso.procesar_desde = noche - timedelta(minutes=1)  # encolado antes de la noche simulada
    db.commit()
    assert enviar(db, noche) == []
    [aviso] = cola(db)
    assert aviso.estado == "pendiente"
    assert aviso.procesar_desde == datetime.combine(hoy() + timedelta(days=1), time(6, 0), LIMA).astimezone(UTC)
    assert enviar(db, aviso.procesar_desde + timedelta(minutes=1)) != []
    # Apagado en Configuración › Avisos: no sale al publicar, ni el recordatorio, y "Recordar" avisa que está apagado.
    r = client.put("/api/configuracion/avisos", headers=h,
                   json={"tipos": {"autorizaciones": False}, "silencio_desde": "21:00", "silencio_hasta": "06:00"})
    assert r.status_code == 200, r.text
    limite = hoy() + timedelta(days=5)
    b = crear(client, h, "Otra", fecha_limite=limite.isoformat())
    assert b["avisos"] == 0 and len(cola(db)) == 1
    assert autorizaciones.revisar_recordatorios(db, limite - timedelta(days=1)) == 0
    assert client.post(f"/api/autorizaciones/{b['id']}/recordar", headers=h).status_code == 409


# --- Anular, cerrar, adjunto -------------------------------------------------------------------------

def test_anular_queda_visible_y_no_manda_recordatorios(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    hf = fam("alfa", token_familia(client, "alfa"))
    limite = hoy() + timedelta(days=4)
    a = crear(client, h, fecha_limite=limite.isoformat())
    assert client.post(f"/api/autorizaciones/{a['id']}/anular", headers=h, json={"motivo": " "}).status_code == 422
    r = client.post(f"/api/autorizaciones/{a['id']}/anular", headers=h, json={"motivo": "Se suspende el paseo"})
    assert r.status_code == 200 and r.json()["estado"] == "anulada"
    assert all(x.estado == "descartado" and x.datos["motivo"] == "autorización anulada" for x in cola(db))
    assert autorizaciones.revisar_recordatorios(db, limite - timedelta(days=1)) == 0
    assert client.post(f"/api/autorizaciones/{a['id']}/recordar", headers=h).status_code == 409
    [visto] = client.get("/api/familia/autorizaciones", headers=hf).json()
    assert visto["estado"] == "anulada" and visto["anulado_motivo"] == "Se suspende el paseo"
    responder(client, hf, a["id"], e.a1.id, True, esperado=409)
    assert detalle(client, h, a["id"])["estado"] == "anulada"
    assert client.post(f"/api/autorizaciones/{a['id']}/anular", headers=h, json={"motivo": "x"}).status_code == 409
    # Un borrador también se anula y queda visible (solo en el colegio).
    b = crear(client, h, "Borrador", publicar=False)
    assert client.post(f"/api/autorizaciones/{b['id']}/anular", headers=h, json={"motivo": "No va"}).status_code == 200
    assert {x["titulo"]: x["estado"] for x in client.get("/api/autorizaciones", headers=h).json()} == {
        "Paseo al zoológico": "anulada", "Borrador": "anulada"}


def test_cerrar_a_mano(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    hf = fam("alfa", token_familia(client, "alfa"))
    a = crear(client, h)
    assert client.post(f"/api/autorizaciones/{a['id']}/cerrar", headers=h).json()["estado"] == "cerrada"
    responder(client, hf, a["id"], e.a1.id, True, esperado=409)
    assert client.post(f"/api/autorizaciones/{a['id']}/cerrar", headers=h).status_code == 409


def test_adjunto_privado_pdf_o_imagen_hasta_5_mb(client, db):
    e = preparar(db, "alfa", otra=True)
    h = auth("alfa", token(client, "alfa"))
    a = crear(client, h, publicar=False, alcance="alumnos", alumnos=[e.a1.id])
    ruta = f"/api/autorizaciones/{a['id']}/adjunto"
    assert client.put(ruta, headers=h, files={"archivo": ("x.txt", b"hola", "text/plain")}).status_code == 422
    grande = PDF + b"0" * (5 * 1024 * 1024)
    assert client.put(ruta, headers=h, files={"archivo": ("g.pdf", grande, "application/pdf")}).status_code == 422
    r = client.put(ruta, headers=h, files={"archivo": ("permiso.pdf", PDF, "application/pdf")})
    assert r.status_code == 200 and r.json()["adjunto"]["nombre"] == "permiso.pdf"
    r = client.put(ruta, headers=h, files={"archivo": ("mapa.png", PNG, "image/png")})  # reemplaza
    assert r.json()["adjunto"]["tipo"] == "image/png"
    client.post(f"/api/autorizaciones/{a['id']}/publicar", headers=h)
    assert client.get(ruta, headers=h).content == PNG
    madre = fam("alfa", token_familia(client, "alfa"))
    otra = fam("alfa", token_familia(client, "alfa", dni="42222222"))
    f = client.get(f"/api/familia/autorizaciones/{a['id']}/adjunto", headers=madre)
    assert f.status_code == 200 and f.content == PNG and f.headers["cache-control"] == "private, no-store"
    assert client.get(f"/api/familia/autorizaciones/{a['id']}/adjunto", headers=otra).status_code == 404
    assert client.get(f"/archivos/autorizaciones/{e.colegio.id}/x").status_code in (404, 405)
    assert client.delete(ruta, headers=h).json()["adjunto"] is None


# --- Permisos, módulo apagado y aislamiento ----------------------------------------------------------------

def test_permisos_ver_y_editar(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    a = crear(client, h)
    crear_personal(db, e.colegio, "20000000", {"autorizaciones": "ver"})
    crear_personal(db, e.colegio, "20000001", {"cuaderno": "editar"})
    hv = auth("alfa", token(client, "alfa", "20000000"))
    hn = auth("alfa", token(client, "alfa", "20000001"))
    assert client.get(f"/api/autorizaciones/{a['id']}", headers=hv).status_code == 200
    assert client.get(f"/api/autorizaciones/{a['id']}/lista.pdf", headers=hv).status_code == 200
    crear(client, hv, esperado=403)
    assert client.post(f"/api/autorizaciones/{a['id']}/recordar", headers=hv).status_code == 403
    assert client.get("/api/autorizaciones", headers=hn).status_code == 403


def test_modulo_apagado_403_y_sin_pestana(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    hf = fam("alfa", token_familia(client, "alfa"))
    a = crear(client, h)
    limite = hoy() + timedelta(days=5)
    e.colegio.modulos_apagados = ["autorizaciones"]
    db.commit()
    assert client.get("/api/autorizaciones", headers=h).status_code == 403
    assert client.get("/api/familia/autorizaciones", headers=hf).status_code == 403
    assert client.post(f"/api/familia/autorizaciones/{a['id']}/respuestas", headers=hf,
                       json={"alumno_id": e.a1.id, "autoriza": True}).status_code == 403
    assert client.get("/api/familia/yo", headers=hf).json()["modulos"]["autorizaciones"] is False
    assert "autorizaciones" not in client.get("/api/auth/yo", headers=h).json()["permisos"]
    assert autorizaciones.revisar_recordatorios(db, limite - timedelta(days=1)) == 0


def test_colegio_nuevo_sin_el_modulo_y_la_demo_con_el(client, db):
    from app import demo
    from tests.conftest import crear_colegio

    assert "autorizaciones" not in INCLUIDOS
    nuevo = crear_colegio(db, "nuevo")
    db.commit()
    assert not nuevo.modulo_activo("autorizaciones") and nuevo.avisos_tipos["autorizaciones"] is True
    demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=2)
    colegio = db.scalar(select(Colegio).where(Colegio.subdominio == "demo"))
    assert colegio.modulo_activo("autorizaciones")


def test_aislamiento_entre_colegios(client, db):
    a_ = preparar(db, "alfa")
    b_ = preparar(db, "beta")
    ha = auth("alfa", token(client, "alfa"))
    hb = auth("beta", token(client, "beta"))
    hfa = fam("alfa", token_familia(client, "alfa"))
    hfb = fam("beta", token_familia(client, "beta"))
    x = crear(client, ha, "De alfa", alcance="colegio")
    responder(client, hfa, x["id"], a_.a1.id, True)
    assert client.get("/api/autorizaciones", headers=hb).json() == []
    for ruta in ("", "/lista.pdf", "/lista.xlsx", "/adjunto"):
        assert client.get(f"/api/autorizaciones/{x['id']}{ruta}", headers=hb).status_code == 404
    for ruta, cuerpo in (("/publicar", None), ("/recordar", None), ("/cerrar", None), ("/anular", {"motivo": "x"})):
        assert client.post(f"/api/autorizaciones/{x['id']}{ruta}", headers=hb, json=cuerpo).status_code == 404
    assert client.put(f"/api/autorizaciones/{x['id']}", headers=hb, json={
        "titulo": "x", "fecha_limite": hoy().isoformat()}).status_code == 404
    # La familia de beta (mismo DNI, otra cuenta del colegio) no la ve ni responde con ids adivinados.
    assert client.get("/api/familia/autorizaciones", headers=hfb).json() == []
    responder(client, hfb, x["id"], a_.a1.id, True, esperado=404)
    responder(client, hfb, x["id"], b_.a1.id, True, esperado=404)
    assert client.get(f"/api/familia/autorizaciones/{x['id']}/adjunto", headers=hfb).status_code == 404
    # Destinos de otro colegio: no existen.
    crear(client, ha, alcance="secciones", secciones=[b_.s1.id], esperado=422)
    crear(client, ha, alcance="alumnos", alumnos=[b_.a1.id], esperado=422)
    crear(client, ha, alcance="niveles", niveles=[b_.primaria.id], esperado=422)
    # El token de otro colegio no sirve aquí.
    assert client.get("/api/autorizaciones", headers={**ha, "Host": "beta.tikray.test"}).status_code in (401, 403)
    # Los avisos de alfa no van a apoderados de beta.
    assert {c.colegio_id for c in cola(db)} == {a_.colegio.id}


def test_un_apoderado_solo_responde_por_sus_hijos_y_las_que_les_van(client, db):
    e = preparar(db, "alfa", otra=True)
    h = auth("alfa", token(client, "alfa"))
    madre = fam("alfa", token_familia(client, "alfa"))
    a = crear(client, h, alcance="secciones", secciones=[e.ss.id])  # solo a a3 (hijo de la otra madre)
    b = crear(client, h, "Para a1", alcance="alumnos", alumnos=[e.a1.id])
    assert [x["titulo"] for x in client.get("/api/familia/autorizaciones", headers=madre).json()] == ["Para a1"]
    responder(client, madre, a["id"], e.a3.id, True, esperado=404)  # no le va
    responder(client, madre, b["id"], e.a3.id, True, esperado=404)  # no es su hijo
    responder(client, madre, b["id"], e.a2.id, True, esperado=404)  # su hijo, pero no le va


# --- Migración ---------------------------------------------------------------------------------------

def test_migracion_sube_y_baja(client, db):
    from alembic import command
    from alembic.config import Config

    db.close()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    tablas = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    nuevas = {"autorizacion", "destino_autorizacion", "alumno_autorizacion", "respuesta_autorizacion"}
    try:
        command.downgrade(cfg, "e7a1c5d9f3b2")
        with get_engine().begin() as conn:
            assert not nuevas & set(conn.execute(text(tablas)).scalars())
            for i, (sub, demo) in enumerate((("alfa", False), ("demo", True)), 1):
                conn.execute(text(
                    "INSERT INTO colegio (id, nombre, subdominio, color_primario, color_secundario, estado, es_demo, "
                    f"creado_en) VALUES ({i}, 'C', '{sub}', '#111111', '#222222', 'activo', {demo}, now())"))
        command.upgrade(cfg, "head")
        with get_engine().begin() as conn:
            assert nuevas <= set(conn.execute(text(tablas)).scalars())
            filas = {s: (m, a) for s, m, a in conn.execute(text(
                "SELECT subdominio, modulos_contratados, avisos_tipos FROM colegio"))}
            assert "autorizaciones" not in filas["alfa"][0] and "autorizaciones" in filas["demo"][0]
            assert filas["alfa"][1]["autorizaciones"] is True
        command.downgrade(cfg, "e7a1c5d9f3b2")
        with get_engine().begin() as conn:
            assert not nuevas & set(conn.execute(text(tablas)).scalars())
            filas = {s: (m, a) for s, m, a in conn.execute(text(
                "SELECT subdominio, modulos_contratados, avisos_tipos FROM colegio"))}
            assert "autorizaciones" not in filas["demo"][0] and "autorizaciones" not in filas["demo"][1]
    finally:
        command.upgrade(cfg, "head")
        with get_engine().begin() as conn:
            conn.execute(text("TRUNCATE colegio RESTART IDENTITY CASCADE"))
        command.check(cfg)
