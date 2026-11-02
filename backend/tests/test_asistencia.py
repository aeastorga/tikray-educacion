"""Asistencia: marcación, deduplicación, tardanza, cola de avisos, faltas
automáticas, personal y licencias, reportes. Y aislamiento entre colegios en todo."""

import statistics
import time as reloj
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import asistencia
from app.codigos import contenido_qr
from app.fechas import LIMA, hoy_lima
from app.models import (Alumno, AnioEscolar, AsistenciaAlumno, AsistenciaPersonal, ColaAviso, Colegio,
                        DiaNoLectivo, Grado, Marcacion, Matricula, Nivel, Seccion, Turno, Usuario)
from tests.conftest import auth, crear_colegio, crear_personal, token

HOY = hoy_lima()
# Un lunes fijo del año en curso: las pruebas no dependen de la hora en que corren.
LUNES = date(HOY.year, 6, 1) + timedelta(days=(7 - date(HOY.year, 6, 1).weekday()) % 7)


@dataclass
class Escuela:
    colegio: Colegio
    turno: Turno
    seccion: Seccion
    alumnos: list[Alumno]


def preparar(db, sub: str, alumnos: int = 2, dias_semana: str = "12345") -> Escuela:
    """Año en curso activo, un turno 07:45 con 10 min de tolerancia, una sección y sus alumnos."""
    c = crear_colegio(db, sub)
    anio = AnioEscolar(colegio_id=c.id, anio=HOY.year, inicio=date(HOY.year, 1, 1), fin=date(HOY.year, 12, 31),
                       dias_semana=dias_semana, activo=True)
    nivel = Nivel(colegio_id=c.id, nombre="Primaria")
    db.add_all([anio, nivel])
    db.flush()
    grado = Grado(colegio_id=c.id, nivel_id=nivel.id, nombre="1°")
    turno = Turno(colegio_id=c.id, nombre="Mañana", hora_entrada=time(7, 45), tolerancia_minutos=10,
                  hora_salida=time(13, 0))
    db.add_all([grado, turno])
    db.flush()
    sec = Seccion(colegio_id=c.id, anio_id=anio.id, grado_id=grado.id, turno_id=turno.id, nombre="A")
    db.add(sec)
    db.flush()
    lista = []
    for i in range(alumnos):
        a = Alumno(colegio_id=c.id, numero_documento=f"7{i:07d}", nombres=f"Niño{i}", apellidos=f"Apellido{i:03d}",
                   codigo=f"{sub[:2].upper()}{i:06d}".replace("0", "A").replace("1", "B")[:8])
        db.add(a)
        db.flush()
        db.add(Matricula(colegio_id=c.id, anio_id=anio.id, alumno_id=a.id, seccion_id=sec.id))
        lista.append(a)
    db.commit()
    return Escuela(c, turno, sec, lista)


def en(dia: date, hh: int, mm: int) -> datetime:
    return datetime.combine(dia, time(hh, mm), LIMA)


def marcar(db, e: Escuela, momento: datetime, alumno: Alumno | None = None, codigo: str | None = None,
           id_cliente: str | None = None, ahora: datetime | None = None) -> dict:
    lectura = asistencia.Lectura(id_cliente=id_cliente or uuid.uuid4().hex, momento=momento, origen="qr",
                                 codigo=codigo or contenido_qr((alumno or e.alumnos[0]).codigo))
    r = asistencia.registrar(db, e.colegio.id, lectura, None, ahora=ahora or momento + timedelta(minutes=1))
    db.commit()
    return r


def dia_de(db, alumno: Alumno, fecha: date = LUNES) -> AsistenciaAlumno | None:
    return db.scalar(select(AsistenciaAlumno).where(AsistenciaAlumno.alumno_id == alumno.id,
                                                    AsistenciaAlumno.fecha == fecha))


def cola(db, alumno: Alumno) -> list[tuple[str, str | None]]:
    filas = db.scalars(select(ColaAviso).where(ColaAviso.alumno_id == alumno.id).order_by(ColaAviso.id))
    return [(f.tipo, f.datos.get("hora")) for f in filas]


# --- Marcación ------------------------------------------------------------------

def test_entrada_a_tiempo_y_aviso_en_cola(db):
    e = preparar(db, "alfa")
    r = marcar(db, e, en(LUNES, 7, 40))
    assert r["estado"] == "ok" and r["resultado"] == "entrada" and r["estado_dia"] == "presente"
    assert r["persona"]["nombre"] == "Apellido000, Niño0" and r["hora"] == "07:40"
    assert cola(db, e.alumnos[0]) == [("ingreso", "07:40")]


