"""Recojo seguro: autorizados permanentes y del día, verificación en la portería (con y sin internet), quién lo
recogió en la app de la familia y en los reportes (el aviso de salida no cambia), módulo apagado y aislamiento
entre colegios y entre familias."""

import os
import statistics
import time as reloj
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select, text

from app import asistencia, avisos, recojo
from app.codigos import contenido_qr
from app.db import get_engine
from app.fechas import LIMA, hoy_lima
from app.models import (Alumno, AutorizacionRecojoDia, AutorizadoRecojo, ColaAviso, Colegio, Matricula, Recojo,
                        RegistroActividad)
from app.models.colegio import INCLUIDOS
from tests.conftest import auth, crear_colegio, crear_familia, crear_personal, token, token_familia
from tests.test_familias import Push, suscribir
from tests.test_pensiones import preparar as preparar_pensiones

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
PERSONA = {"nombres": "Carlos", "apellidos": "Ruiz Soto", "tipo_documento": "DNI", "numero_documento": "45678901",
           "parentesco": "Tío"}


def preparar(db, sub: str, dni_madre: str = "41234567"):
    """Tres alumnos (1° y 2° de primaria y 1° de secundaria), con recojo seguro contratado. La madre (con cuenta)
    es apoderada de los dos primeros; el padre (sin cuenta), del primero."""
    e = preparar_pensiones(db, sub, dni_madre)
    for a, letra in zip((e.a1, e.a2, e.a3), "ABC"):
        a.codigo = f"{sub[:2].upper()}RQSTU{letra}"  # un código de carnet válido, para marcar con QR
    db.commit()
    return e


def marca(alumno: Alumno, momento: datetime, id_cliente: str | None = None) -> dict:
    return {"id_cliente": id_cliente or uuid.uuid4().hex, "codigo": contenido_qr(alumno.codigo),
            "momento": momento.isoformat()}


def marcar(client, h, *marcas) -> list[dict]:
    r = client.post("/api/asistencia/marcaciones", headers=h, json={"marcaciones": list(marcas)})
    assert r.status_code == 200, r.text
    return r.json()["resultados"]


def salida(client, h, alumno: Alumno, ahora: datetime | None = None) -> dict:
    """Entrada hace 20 min y salida ahora (en línea). Devuelve la respuesta de la salida."""
    ahora = ahora or datetime.now(UTC)
    marcar(client, h, marca(alumno, ahora - timedelta(minutes=20)))
    r = marcar(client, h, marca(alumno, ahora))[0]
    assert r["resultado"] == "salida", r
    return r


def recoger(client, h, marcacion: str, tipo: str, **extra) -> dict:
    r = client.post("/api/recojo/registros", headers=h, json={"recojos": [{"marcacion": marcacion, "tipo": tipo,
                                                                            **extra}]})
    assert r.status_code == 200, r.text
    return r.json()["resultados"][0]


def aviso_salida(db, alumno: Alumno) -> ColaAviso:
    db.expire_all()
    return db.scalar(select(ColaAviso).where(ColaAviso.alumno_id == alumno.id, ColaAviso.tipo == "salida"))


def enviar(db) -> list[str]:
    push = Push()
    avisos.procesar_cola(db, push, ahora=datetime.now(UTC) + timedelta(seconds=5))
    return [m["cuerpo"] for _, m in push.enviados if " salió " in m["cuerpo"]]


# --- Portería: quién lo recogió y el aviso -------------------------------------------------------------