def test_tardanza_segun_tolerancia_del_turno(db):
    e = preparar(db, "alfa")
    assert marcar(db, e, en(LUNES, 7, 55), e.alumnos[0])["estado_dia"] == "presente"  # 10 min: dentro
    r = marcar(db, e, en(LUNES, 7, 56), e.alumnos[1])
    assert r["estado_dia"] == "tarde" and r["minutos_tarde"] == 11
    assert cola(db, e.alumnos[1]) == [("tarde", "07:56")]


def test_doble_marcacion_se_descarta(db):
    e = preparar(db, "alfa")
    marcar(db, e, en(LUNES, 7, 40))
    r = marcar(db, e, en(LUNES, 7, 45))
    assert r["resultado"] == "duplicada" and r["entrada"] == "07:40"
    assert cola(db, e.alumnos[0]) == [("ingreso", "07:40")]
    assert [m.resultado for m in db.scalars(select(Marcacion).order_by(Marcacion.id))] == ["entrada", "duplicada"]


def test_salida_y_su_aviso_con_la_ultima_hora(db):
    e = preparar(db, "alfa")
    marcar(db, e, en(LUNES, 7, 40))
    r = marcar(db, e, en(LUNES, 13, 5))
    assert r["resultado"] == "salida" and r["salida"] == "13:05"
    marcar(db, e, en(LUNES, 13, 30))
    assert cola(db, e.alumnos[0]) == [("ingreso", "07:40"), ("salida", "13:30")]
    assert dia_de(db, e.alumnos[0]).salida == en(LUNES, 13, 30)


def test_reenvio_con_mismo_id_no_duplica(db):
    e = preparar(db, "alfa")
    a = marcar(db, e, en(LUNES, 7, 40), id_cliente="porteria-1-0001")
    b = marcar(db, e, en(LUNES, 7, 40), id_cliente="porteria-1-0001")
    assert a == b
    assert len(db.scalars(select(Marcacion)).all()) == 1


def test_marcaciones_sin_internet_llegan_desordenadas(db):
    e = preparar(db, "alfa")
    tarde = en(LUNES, 18, 0)  # la portería sincroniza al final del día
    marcar(db, e, en(LUNES, 13, 0), ahora=tarde)
    marcar(db, e, en(LUNES, 7, 50), ahora=tarde)
    fila = dia_de(db, e.alumnos[0])
    assert (fila.entrada, fila.salida, fila.estado) == (en(LUNES, 7, 50), en(LUNES, 13, 0), "presente")
    assert cola(db, e.alumnos[0]) == []  # ya no es momento de avisar "ingresó a las 7:50"


def test_hora_adelantada_o_codigo_desconocido(db):
    e = preparar(db, "alfa")
    lectura = asistencia.Lectura("x" * 10, en(LUNES, 9, 0), "qr", codigo=contenido_qr(e.alumnos[0].codigo))
    assert asistencia.registrar(db, e.colegio.id, lectura, None, ahora=en(LUNES, 8, 0))["estado"] == "rechazada"
    assert marcar(db, e, en(LUNES, 7, 40), codigo="TK1:ZZZZZZZZ")["estado"] == "desconocido"
    assert marcar(db, e, en(LUNES, 7, 40), codigo="cualquier cosa")["estado"] == "desconocido"
    assert db.scalars(select(Marcacion)).all() == []


def test_carnet_de_otro_colegio_no_se_reconoce(db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    r = marcar(db, a, en(LUNES, 7, 40), codigo=contenido_qr(b.alumnos[0].codigo))
    assert r["estado"] == "desconocido"
    lectura = asistencia.Lectura("manual-0001", en(LUNES, 7, 40), "manual", alumno_id=b.alumnos[0].id)
    assert asistencia.registrar(db, a.colegio.id, lectura, None, ahora=en(LUNES, 8, 0))["estado"] == "desconocido"
    assert db.scalars(select(AsistenciaAlumno)).all() == []


def test_alumno_retirado_no_marca(db):
    e = preparar(db, "alfa")
    e.alumnos[0].activo = False
    db.commit()
    assert marcar(db, e, en(LUNES, 7, 40))["estado"] == "desconocido"


def test_base_rechaza_marcacion_cruzada_o_sin_persona(db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    db.add(Marcacion(colegio_id=a.colegio.id, id_cliente="cruzada-01", alumno_id=b.alumnos[0].id,
                     momento=en(LUNES, 7, 40), fecha=LUNES, origen="qr", resultado="entrada"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(Marcacion(colegio_id=a.colegio.id, id_cliente="nadie-0001", momento=en(LUNES, 7, 40), fecha=LUNES,
                     origen="qr", resultado="entrada"))
    with pytest.raises(IntegrityError):
        db.commit()


# --- Faltas automáticas ----------------------------------------------------------

def test_faltas_despues_del_corte_y_llegada_tardia(db):
    e = preparar(db, "alfa")
    marcar(db, e, en(LUNES, 7, 40), e.alumnos[0])
    assert asistencia.marcar_faltas(db, LUNES, time(9, 0)) == 0  # corte: 07:45 + 90 min = 09:15
    assert asistencia.marcar_faltas(db, LUNES, time(9, 15)) == 1
    db.commit()
    assert dia_de(db, e.alumnos[0]).estado == "presente"
    assert dia_de(db, e.alumnos[1]).estado == "falta"
    assert cola(db, e.alumnos[1]) == [("falta", None)]
    assert asistencia.marcar_faltas(db, LUNES, time(10, 0)) == 0  # repetir no duplica
    db.commit()
    assert len(cola(db, e.alumnos[1])) == 1
    # Llega a las 10: queda tarde y el aviso de falta pendiente se retira.
    r = marcar(db, e, en(LUNES, 10, 0), e.alumnos[1])
    assert r["estado_dia"] == "tarde" and cola(db, e.alumnos[1]) == [("tarde", "10:00")]


def test_sin_faltas_en_dias_no_lectivos(db):
    e = preparar(db, "alfa")
    sabado = LUNES + timedelta(days=5)
    assert asistencia.marcar_faltas(db, sabado) == 0
    anio = db.scalar(select(AnioEscolar))
    db.add(DiaNoLectivo(colegio_id=e.colegio.id, anio_id=anio.id, fecha=LUNES, motivo="Feriado"))
    db.commit()
    assert asistencia.marcar_faltas(db, LUNES) == 0
    assert asistencia.marcar_faltas(db, LUNES + timedelta(days=1)) == 2
    assert asistencia.marcar_faltas(db, date(HOY.year + 1, 3, 2)) == 0  # fuera del año escolar


def test_faltas_por_colegio_con_su_calendario_y_su_corte(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    anio_b = db.scalar(select(AnioEscolar).where(AnioEscolar.colegio_id == b.colegio.id))
    db.add(DiaNoLectivo(colegio_id=b.colegio.id, anio_id=anio_b.id, fecha=LUNES, motivo="Aniversario"))
    db.commit()
    h = auth("alfa", token(client, "alfa"))
    assert client.put("/api/asistencia/configuracion", headers=h,
                      json={"minutos_duplicado": 5, "minutos_corte_falta": 30}).status_code == 200
    assert asistencia.marcar_faltas(db, LUNES, time(8, 20)) == 2  # alfa: corte 08:15; beta: feriado
    db.commit()
    assert {f.colegio_id for f in db.scalars(select(AsistenciaAlumno))} == {a.colegio.id}
    hb = auth("beta", token(client, "beta"))
    assert client.get("/api/asistencia/configuracion", headers=hb).json()["minutos_corte_falta"] == 90
    # Solo un colegio
    assert asistencia.marcar_faltas(db, LUNES + timedelta(days=1), colegio_id=b.colegio.id) == 2
    assert {f.colegio_id for f in db.scalars(select(AsistenciaAlumno).where(
        AsistenciaAlumno.fecha == LUNES + timedelta(days=1)))} == {b.colegio.id}


def test_colegio_suspendido_no_recibe_faltas(db):
    e = preparar(db, "alfa")
    e.colegio.estado = "suspendido"
    db.commit()
    assert asistencia.marcar_faltas(db, LUNES) == 0


def test_corte_no_pasa_de_medianoche():
    t = Turno(hora_entrada=time(22, 0))
    assert asistencia.corte(t, 300) == time(23, 59)


# --- Rutas: receptor, portería, permisos ---------------------------------------------

def _marca(codigo: str | None = None, **extra) -> dict:
    return {"id_cliente": uuid.uuid4().hex, **({"codigo": codigo} if codigo else {}), **extra}


def test_receptor_por_lote(client, db):
    e = preparar(db, "alfa", alumnos=3)
    h = auth("alfa", token(client, "alfa"))
    lote = [_marca(contenido_qr(e.alumnos[0].codigo)), _marca("TK1:ZZZZZZZZ"),
            _marca(alumno_id=e.alumnos[1].id)]
    r = client.post("/api/asistencia/marcaciones", headers=h, json={"marcaciones": lote})
    assert r.status_code == 200
    estados = [x["estado"] for x in r.json()["resultados"]]
    assert estados == ["ok", "desconocido", "ok"]
    manual = db.scalar(select(Marcacion).where(Marcacion.alumno_id == e.alumnos[1].id))
    assert manual.origen == "manual" and manual.registrado_por_id is not None
    # Un reenvío del mismo lote (la portería no recibió la respuesta) no cambia nada.
    client.post("/api/asistencia/marcaciones", headers=h, json={"marcaciones": lote})
    assert len(db.scalars(select(Marcacion)).all()) == 2


def test_receptor_valida_el_lote(client, db):
    preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    url = "/api/asistencia/marcaciones"
    assert client.post(url, headers=h, json={"marcaciones": []}).status_code == 422
    assert client.post(url, headers=h, json={"marcaciones": [_marca("TK1:AAAAAAAA", alumno_id=1)]}).status_code == 422
    assert client.post(url, headers=h, json={"marcaciones": [{"id_cliente": "corto", "codigo": "x"}]}).status_code == 422
    muchos = [_marca("TK1:AAAAAAAA") for _ in range(501)]
    assert client.post(url, headers=h, json={"marcaciones": muchos}).status_code == 422


def test_receptor_ignora_alumno_de_otro_colegio(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    h = auth("alfa", token(client, "alfa"))
    r = client.post("/api/asistencia/marcaciones", headers=h, json={"marcaciones": [
        _marca(alumno_id=b.alumnos[0].id), _marca(contenido_qr(b.alumnos[0].codigo))]})
    assert [x["estado"] for x in r.json()["resultados"]] == ["desconocido", "desconocido"]
    assert db.scalars(select(Marcacion)).all() == []


def test_marcacion_responde_en_menos_de_300_ms(client, db):
    e = preparar(db, "alfa", alumnos=25)
    h = auth("alfa", token(client, "alfa"))
    url = "/api/asistencia/marcaciones"
    client.post(url, headers=h, json={"marcaciones": [_marca(contenido_qr(e.alumnos[0].codigo))]})  # calentar
    tiempos = []
    for a in e.alumnos[1:]:
        inicio = reloj.perf_counter()
        r = client.post(url, headers=h, json={"marcaciones": [_marca(contenido_qr(a.codigo))]})
        tiempos.append(reloj.perf_counter() - inicio)
        assert r.json()["resultados"][0]["estado"] == "ok"
    assert statistics.median(tiempos) < 0.3 and max(tiempos) < 0.6, tiempos
    assert len(db.scalars(select(ColaAviso)).all()) == 25  # cada una dejó su aviso en la cola


def test_permisos_de_porteria_y_reportes(client, db):
    e = preparar(db, "alfa")
    crear_personal(db, e.colegio, "20000000", {"asistencia": "editar"})
    crear_personal(db, e.colegio, "20000001", {"asistencia": "ver"})
    portero = auth("alfa", token(client, "alfa", "20000000"))
    docente = auth("alfa", token(client, "alfa", "20000001"))
    lote = {"marcaciones": [_marca(contenido_qr(e.alumnos[0].codigo))]}
    assert client.post("/api/asistencia/marcaciones", headers=portero, json=lote).status_code == 200
    assert client.get("/api/asistencia/porteria", headers=portero).status_code == 200
    assert client.post("/api/asistencia/marcaciones", headers=docente, json=lote).status_code == 403
    assert client.get("/api/asistencia/porteria", headers=docente).status_code == 403
    assert client.get("/api/asistencia/dia", headers=docente).status_code == 200
    assert client.put("/api/asistencia/configuracion", headers=portero,
                      json={"minutos_duplicado": 5, "minutos_corte_falta": 60}).status_code == 403
    assert client.post("/api/asistencia/licencias", headers=portero, json={
        "usuario_id": 1, "tipo": "salud", "desde": "2026-01-01", "hasta": "2026-01-01"}).status_code == 403


def test_padron_de_porteria_sin_dni_y_solo_del_colegio(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    h = auth("alfa", token(client, "alfa"))
    p = client.get("/api/asistencia/porteria", headers=h).json()
    assert {x["codigo"] for x in p["alumnos"]} == {x.codigo for x in a.alumnos}
    assert p["alumnos"][0]["seccion"] == "1° A" and p["alumnos"][0]["turno_id"] == a.turno.id
    assert "numero_documento" not in str(p) and "41234567" not in str(p)
    assert len(p["personal"]) == 1 and p["turnos"][0]["hora_entrada"] == "07:45"
    assert p["minutos_duplicado"] == 10


# --- Personal ----------------------------------------------------------------------

def test_personal_con_turno_marca_con_su_carnet(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    yo = client.get("/api/personal", headers=h).json()[0]
    r = client.put(f"/api/personal/{yo['id']}", headers=h, json={
        "nombres": yo["nombres"], "apellidos": yo["apellidos"], "rol_id": yo["rol_id"], "turno_id": e.turno.id})
    assert r.status_code == 200 and r.json()["turno_id"] == e.turno.id
    lectura = asistencia.Lectura("personal-01", en(LUNES, 8, 0), "qr", codigo=contenido_qr(yo["codigo"], True))
    r = asistencia.registrar(db, e.colegio.id, lectura, None, ahora=en(LUNES, 8, 1))
    db.commit()
    assert r["persona"]["tipo"] == "personal" and r["estado_dia"] == "tarde" and r["minutos_tarde"] == 15
    assert db.scalars(select(ColaAviso)).all() == []  # el personal no genera avisos a familias
    pdf = client.get("/api/personal/carnets", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_editar_personal_de_otro_colegio_o_con_turno_ajeno(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    h = auth("alfa", token(client, "alfa"))
    otro = db.scalar(select(Usuario).where(Usuario.colegio_id == b.colegio.id))
    yo = client.get("/api/personal", headers=h).json()[0]
    datos = {"nombres": "X", "apellidos": "Y", "rol_id": yo["rol_id"]}
    assert client.put(f"/api/personal/{otro.id}", headers=h, json=datos).status_code == 404
    assert client.post(f"/api/personal/{otro.id}/nuevo-codigo", headers=h).status_code == 404
    assert client.get(f"/api/personal/carnets?usuario_id={otro.id}", headers=h).status_code == 404
    assert client.put(f"/api/personal/{yo['id']}", headers=h,
                      json={**datos, "turno_id": b.turno.id}).status_code == 422
    assert client.put(f"/api/personal/{yo['id']}", headers=h, json={**datos, "activo": False}).status_code == 409


def test_licencia_antes_y_despues_de_la_falta(client, db):
    e = preparar(db, "alfa")
    docente = crear_personal(db, e.colegio, "20000000", {})
    docente.turno_id = e.turno.id
    db.commit()
    h = auth("alfa", token(client, "alfa"))
    martes = LUNES + timedelta(days=1)
    # Falta automática el lunes; la licencia se registra después y la corrige.
    asistencia.marcar_faltas(db, LUNES)
    db.commit()
    estado = lambda d: db.scalar(select(AsistenciaPersonal.estado).where(  # noqa: E731
        AsistenciaPersonal.usuario_id == docente.id, AsistenciaPersonal.fecha == d))
    assert estado(LUNES) == "falta"
    r = client.post("/api/asistencia/licencias", headers=h, json={
        "usuario_id": docente.id, "tipo": "salud", "desde": LUNES.isoformat(), "hasta": martes.isoformat(),
        "motivo": "Descanso médico"})
    assert r.status_code == 201
    db.expire_all()
    assert estado(LUNES) == "licencia"
    asistencia.marcar_faltas(db, martes)  # con licencia vigente queda "licencia", no falta
    db.commit()
    assert estado(martes) == "licencia"
    assert client.post("/api/asistencia/licencias", headers=h, json={
        "usuario_id": docente.id, "tipo": "personal", "desde": martes.isoformat(),
        "hasta": martes.isoformat()}).status_code == 409
    dia = client.get(f"/api/asistencia/personal/dia?fecha={martes}", headers=h).json()
    fila = next(p for p in dia["personal"] if p["usuario_id"] == docente.id)
    assert fila["estado"] == "licencia" and fila["licencia"] == "salud"
    assert client.delete(f"/api/asistencia/licencias/{r.json()['id']}", headers=h).status_code == 204
    db.expire_all()
    assert estado(LUNES) == "falta" and estado(martes) == "falta"


def test_licencias_aisladas_entre_colegios(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    otro = db.scalar(select(Usuario).where(Usuario.colegio_id == b.colegio.id))
    hb = auth("beta", token(client, "beta"))
    lic = client.post("/api/asistencia/licencias", headers=hb, json={
        "usuario_id": otro.id, "tipo": "vacaciones", "desde": LUNES.isoformat(), "hasta": LUNES.isoformat()}).json()
    h = auth("alfa", token(client, "alfa"))
    assert client.get("/api/asistencia/licencias", headers=h).json() == []
    assert client.delete(f"/api/asistencia/licencias/{lic['id']}", headers=h).status_code == 404
    assert client.post("/api/asistencia/licencias", headers=h, json={
        "usuario_id": otro.id, "tipo": "salud", "desde": LUNES.isoformat(),
        "hasta": LUNES.isoformat()}).status_code == 404
    assert client.post("/api/asistencia/licencias", headers=h, json={
        "usuario_id": 1, "tipo": "salud", "desde": "2026-05-02", "hasta": "2026-05-01"}).status_code == 422


# --- Reportes --------------------------------------------------------------------

def test_reporte_del_dia_y_del_mes(client, db):
    e = preparar(db, "alfa", alumnos=3)
    marcar(db, e, en(LUNES, 7, 40), e.alumnos[0])
    marcar(db, e, en(LUNES, 8, 5), e.alumnos[1])
    asistencia.marcar_faltas(db, LUNES)
    db.commit()
    h = auth("alfa", token(client, "alfa"))
    r = client.get(f"/api/asistencia/dia?fecha={LUNES}", headers=h).json()
    assert r["lectivo"] is True
    assert r["totales"] == {"total": 3, "presente": 1, "tarde": 1, "falta": 1, "sin_registro": 0}
    detalle = client.get(f"/api/asistencia/dia?fecha={LUNES}&seccion_id={e.seccion.id}", headers=h).json()
    assert [(x["estado"], x["entrada"]) for x in detalle["alumnos"]] == [
        ("presente", "07:40"), ("tarde", "08:05"), ("falta", None)]
    x = client.get(f"/api/asistencia/mensual.xlsx?anio={LUNES.year}&mes={LUNES.month}", headers=h)
    assert x.status_code == 200
    ws = load_workbook(BytesIO(x.content)).active
    columna = [c.value for c in ws[2]].index(LUNES.day) + 1
    assert [ws.cell(fila, columna).value for fila in (3, 4, 5)] == ["P", "T", "F"]
    assert [c.value for c in ws[2]][-3:] == ["Asistió", "Tardanzas", "Faltas"]
    assert client.get("/api/asistencia/mensual.xlsx?anio=2026&mes=13", headers=h).status_code == 422
    xp = client.get(f"/api/asistencia/personal/mensual.xlsx?anio={LUNES.year}&mes={LUNES.month}", headers=h)
    assert xp.status_code == 200 and load_workbook(BytesIO(xp.content)).active.title == "Personal"
    marcas = client.get(f"/api/asistencia/marcaciones?fecha={LUNES}", headers=h).json()
    assert [m["hora"] for m in marcas] == ["08:05", "07:40"]


def test_reportes_aislados_entre_colegios(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    marcar(db, b, en(LUNES, 7, 40), b.alumnos[0])
    h = auth("alfa", token(client, "alfa"))
    r = client.get(f"/api/asistencia/dia?fecha={LUNES}", headers=h).json()
    assert r["totales"]["total"] == 2 and r["totales"]["presente"] == 0
    assert client.get(f"/api/asistencia/dia?fecha={LUNES}&seccion_id={b.seccion.id}", headers=h).status_code == 404
    assert client.get(f"/api/asistencia/marcaciones?fecha={LUNES}", headers=h).json() == []
    assert client.get(f"/api/asistencia/mensual.xlsx?anio={LUNES.year}&mes={LUNES.month}"
                      f"&seccion_id={b.seccion.id}", headers=h).status_code == 404
    personal = client.get(f"/api/asistencia/personal/dia?fecha={LUNES}", headers=h).json()["personal"]
    assert [p["nombre"] for p in personal] == ["alfa, Dir"]


def test_hora_en_utc_se_muestra_en_lima():
    assert asistencia.hora(datetime(2026, 6, 1, 12, 40, tzinfo=UTC)) == "07:40"