def test_salida_con_apoderado_aviso_al_instante_y_la_familia_lo_ve(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    hf = suscribir(client, "alfa")
    ahora = datetime.now(UTC)
    r = salida(client, h, e.a1, ahora)
    # La portería ve a los apoderados (sin estar en la lista), con el documento enmascarado.
    personas = r["recojo"]["personas"]
    assert {(p["tipo"], p["nombre"], p["parentesco"], p["documento"]) for p in personas} == {
        ("apoderado", "Rosa Mamani", "Madre", "••••4567"), ("apoderado", "Juan Quispe", "Padre", "••••3333")}
    # El aviso de salida sale al instante, como siempre (marcar quién lo recoge es opcional).
    assert aviso_salida(db, e.a1).procesar_desde <= datetime.now(UTC)
    assert enviar(db) == [f"Niño0 salió del colegio a las {asistencia.hora(ahora)}."]

    assert recoger(client, h, r["id_cliente"], "apoderado", persona_id=e.madre.id) == {
        "marcacion": r["id_cliente"], "estado": "ok", "fuera_de_lista": False}
    rec = db.scalar(select(Recojo))
    assert (rec.nombre, rec.numero_documento, rec.parentesco, rec.registrado_por_id) == (
        "Rosa Mamani", "41234567", "Madre", 1)
    # No se manda un segundo aviso: queda en la app de la familia.
    assert enviar(db) == []
    assert aviso_salida(db, e.a1).datos.get("recojo") is None
    hijo = next(x for x in client.get("/api/familia/hijos", headers=hf).json()["hijos"] if x["alumno_id"] == e.a1.id)
    assert hijo["recogido_por"] == {"nombre": "Rosa Mamani", "parentesco": "Madre", "fuera_de_lista": False}
    mes = client.get(f"/api/familia/hijos/{e.a1.id}/asistencia", headers=hf).json()
    assert mes["dias"][0]["recogido_por"]["nombre"] == "Rosa Mamani"
    assert "41234567" not in str(hijo) + str(mes)  # sin el documento

    # Reportes: la salida muestra quién lo recogió.
    d = client.get(f"/api/asistencia/dia?seccion_id={e.s1.id}", headers=h).json()
    assert d["recojo"] is True
    assert d["alumnos"][0]["recojo"]["nombre"] == "Rosa Mamani" and not d["alumnos"][0]["recojo"]["fuera_de_lista"]
    lista = client.get("/api/asistencia/recojos", headers=h).json()["recojos"]
    assert [(x["alumno"], x["seccion"], x["registrado_por"], x["recojo"]["nombre"]) for x in lista] == [
        ("Ape0, Niño0", "Primaria · 1° A", "Dir alfa", "Rosa Mamani")]


def test_fuera_de_lista_no_bloquea_la_salida(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    hf = auth("alfa", token_familia(client, "alfa"))
    r = salida(client, h, e.a1)
    res = recoger(client, h, r["id_cliente"], "otro", nombres="Pedro", apellidos="Gómez Luna",
                  numero_documento="40404040")
    assert res["estado"] == "ok" and res["fuera_de_lista"] is True
    hijo = next(x for x in client.get("/api/familia/hijos", headers=hf).json()["hijos"] if x["alumno_id"] == e.a1.id)
    assert hijo["recogido_por"] == {"nombre": "Pedro Gómez Luna", "parentesco": None, "fuera_de_lista": True}
    # Filtro de los recogidos por alguien fuera de la lista y su línea en el historial.
    assert [x["alumno"] for x in client.get("/api/asistencia/recojos?fuera_de_lista=true", headers=h)
            .json()["recojos"]] == ["Ape0, Niño0"]
    assert db.scalar(select(RegistroActividad.resumen).where(RegistroActividad.modulo == "recojo")) == \
        "Salida de Ape0, Niño0 con Pedro Gómez Luna (DNI): fuera de la lista"
    # El reenvío (la portería no recibió la respuesta) no deja otra línea.
    recoger(client, h, r["id_cliente"], "otro", nombres="Pedro", apellidos="Gómez Luna", numero_documento="40404040")
    assert len(db.scalars(select(RegistroActividad).where(RegistroActividad.modulo == "recojo")).all()) == 1
    # "Otro" exige nombre y documento válidos.
    r2 = client.post("/api/recojo/registros", headers=h, json={"recojos": [
        {"marcacion": r["id_cliente"], "tipo": "otro", "nombres": "Pedro", "apellidos": "Gómez"}]})
    assert r2.status_code == 422


def test_autorizado_permanente_y_desactivado(client, db):
    e = preparar(db, "alfa")
    crear_personal(db, e.colegio, "20000000", {"recojo": "editar", "padron": "ver"})
    sec = auth("alfa", token(client, "alfa", "20000000"))
    h = auth("alfa", token(client, "alfa"))
    x = client.post(f"/api/recojo/alumnos/{e.a1.id}/autorizados", headers=sec, json=PERSONA)
    assert x.status_code == 201, x.text
    x = x.json()
    assert x["origen"] == "colegio" and x["activo"]
    # Está en el padrón de la portería (con el documento enmascarado).
    p = client.get("/api/asistencia/porteria", headers=h).json()
    assert {"tipo": "autorizado", "id": x["id"], "nombre": "Carlos Ruiz Soto", "parentesco": "Tío",
            "tipo_documento": "DNI", "documento": "••••8901", "foto": False} in p["recojo"][str(e.a1.id)]["personas"]
    assert "45678901" not in str(p)
    ahora = datetime.now(UTC)
    r = salida(client, h, e.a1, ahora)
    assert recoger(client, h, r["id_cliente"], "autorizado", persona_id=x["id"])["fuera_de_lista"] is False
    assert db.scalar(select(Recojo)).nombre == "Carlos Ruiz Soto"

    # Desactivado: ya no aparece; si igual se lo registra (padrón viejo sin internet), queda fuera de la lista.
    assert client.put(f"/api/recojo/autorizados/{x['id']}", headers=sec, json={**PERSONA, "activo": False}
                      ).status_code == 200
    ficha = client.get(f"/api/recojo/alumnos/{e.a1.id}", headers=sec).json()
    assert [(a["id"], a["activo"]) for a in ficha["autorizados"]] == [(x["id"], False)]
    otra = marcar(client, h, marca(e.a1, ahora + timedelta(minutes=1)))[0]
    assert otra["resultado"] == "duplicada" or otra["resultado"] == "salida"
    assert x["id"] not in [p["id"] for p in client.get("/api/asistencia/porteria", headers=h).json()["recojo"]
                           .get(str(e.a1.id), {"personas": []})["personas"] if p["tipo"] == "autorizado"]
    assert recoger(client, h, r["id_cliente"], "autorizado", persona_id=x["id"])["fuera_de_lista"] is True
    # Una corrección reemplaza al anterior: un solo recojo por salida.
    assert len(db.scalars(select(Recojo)).all()) == 1
    # Nada se borra: no hay DELETE.
    assert client.delete(f"/api/recojo/autorizados/{x['id']}", headers=sec).status_code == 405


def test_maximo_cinco_autorizados_activos(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    hf = auth("alfa", token_familia(client, "alfa"))
    ids = []
    for i in range(5):
        cliente, cab = (client, hf) if i % 2 else (client, h)
        ruta = (f"/api/familia/recojo/hijos/{e.a1.id}/autorizados" if i % 2
                else f"/api/recojo/alumnos/{e.a1.id}/autorizados")
        r = cliente.post(ruta, headers=cab, json={**PERSONA, "numero_documento": f"4567890{i}"})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    r = client.post(f"/api/recojo/alumnos/{e.a1.id}/autorizados", headers=h,
                    json={**PERSONA, "numero_documento": "45678909"})
    assert r.status_code == 409 and "Máximo 5" in r.json()["detail"]
    assert client.post(f"/api/familia/recojo/hijos/{e.a1.id}/autorizados", headers=hf,
                       json={**PERSONA, "numero_documento": "45678909"}).status_code == 409
    # La misma persona dos veces, tampoco.
    assert client.put(f"/api/recojo/autorizados/{ids[0]}", headers=h,
                      json={**PERSONA, "numero_documento": "45678901"}).status_code == 409
    # Al desactivar uno se libera el cupo; reactivarlo con la lista llena da 409.
    assert client.put(f"/api/familia/recojo/autorizados/{ids[1]}", headers=hf,
                      json={**PERSONA, "numero_documento": "45678901", "activo": False}).status_code == 200
    assert client.post(f"/api/recojo/alumnos/{e.a1.id}/autorizados", headers=h,
                       json={**PERSONA, "numero_documento": "45678909"}).status_code == 201
    assert client.put(f"/api/recojo/autorizados/{ids[1]}", headers=h,
                      json={**PERSONA, "numero_documento": "45678901", "activo": True}).status_code == 409
    # Lo que agrega el apoderado entra activo de inmediato y queda en el historial con su nombre.
    familia = db.scalars(select(AutorizadoRecojo).where(AutorizadoRecojo.origen == "familia")).all()
    assert len(familia) == 2 and familia[0].creado_por_apoderado_id == e.madre.id
    assert db.scalar(select(RegistroActividad.quien).where(RegistroActividad.objeto_id == familia[0].id)) == \
        "Rosa Mamani (apoderado)"


def test_no_hay_salio_solo(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    r = salida(client, h, e.a1)
    assert client.post("/api/recojo/registros", headers=h, json={"recojos": [
        {"marcacion": r["id_cliente"], "tipo": "solo"}]}).status_code == 422
    assert "sale_solo" not in str(r["recojo"])


def test_autorizacion_del_dia_vale_solo_esa_fecha_en_lima(client, db):
    e = preparar(db, "alfa")
    hf = auth("alfa", token_familia(client, "alfa"))
    h = auth("alfa", token(client, "alfa"))
    hoy = hoy_lima()
    ruta = f"/api/familia/recojo/hijos/{e.a1.id}/del-dia"
    assert client.post(ruta, headers=hf, json={**PERSONA, "fecha": (hoy - timedelta(days=1)).isoformat()}
                       ).status_code == 422
    assert client.post(ruta, headers=hf, json={**PERSONA, "fecha": (hoy + timedelta(days=31)).isoformat()}
                       ).status_code == 422
    manana = client.post(ruta, headers=hf, json={**PERSONA, "numero_documento": "45000000",
                                                 "fecha": (hoy + timedelta(days=1)).isoformat()}).json()
    hoy_x = client.post(ruta, headers=hf, json={**PERSONA, "fecha": hoy.isoformat()})
    assert hoy_x.status_code == 201
    # La portería de hoy ve solo la de hoy.
    personas = client.get("/api/asistencia/porteria", headers=h).json()["recojo"][str(e.a1.id)]["personas"]
    assert [p["id"] for p in personas if p["tipo"] == "del_dia"] == [hoy_x.json()["id"]]
    assert manana["id"] not in [p["id"] for p in personas if p["tipo"] == "del_dia"]
    # Anulada, ya no vale.
    assert client.post(f"/api/familia/recojo/del-dia/{hoy_x.json()['id']}/anular", headers=hf).status_code == 204
    assert not [p for p in client.get("/api/asistencia/porteria", headers=h).json()["recojo"][str(e.a1.id)]["personas"]
                if p["tipo"] == "del_dia"]

    # La fecha es la de Lima: una salida a las 11:30 p. m. de Lima (ya otro día en UTC) sigue siendo ese día.
    lunes = date(hoy.year, 6, 1) + timedelta(days=(7 - date(hoy.year, 6, 1).weekday()) % 7)
    x = AutorizacionRecojoDia(colegio_id=e.colegio.id, alumno_id=e.a2.id, apoderado_id=e.madre.id, fecha=lunes,
                              nombres="Ana", apellidos="Paz", numero_documento="46000000", parentesco="Vecina")
    db.add(x)
    db.commit()
    assert [p["id"] for p in recojo.quienes_pueden(db, e.colegio.id, lunes, [e.a2.id])[e.a2.id]["personas"]
            if p["tipo"] == "del_dia"] == [x.id]
    assert recojo.quienes_pueden(db, e.colegio.id, lunes + timedelta(days=1), [e.a2.id]).get(
        e.a2.id, {"personas": []})["personas"] == [p for p in recojo.quienes_pueden(
            db, e.colegio.id, lunes + timedelta(days=1), [e.a2.id]).get(e.a2.id, {"personas": []})["personas"]
            if p["tipo"] != "del_dia"]

    def salir(dia: date, hh: int, mm: int) -> str:
        momento = datetime.combine(dia, time(hh, mm), LIMA)
        for m in (momento - timedelta(hours=2), momento):
            lectura = asistencia.Lectura(id_cliente=uuid.uuid4().hex, momento=m, origen="qr",
                                         codigo=contenido_qr(e.a2.codigo))
            res = asistencia.registrar(db, e.colegio.id, lectura, None, ahora=m + timedelta(minutes=1))
            db.commit()
        assert res["resultado"] == "salida"
        return lectura.id_cliente

    tarde = salir(lunes, 23, 30)
    assert datetime.combine(lunes, time(23, 30), LIMA).astimezone(UTC).date() == lunes + timedelta(days=1)
    assert recojo.registrar(db, e.colegio.id, recojo.DatosRecojo(tarde, "del_dia", x.id), None)["fuera_de_lista"] \
        is False
    db.commit()
    otro_dia = salir(lunes + timedelta(days=1), 13, 0)
    assert recojo.registrar(db, e.colegio.id, recojo.DatosRecojo(otro_dia, "del_dia", x.id), None)[
        "fuera_de_lista"] is True


def test_porteria_sin_internet_conserva_quien_lo_recogio(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    ahora = datetime.now(UTC)
    entrada, sal = marca(e.a1, ahora - timedelta(minutes=50)), marca(e.a1, ahora - timedelta(minutes=30))
    # El recojo llega antes que su salida (falló el envío de la marcación): espera y se reintenta.
    assert recoger(client, h, sal["id_cliente"], "apoderado", persona_id=e.padre.id)["estado"] == "esperando"
    assert db.scalars(select(Recojo)).all() == []
    assert [x["resultado"] for x in marcar(client, h, entrada, sal)] == ["entrada", "salida"]
    for _ in range(2):  # el reenvío no duplica
        assert recoger(client, h, sal["id_cliente"], "apoderado", persona_id=e.padre.id)["estado"] == "ok"
    rec = db.scalar(select(Recojo))
    assert len(db.scalars(select(Recojo)).all()) == 1
    assert rec.momento == datetime.fromisoformat(sal["momento"]) and rec.nombre == "Juan Quispe"
    assert rec.parentesco == "Padre" and rec.fecha == datetime.fromisoformat(sal["momento"]).astimezone(LIMA).date()
    d = client.get(f"/api/asistencia/dia?seccion_id={e.s1.id}&fecha={rec.fecha}", headers=h).json()
    assert d["alumnos"][0]["recojo"]["nombre"] == "Juan Quispe"
    # Una marcación desconocida (otro colegio o rechazada) nunca crea un recojo.
    assert recoger(client, h, "no-existe-123", "apoderado", persona_id=e.padre.id)["estado"] == "esperando"


def test_marcacion_responde_en_menos_de_300_ms_con_recojo(client, db):
    e = preparar(db, "alfa")
    # 25 alumnos con dos autorizados cada uno.
    sec = e.s1
    alumnos = []
    for i in range(25):
        a = Alumno(colegio_id=e.colegio.id, numero_documento=f"6{i:07d}", nombres=f"Al{i}", apellidos=f"Ap{i}",
                   codigo=f"RQ{i:02d}ABCD"[:8].replace("0", "A").replace("1", "B"))
        db.add(a)
        db.flush()
        db.add(Matricula(colegio_id=e.colegio.id, anio_id=e.anio.id, alumno_id=a.id, seccion_id=sec.id))
        for j in range(2):
            db.add(AutorizadoRecojo(colegio_id=e.colegio.id, alumno_id=a.id, nombres="N", apellidos=f"A{j}",
                                    numero_documento=f"5{i:03d}{j:04d}", parentesco="Tía", origen="colegio"))
        alumnos.append(a)
    db.commit()
    h = auth("alfa", token(client, "alfa"))
    ahora = datetime.now(UTC)
    marcar(client, h, *[marca(a, ahora - timedelta(minutes=20)) for a in alumnos])
    url = "/api/asistencia/marcaciones"
    tiempos = []
    for a in alumnos:
        inicio = reloj.perf_counter()
        r = client.post(url, headers=h, json={"marcaciones": [marca(a, ahora)]})
        tiempos.append(reloj.perf_counter() - inicio)
        assert len(r.json()["resultados"][0]["recojo"]["personas"]) == 2
    assert statistics.median(tiempos) < 0.3 and max(tiempos) < 0.6, tiempos


# --- Módulo apagado -------------------------------------------------------------------------------------

def test_modulo_apagado_403_y_porteria_como_siempre(client, db):
    e = preparar(db, "alfa")
    e.colegio.modulos_contratados = [*INCLUIDOS]  # sin recojo
    db.commit()
    h = auth("alfa", token(client, "alfa"))
    hf = auth("alfa", token_familia(client, "alfa"))
    suscribir(client, "alfa")
    assert client.get(f"/api/recojo/alumnos/{e.a1.id}", headers=h).status_code == 403
    assert client.post(f"/api/recojo/alumnos/{e.a1.id}/autorizados", headers=h, json=PERSONA).status_code == 403
    assert client.get("/api/familia/recojo", headers=hf).status_code == 403
    assert client.post(f"/api/familia/recojo/hijos/{e.a1.id}/autorizados", headers=hf, json=PERSONA
                       ).status_code == 403
    assert client.get("/api/asistencia/recojos", headers=h).status_code == 403
    assert client.get("/api/familia/yo", headers=hf).json()["modulos"]["recojo"] is False
    # La portería marca la salida como hoy: sin lista, sin espera del aviso.
    assert client.get("/api/asistencia/porteria", headers=h).json()["recojo"] is None
    ahora = datetime.now(UTC)
    r = salida(client, h, e.a1, ahora)
    assert "recojo" not in r
    r2 = client.post("/api/recojo/registros", headers=h, json={"recojos": [
        {"marcacion": r["id_cliente"], "tipo": "apoderado", "persona_id": e.madre.id}]})
    assert r2.status_code == 403
    assert aviso_salida(db, e.a1).procesar_desde <= datetime.now(UTC)
    assert enviar(db)[0].startswith("Niño0 salió del colegio a las")
    d = client.get(f"/api/asistencia/dia?seccion_id={e.s1.id}", headers=h).json()
    assert d["recojo"] is False and "recojo" not in d["alumnos"][0]
    assert all(x["recogido_por"] is None for x in client.get("/api/familia/hijos", headers=hf).json()["hijos"])
    # Apagado por el administrador (aunque esté contratado): igual.
    e.colegio.modulos_contratados = [*INCLUIDOS, "recojo"]
    e.colegio.modulos_apagados = ["recojo"]
    db.commit()
    assert client.get(f"/api/recojo/alumnos/{e.a1.id}", headers=h).status_code == 403


def test_permisos_de_secretaria_y_porteria(client, db):
    e = preparar(db, "alfa")
    crear_personal(db, e.colegio, "20000000", {"recojo": "editar"})
    crear_personal(db, e.colegio, "20000001", {"asistencia": "editar"})
    crear_personal(db, e.colegio, "20000002", {"recojo": "ver"})
    sec = auth("alfa", token(client, "alfa", "20000000"))
    portero = auth("alfa", token(client, "alfa", "20000001"))
    lector = auth("alfa", token(client, "alfa", "20000002"))
    x = client.post(f"/api/recojo/alumnos/{e.a1.id}/autorizados", headers=sec, json=PERSONA).json()
    assert client.put(f"/api/recojo/autorizados/{x['id']}/foto", headers=sec,
                      files={"archivo": ("f.png", PNG, "image/png")}).json()["foto"] is True
    assert client.put(f"/api/recojo/autorizados/{x['id']}/foto", headers=sec,
                      files={"archivo": ("f.pdf", b"%PDF-1.4", "application/pdf")}).status_code == 422
    # La portería ve la foto y registra el recojo, pero no edita la lista.
    foto = client.get(f"/api/recojo/autorizados/{x['id']}/foto", headers=portero)
    assert foto.status_code == 200 and foto.content == PNG and foto.headers["content-type"] == "image/png"
    assert client.post(f"/api/recojo/alumnos/{e.a1.id}/autorizados", headers=portero, json=PERSONA).status_code == 403
    r = salida(client, portero, e.a1)
    assert recoger(client, portero, r["id_cliente"], "autorizado", persona_id=x["id"])["estado"] == "ok"
    assert db.scalar(select(Recojo)).registrado_por_id != 1
    # Quien solo ve la lista no la cambia ni registra recojos.
    assert client.get(f"/api/recojo/alumnos/{e.a1.id}", headers=lector).status_code == 200
    assert client.put(f"/api/recojo/autorizados/{x['id']}", headers=lector, json=PERSONA).status_code == 403
    assert client.post("/api/recojo/registros", headers=sec, json={"recojos": [
        {"marcacion": r["id_cliente"], "tipo": "apoderado", "persona_id": e.madre.id}]}).status_code == 403


# --- Aislamiento ----------------------------------------------------------------------------------------

def test_aislamiento_entre_colegios(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta", dni_madre="45555555")
    ha, hb = auth("alfa", token(client, "alfa")), auth("beta", token(client, "beta"))
    hfb = auth("beta", token_familia(client, "beta", "45555555"))
    xb = client.post(f"/api/recojo/alumnos/{b.a1.id}/autorizados", headers=hb, json=PERSONA).json()
    client.put(f"/api/recojo/autorizados/{xb['id']}/foto", headers=hb, files={"archivo": ("f.png", PNG, "image/png")})
    db_b = client.post(f"/api/familia/recojo/hijos/{b.a1.id}/del-dia", headers=hfb,
                       json={**PERSONA, "fecha": hoy_lima().isoformat()}).json()
    rb = salida(client, hb, b.a1)
    assert recoger(client, hb, rb["id_cliente"], "autorizado", persona_id=xb["id"])["estado"] == "ok"

    # Con ids adivinados, A no ve ni toca nada de B: 404 como si no existiera.
    assert client.get(f"/api/recojo/alumnos/{b.a1.id}", headers=ha).status_code == 404
    assert client.post(f"/api/recojo/alumnos/{b.a1.id}/autorizados", headers=ha, json=PERSONA).status_code == 404
    assert client.put(f"/api/recojo/autorizados/{xb['id']}", headers=ha, json=PERSONA).status_code == 404
    assert client.put(f"/api/recojo/autorizados/{xb['id']}/foto", headers=ha,
                      files={"archivo": ("f.png", PNG, "image/png")}).status_code == 404
    assert client.get(f"/api/recojo/autorizados/{xb['id']}/foto", headers=ha).status_code == 404
    # Ni el recojo de una salida de B, ni una persona de B en una salida de A.
    assert recoger(client, ha, rb["id_cliente"], "apoderado", persona_id=a.madre.id)["estado"] == "esperando"
    ra = salida(client, ha, a.a1)
    assert recoger(client, ha, ra["id_cliente"], "autorizado", persona_id=xb["id"])["estado"] == "rechazada"
    assert recoger(client, ha, ra["id_cliente"], "del_dia", persona_id=db_b["id"])["estado"] == "rechazada"
    assert recoger(client, ha, ra["id_cliente"], "apoderado", persona_id=b.madre.id)["estado"] == "rechazada"
    assert db.scalar(select(Recojo).where(Recojo.colegio_id == a.colegio.id)) is None
    # Listados y padrón: solo lo propio.
    assert client.get("/api/asistencia/recojos", headers=ha).json()["recojos"] == []
    padron = client.get("/api/asistencia/porteria", headers=ha).json()
    assert str(b.a1.id) not in padron["recojo"] or b.a1.id in (a.a1.id, a.a2.id, a.a3.id)
    assert "Carlos Ruiz Soto" not in str(padron)
    # La familia de A no llega a lo de B.
    hfa = auth("alfa", token_familia(client, "alfa"))
    assert client.put(f"/api/familia/recojo/autorizados/{xb['id']}", headers=hfa, json=PERSONA).status_code == 404
    assert client.get(f"/api/familia/recojo/autorizados/{xb['id']}/foto", headers=hfa).status_code == 404
    assert client.post(f"/api/familia/recojo/del-dia/{db_b['id']}/anular", headers=hfa).status_code == 404
    assert client.post(f"/api/familia/recojo/hijos/{b.a1.id}/del-dia", headers=hfa,
                       json={**PERSONA, "fecha": hoy_lima().isoformat()}).status_code == 404
    db.expire_all()
    assert db.get(AutorizadoRecojo, xb["id"]).activo and db.get(AutorizacionRecojoDia, db_b["id"]).anulada_en is None


def test_apoderado_solo_ve_y_edita_lo_de_sus_hijos(client, db):
    e = preparar(db, "alfa")
    crear_familia(db, e.colegio, "42222222", [e.a3])
    h = auth("alfa", token(client, "alfa"))
    hf = auth("alfa", token_familia(client, "alfa"))  # madre de a1 y a2
    hf3 = auth("alfa", token_familia(client, "alfa", "42222222"))  # apoderado de a3
    x3 = client.post(f"/api/recojo/alumnos/{e.a3.id}/autorizados", headers=h, json=PERSONA).json()
    d3 = client.post(f"/api/familia/recojo/hijos/{e.a3.id}/del-dia", headers=hf3,
                     json={**PERSONA, "fecha": hoy_lima().isoformat()}).json()
    client.put(f"/api/recojo/autorizados/{x3['id']}/foto", headers=h, files={"archivo": ("f.png", PNG, "image/png")})
    lista = client.get("/api/familia/recojo", headers=hf).json()
    assert [x["id"] for x in lista["hijos"]] == [e.a1.id, e.a2.id]
    assert "Carlos" not in str(lista)
    assert client.post(f"/api/familia/recojo/hijos/{e.a3.id}/autorizados", headers=hf, json=PERSONA).status_code == 404
    assert client.put(f"/api/familia/recojo/autorizados/{x3['id']}", headers=hf,
                      json={**PERSONA, "activo": False}).status_code == 404
    assert client.put(f"/api/familia/recojo/autorizados/{x3['id']}/foto", headers=hf,
                      files={"archivo": ("f.png", PNG, "image/png")}).status_code == 404
    assert client.get(f"/api/familia/recojo/autorizados/{x3['id']}/foto", headers=hf).status_code == 404
    assert client.post(f"/api/familia/recojo/del-dia/{d3['id']}/anular", headers=hf).status_code == 404
    # El apoderado de a3 sí: ve lo que puso el colegio y lo puede editar.
    mio = client.get("/api/familia/recojo", headers=hf3).json()["hijos"][0]
    assert [x["id"] for x in mio["autorizados"]] == [x3["id"]] and [x["id"] for x in mio["del_dia"]] == [d3["id"]]
    assert client.get(f"/api/familia/recojo/autorizados/{x3['id']}/foto", headers=hf3).content == PNG
    assert client.put(f"/api/familia/recojo/autorizados/{x3['id']}", headers=hf3,
                      json={**PERSONA, "parentesco": "Abuelo"}).json()["parentesco"] == "Abuelo"
    # Con el acceso pendiente aún no puede.
    pendiente = crear_familia(db, e.colegio, "43000000", [e.a1], estado="pendiente")
    hp = auth("alfa", token_familia(client, "alfa", "43000000"))
    assert pendiente.id and client.get("/api/familia/recojo", headers=hp).status_code == 403


# --- Migración ---------------------------------------------------------------------------------------

def test_migracion_sube_y_baja(client, db):
    from alembic import command
    from alembic.config import Config

    db.close()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    tablas = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    try:
        command.downgrade(cfg, "4b7e2a9c1d30")
        with get_engine().begin() as conn:
            assert not {"autorizado_recojo", "autorizacion_recojo_dia", "recojo"} & set(conn.execute(text(tablas))
                                                                                         .scalars())
            for i, (sub, demo) in enumerate((("alfa", False), ("demo", True)), 1):
                conn.execute(text(
                    "INSERT INTO colegio (id, nombre, subdominio, color_primario, color_secundario, estado, es_demo, "
                    f"creado_en) VALUES ({i}, 'C', '{sub}', '#111111', '#222222', 'activo', {demo}, now())"))
        command.upgrade(cfg, "head")
        with get_engine().begin() as conn:
            assert {"autorizado_recojo", "autorizacion_recojo_dia", "recojo"} <= set(conn.execute(text(tablas))
                                                                                     .scalars())
            contratados = dict(conn.execute(text("SELECT subdominio, modulos_contratados FROM colegio")).all())
            assert "recojo" not in contratados["alfa"] and "recojo" in contratados["demo"]
        command.downgrade(cfg, "4b7e2a9c1d30")
        with get_engine().begin() as conn:
            assert not {"autorizado_recojo", "recojo"} & set(conn.execute(text(tablas)).scalars())
            contratados = dict(conn.execute(text("SELECT subdominio, modulos_contratados FROM colegio")).all())
            assert "recojo" not in contratados["demo"]
    finally:
        command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def _sin_colegios_sueltos(db):
    yield
    db.rollback()
    assert Colegio  # noqa: B018 (la limpieza la hace conftest)


def test_correccion_llave_colegio_e_indices_sube_y_baja(client, db):
    """La corrección (e7a1c5d9f3b2) deja la llave hacia `colegio` en RESTRICT con índice de `colegio_id` en las tres
    tablas de recojo, y al bajar vuelve a como estaba. Después de subir, `alembic check` no ve diferencias."""
    from alembic import command
    from alembic.config import Config

    db.close()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    tablas = ("autorizado_recojo", "autorizacion_recojo_dia", "recojo")

    def estado() -> tuple[dict[str, str], set[str]]:
        with get_engine().begin() as conn:
            llaves = dict(conn.execute(text(
                "SELECT conrelid::regclass::text, confdeltype FROM pg_constraint "
                "WHERE conname = 'fk_' || conrelid::regclass::text || '_colegio_id_colegio' "
                "AND conrelid::regclass::text = ANY(:t)"), {"t": list(tablas)}).all())
            indices = set(conn.execute(text(
                "SELECT tablename FROM pg_indexes WHERE indexname = 'ix_' || tablename || '_colegio_id' "
                "AND tablename = ANY(:t)"), {"t": list(tablas)}).scalars())
        return llaves, indices

    try:
        command.downgrade(cfg, "d4e9f2a5b8c1")  # la migración anterior (calendario)
        assert estado() == ({t: "c" for t in tablas}, set())
        command.upgrade(cfg, "head")
        assert estado() == ({t: "r" for t in tablas}, set(tablas))
        command.check(cfg)  # falla si el modelo y la base no coinciden
    finally:
        command.upgrade(cfg, "head")
