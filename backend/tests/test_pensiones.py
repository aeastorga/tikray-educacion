"""Pensiones y caja: conceptos, montos, cronograma, cuotas, descuentos, mora, cobros con recibo sin saltos,
anulaciones, cierre de caja, gastos, reportes, la familia (responsable de pago) y los avisos de cobro.
El aislamiento entre colegios de todo esto está en test_aislamiento.py."""

import json
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app import avisos, pensiones
from app.db import get_engine
from app.fechas import LIMA, hoy_lima
from app.main import app
from app.models import (Alumno, AlumnoApoderado, AnioEscolar, Apoderado, ColaAviso, Colegio, ConfigPensiones,
                        CuotaAlumno, CuotaProgramada, Gasto, Grado, Matricula, Nivel, Pago, PagoDetalle,
                        RegistroActividad, Seccion, SuscripcionPush, Turno)
from app.models.colegio import CONTRATABLES
from app.routers.pensiones import desde_vencimiento
from tests.conftest import auth, crear_colegio, crear_familia, crear_personal, token, token_familia

HOY = hoy_lima()
D = Decimal
PDF = b"%PDF-1.4\n%prueba\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


@dataclass
class Escuela:
    colegio: Colegio
    anio: AnioEscolar
    primaria: Nivel
    secundaria: Nivel
    g1: Grado  # 1° primaria
    g2: Grado  # 2° primaria
    gs: Grado  # 1° secundaria
    s1: Seccion
    s2: Seccion
    ss: Seccion
    a1: Alumno  # 1° primaria, hijo de la madre (y del padre)
    a2: Alumno  # 2° primaria, hijo de la madre
    a3: Alumno  # 1° secundaria
    madre: Apoderado
    padre: Apoderado


def preparar(db, sub: str, dni_madre: str = "41234567") -> Escuela:
    c = crear_colegio(db, sub, modulos_contratados=list(CONTRATABLES))  # pensiones y caja se contratan aparte
    # Año escolar que rodea a hoy, para tener cuotas vencidas y por vencer.
    anio = AnioEscolar(colegio_id=c.id, anio=HOY.year, inicio=HOY - timedelta(days=200),
                       fin=HOY + timedelta(days=200), dias_semana="1234567", activo=True)
    prim, secu = Nivel(colegio_id=c.id, nombre="Primaria", orden=1), Nivel(colegio_id=c.id, nombre="Secundaria", orden=2)
    turno = Turno(colegio_id=c.id, nombre="Mañana", hora_entrada=time(0, 5), tolerancia_minutos=0,
                  hora_salida=time(23, 0))
    db.add_all([anio, prim, secu, turno])
    db.flush()
    g1 = Grado(colegio_id=c.id, nivel_id=prim.id, nombre="1°", orden=1)
    g2 = Grado(colegio_id=c.id, nivel_id=prim.id, nombre="2°", orden=2)
    gs = Grado(colegio_id=c.id, nivel_id=secu.id, nombre="1°", orden=1)
    db.add_all([g1, g2, gs])
    db.flush()
    secs = [Seccion(colegio_id=c.id, anio_id=anio.id, grado_id=g.id, turno_id=turno.id, nombre="A") for g in (g1, g2, gs)]
    db.add_all(secs)
    db.flush()
    alumnos = []
    for i, sec in enumerate(secs):
        a = Alumno(colegio_id=c.id, numero_documento=f"7{i:07d}", nombres=f"Niño{i}", apellidos=f"Ape{i}",
                   codigo=f"{sub[:2].upper()}PEN{i}")
        db.add(a)
        db.flush()
        db.add(Matricula(colegio_id=c.id, anio_id=anio.id, alumno_id=a.id, seccion_id=sec.id))
        alumnos.append(a)
    db.commit()
    madre = crear_familia(db, c, dni_madre, alumnos[:2])
    padre = Apoderado(colegio_id=c.id, numero_documento="43333333", nombres="Juan", apellidos="Quispe")
    db.add(padre)
    db.flush()
    db.add(AlumnoApoderado(colegio_id=c.id, alumno_id=alumnos[0].id, apoderado_id=padre.id, parentesco="Padre"))
    db.commit()
    return Escuela(c, anio, prim, secu, g1, g2, gs, *secs, *alumnos, madre, padre)


@pytest.fixture
def e(db):
    return preparar(db, "alfa")


@pytest.fixture
def h(client, e):
    return auth("alfa", token(client, "alfa"))


def concepto(client, h, nombre="Pensión", tipo="pension", **extra) -> dict:
    r = client.post("/api/pensiones/conceptos", headers=h, json={"nombre": nombre, "tipo": tipo, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def montos(client, h, concepto_id: int, lista: list[dict]) -> dict:
    r = client.put(f"/api/pensiones/conceptos/{concepto_id}/montos", headers=h, json={"montos": lista})
    assert r.status_code == 200, r.text
    return r.json()


def linea(client, h, concepto_id: int, numero: int, vence: date, mes: str = "Mes") -> dict:
    r = client.post(f"/api/pensiones/conceptos/{concepto_id}/cronograma", headers=h,
                    json={"numero": numero, "mes": mes, "vence": vence.isoformat()})
    assert r.status_code == 201, r.text
    return r.json()


def armar(client, h, e, monto="350.50", vences=(-40, -10, 3, 30)) -> dict:
    """Pensión con monto por nivel (primaria y secundaria) y cuatro cuotas alrededor de hoy; genera."""
    c = concepto(client, h)
    montos(client, h, c["id"], [{"nivel_id": e.primaria.id, "monto": monto},
                                {"nivel_id": e.secundaria.id, "monto": "420.00"}])
    for i, dias in enumerate(vences, 1):
        c = linea(client, h, c["id"], i, HOY + timedelta(days=dias), f"Cuota {i}")
    r = client.post("/api/pensiones/generar", headers=h)
    assert r.status_code == 200, r.text
    return c


def cuotas(client, h, alumno_id: int) -> list[dict]:
    r = client.get(f"/api/pensiones/alumnos/{alumno_id}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["cuotas"]


def abrir(client, h):
    r = client.post("/api/caja/abrir", headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def cobrar(client, h, alumno_id: int, detalles: list[tuple[int, str]], medio="efectivo", operacion=None):
    return client.post("/api/caja/pagos", headers=h, json={
        "alumno_id": alumno_id, "medio": medio, "numero_operacion": operacion,
        "detalles": [{"cuota_id": c, "monto": m} for c, m in detalles]})


# --- Configuración -------------------------------------------------------------------------------

def test_conceptos_unicos_por_anio_e_igv_por_defecto(client, e, h):
    assert concepto(client, h, "Matrícula", "matricula")["igv"] == "inafecto"
    assert concepto(client, h, "Pensión")["igv"] == "inafecto"
    assert concepto(client, h, "Uniforme", "otro")["igv"] == "gravado"
    assert concepto(client, h, "Taller", "otro", igv="inafecto")["igv"] == "inafecto"
    r = client.post("/api/pensiones/conceptos", headers=h, json={"nombre": " pensión ".replace("p", "P"), "tipo": "pension"})
    assert r.status_code == 409


def test_montos_no_repiten_grado_y_el_grado_manda_sobre_el_nivel(client, db, e, h):
    c = concepto(client, h)
    r = client.put(f"/api/pensiones/conceptos/{c['id']}/montos", headers=h, json={"montos": [
        {"grado_id": e.g1.id, "monto": "300"}, {"grado_id": e.g1.id, "monto": "310"}]})
    assert r.status_code == 422
    r = client.put(f"/api/pensiones/conceptos/{c['id']}/montos", headers=h, json={"montos": [
        {"grado_id": e.g1.id, "nivel_id": e.primaria.id, "monto": "300"}]})
    assert r.status_code == 422
    montos(client, h, c["id"], [{"nivel_id": e.primaria.id, "monto": "350.00"}, {"grado_id": e.g2.id, "monto": "380.25"}])
    linea(client, h, c["id"], 1, HOY + timedelta(days=5))
    client.post("/api/pensiones/generar", headers=h)
    assert cuotas(client, h, e.a1.id)[0]["monto"] == "350.00"  # 1°: el del nivel
    assert cuotas(client, h, e.a2.id)[0]["monto"] == "380.25"  # 2°: el del grado manda
    assert cuotas(client, h, e.a3.id) == []  # secundaria sin monto: no se le crea
    # En la base tampoco entran dos montos para el mismo grado.
    from app.models import MontoConcepto
    db.add(MontoConcepto(colegio_id=e.colegio.id, concepto_id=c["id"], grado_id=e.g2.id, monto=D("1")))
    with pytest.raises(IntegrityError):
        db.commit()


def test_vencimiento_dentro_del_anio_escolar_y_serie(client, e, h):
    c = concepto(client, h)
    r = client.post(f"/api/pensiones/conceptos/{c['id']}/cronograma", headers=h,
                    json={"numero": 1, "mes": "X", "vence": (e.anio.fin + timedelta(days=1)).isoformat()})
    assert r.status_code == 422
    # Serie de meses del año calendario del año escolar: vence el día pedido o el último del mes.
    meses = [m for m in range(1, 13) if date(HOY.year, m, 1) >= e.anio.inicio and date(HOY.year, m, 28) <= e.anio.fin]
    desde, hasta = meses[0], meses[2]
    r = client.post(f"/api/pensiones/conceptos/{c['id']}/cronograma/serie", headers=h,
                    json={"desde": desde, "hasta": hasta, "dia": 31})
    assert r.status_code == 201, r.text
    lineas = r.json()["cronograma"]
    assert [x["numero"] for x in lineas] == list(range(1, hasta - desde + 2))
    assert all(date.fromisoformat(x["vence"]).day >= 28 for x in lineas)


def test_mora_configurable_con_tope_y_aviso_legal(client, e, h):
    r = client.get("/api/pensiones/config", headers=h).json()
    assert r["mora_tipo"] == "ninguna" and r["dias_aviso_previo"] == 3 and "asesor legal" in r["aviso_mora"]
    assert client.put("/api/pensiones/config", headers=h, json={"mora_tipo": "porcentaje", "mora_valor": "101"}
                      ).status_code == 422
    assert client.put("/api/pensiones/config", headers=h, json={"mora_tipo": "fijo", "mora_valor": "0"}
                      ).status_code == 422
    r = client.put("/api/pensiones/config", headers=h,
                   json={"mora_tipo": "porcentaje", "mora_valor": "1.5", "mora_tope": "20", "dias_aviso_previo": 5})
    assert r.status_code == 200 and r.json()["mora_tope"] == "20.00"


def test_calculo_de_mora_sin_interes_sobre_interes():
    cfg = ConfigPensiones(mora_tipo="porcentaje", mora_valor=D("2"), mora_tope=None)
    vence = date(2026, 3, 31)
    assert pensiones.mora_del_dia(cfg, D("300"), D("0"), vence, vence) == D("0.00")
    assert pensiones.mora_del_dia(cfg, D("300"), D("0"), vence, vence + timedelta(days=1)) == D("6.00")
    assert pensiones.mora_del_dia(cfg, D("300"), D("50"), vence, vence + timedelta(days=61)) == D("15.00")  # 3 meses
    cfg.mora_tope = D("10")
    assert pensiones.mora_del_dia(cfg, D("300"), D("0"), vence, vence + timedelta(days=200)) == D("10.00")
    cfg.mora_tipo, cfg.mora_valor = "fijo", D("5.50")
    assert pensiones.mora_del_dia(cfg, D("300"), D("0"), vence, vence + timedelta(days=200)) == D("5.50")
    cfg.mora_tipo = "ninguna"
    assert pensiones.mora_del_dia(cfg, D("300"), D("0"), vence, vence + timedelta(days=200)) == D("0.00")


# --- Cuotas ---------------------------------------------------------------------------------------

def test_generar_dos_veces_no_duplica_y_solo_crea_las_que_faltan(client, db, e, h):
    armar(client, h, e)
    total = db.scalar(select(func.count()).select_from(CuotaAlumno))
    assert total == 12  # 3 alumnos x 4 cuotas
    r = client.post("/api/pensiones/generar", headers=h).json()
    assert r["creadas"] == 0
    assert db.scalar(select(func.count()).select_from(CuotaAlumno)) == 12


def test_alumno_nuevo_matriculado_recibe_sus_cuotas_solas(client, db, e, h):
    armar(client, h, e)
    r = client.post("/api/padron/alumnos", headers=h, json={
        "numero_documento": "71234500", "nombres": "Nuevo", "apellidos": "Alumno", "seccion_id": e.s1.id})
    assert r.status_code == 201, r.text
    nuevas = cuotas(client, h, r.json()["id"])
    assert len(nuevas) == 4 and {c["monto"] for c in nuevas} == {"350.50"}


def test_cambio_de_grado_recalcula_solo_las_cuotas_sin_pagos(client, db, e, h):
    c = armar(client, h, e)
    montos(client, h, c["id"], [{"nivel_id": e.primaria.id, "monto": "350.50"},
                                {"nivel_id": e.secundaria.id, "monto": "420.00"}])
    primera = cuotas(client, h, e.a1.id)[0]
    abrir(client, h)
    assert cobrar(client, h, e.a1.id, [(primera["id"], "100.00")]).status_code == 201
    r = client.put(f"/api/padron/alumnos/{e.a1.id}", headers=h, json={
        "numero_documento": e.a1.numero_documento, "nombres": e.a1.nombres, "apellidos": e.a1.apellidos,
        "seccion_id": e.ss.id})
    assert r.status_code == 200, r.text
    despues = cuotas(client, h, e.a1.id)
    assert despues[0]["monto"] == "350.50"  # con pago: no cambia
    assert {x["monto"] for x in despues[1:]} == {"420.00"}


def test_estados_y_saldo(client, db, e, h):
    armar(client, h, e)
    c = cuotas(client, h, e.a1.id)
    assert [x["estado"] for x in c] == ["vencida", "vencida", "pendiente", "pendiente"]
    assert c[0]["dias_atraso"] == 40 and c[2]["dias_atraso"] == 0
    abrir(client, h)
    cobrar(client, h, e.a1.id, [(c[0]["id"], "350.50"), (c[2]["id"], "0.50")])
    c = cuotas(client, h, e.a1.id)
    assert (c[0]["estado"], c[0]["saldo"]) == ("pagada", "0.00")
    assert (c[2]["estado"], c[2]["saldo"]) == ("parcial", "350.00")


def test_saldo_nunca_negativo_en_la_base(client, db, e, h):
    armar(client, h, e)
    cuota = db.scalar(select(CuotaAlumno).where(CuotaAlumno.alumno_id == e.a1.id).limit(1))
    cuota.pagado = cuota.monto + D("0.01")
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    cuota = db.scalar(select(CuotaAlumno).where(CuotaAlumno.alumno_id == e.a1.id).limit(1))
    cuota.descuento = cuota.monto + 1
    with pytest.raises(IntegrityError):
        db.commit()


def test_retiro_anula_solo_las_cuotas_futuras(client, db, e, h):
    armar(client, h, e)
    r = client.put(f"/api/padron/alumnos/{e.a1.id}", headers=h, json={
        "numero_documento": e.a1.numero_documento, "nombres": e.a1.nombres, "apellidos": e.a1.apellidos,
        "activo": False})
    assert r.status_code == 200, r.text
    c = cuotas(client, h, e.a1.id)
    assert [x["estado"] for x in c] == ["vencida", "vencida", "anulada", "anulada"]
    assert c[2]["anulada_motivo"] == "Retiro"
    assert db.scalar(select(func.count()).select_from(CuotaAlumno).where(CuotaAlumno.alumno_id == e.a1.id)) == 4
    # Generar otra vez no le crea cuotas a un retirado.
    assert client.post("/api/pensiones/generar", headers=h).json()["creadas"] == 0


# --- Descuentos -----------------------------------------------------------------------------------

def test_descuento_se_aplica_a_cuotas_sin_pagos_con_tope_100(client, db, e, h):
    c = armar(client, h, e, monto="300.00")
    primera = cuotas(client, h, e.a1.id)[0]
    abrir(client, h)
    cobrar(client, h, e.a1.id, [(primera["id"], "10.00")])
    assert client.post("/api/pensiones/descuentos", headers=h, json={
        "alumno_id": e.a1.id, "tipo": "porcentaje", "valor": "50", "motivo": ""}).status_code == 422  # sin motivo
    r = client.post("/api/pensiones/descuentos", headers=h, json={
        "alumno_id": e.a1.id, "concepto_id": c["id"], "tipo": "porcentaje", "valor": "50", "motivo": "Hermanos"})
    assert r.status_code == 201 and r.json()["cuotas_actualizadas"] == 3
    r = client.post("/api/pensiones/descuentos", headers=h, json={
        "alumno_id": e.a1.id, "tipo": "porcentaje", "valor": "51", "motivo": "Beca"})
    assert r.status_code == 422  # pasaría de 100 %
    r = client.post("/api/pensiones/descuentos", headers=h, json={
        "alumno_id": e.a1.id, "tipo": "monto", "valor": "400", "motivo": "Beca total"})
    assert r.status_code == 201
    lista = cuotas(client, h, e.a1.id)
    assert lista[0]["descuento"] == "0.00"  # tenía pago
    assert {(x["descuento"], x["saldo"]) for x in lista[1:]} == {("300.00", "0.00")}  # tope: el monto
    # Anular el descuento de monto: vuelve el 50 %.
    did = r.json()["id"]
    r = client.post(f"/api/pensiones/descuentos/{did}/anular", headers=h, json={"motivo": "Error"})
    assert r.status_code == 200 and r.json()["anulado"]
    assert {x["saldo"] for x in cuotas(client, h, e.a1.id)[1:]} == {"150.00"}
    quien = db.scalar(select(RegistroActividad.resumen).where(RegistroActividad.que == "descuento")
                      .order_by(RegistroActividad.id))
    assert "Descuento 50 %" in quien


# --- Caja: cobros ---------------------------------------------------------------------------------

def test_sin_caja_abierta_no_se_cobra_y_no_hay_dos(client, e, h):
    armar(client, h, e)
    c = cuotas(client, h, e.a1.id)
    assert cobrar(client, h, e.a1.id, [(c[0]["id"], "10")]).status_code == 409
    abrir(client, h)
    assert client.post("/api/caja/abrir", headers=h).status_code == 409


def test_caja_de_otro_dia_obliga_a_cerrarla(client, db, e, h):
    armar(client, h, e)
    caja = abrir(client, h)
    from app.models import CajaSesion
    db.get(CajaSesion, caja["id"]).fecha = HOY - timedelta(days=1)
    db.commit()
    c = cuotas(client, h, e.a1.id)
    r = cobrar(client, h, e.a1.id, [(c[0]["id"], "10")])
    assert r.status_code == 409 and "ciérrala" in r.json()["detail"]


def test_montos_con_decimales_parcial_y_varias_cuotas(client, db, e, h):
    armar(client, h, e, monto="333.33")
    c = cuotas(client, h, e.a1.id)
    abrir(client, h)
    # 0.10 + 0.20 en float da 0.30000000000000004: aquí no.
    r = cobrar(client, h, e.a1.id, [(c[0]["id"], "0.10"), (c[1]["id"], "0.20")])
    assert r.status_code == 201 and r.json()["total"] == "0.30"
    r = cobrar(client, h, e.a1.id, [(c[0]["id"], "333.23"), (c[1]["id"], "100.01"), (c[2]["id"], "333.33")],
               medio="yape", operacion="op-123")
    assert r.status_code == 201, r.text
    assert r.json()["total"] == "766.57" and r.json()["numero_operacion"] == "OP-123"
    c = cuotas(client, h, e.a1.id)
    assert [(x["pagado"], x["saldo"], x["estado"]) for x in c[:3]] == [
        ("333.33", "0.00", "pagada"), ("100.21", "233.12", "vencida"), ("333.33", "0.00", "pagada")]
    assert db.scalar(select(func.sum(Pago.total))) == D("766.87")
    assert db.scalar(select(func.sum(PagoDetalle.monto))) == D("766.87")


def test_sobrepago_rechazado_sin_saldo_a_favor(client, db, e, h):
    armar(client, h, e, monto="100.00")
    c = cuotas(client, h, e.a1.id)
    abrir(client, h)
    r = cobrar(client, h, e.a1.id, [(c[0]["id"], "100.01")])
    assert r.status_code == 422 and "supera el saldo" in r.json()["detail"]
    assert cobrar(client, h, e.a1.id, [(c[0]["id"], "60")]).status_code == 201
    assert cobrar(client, h, e.a1.id, [(c[0]["id"], "40.01")]).status_code == 422
    assert cobrar(client, h, e.a1.id, [(c[0]["id"], "0")]).status_code == 422
    assert cobrar(client, h, e.a1.id, [(c[0]["id"], "1.001")]).status_code == 422  # tres decimales
    assert cobrar(client, h, e.a1.id, [(c[0]["id"], "10"), (c[0]["id"], "10")]).status_code == 422
    assert db.scalar(select(func.count()).select_from(Pago)) == 1


def test_numero_de_operacion_obligatorio_y_no_se_repite(client, db, e, h):
    armar(client, h, e)
    c = cuotas(client, h, e.a1.id)
    abrir(client, h)
    assert cobrar(client, h, e.a1.id, [(c[0]["id"], "10")], medio="yape").status_code == 422
    assert cobrar(client, h, e.a1.id, [(c[0]["id"], "10")], medio="yape", operacion="555").status_code == 201
    r = cobrar(client, h, e.a1.id, [(c[0]["id"], "10")], medio="yape", operacion=" 555 ")
    assert r.status_code == 409 and "operación" in r.json()["detail"]
    assert cobrar(client, h, e.a1.id, [(c[0]["id"], "10")], medio="plin", operacion="555").status_code == 201
    # Con un pago repetido rechazado el correlativo no saltó.
    assert [p.correlativo for p in db.scalars(select(Pago).order_by(Pago.id))] == [1, 2]


def test_correlativo_sin_saltos_ni_repetidos_con_cobros_simultaneos(client, db, e, h):
    armar(client, h, e)
    for dni in ("50000001", "50000002", "50000003", "50000004"):
        crear_personal(db, e.colegio, dni, {"caja": "editar"})
    cajeros = []
    for dni in ("50000001", "50000002", "50000003", "50000004"):
        hc = auth("alfa", token(client, "alfa", dni))
        abrir(client, hc)
        cajeros.append(hc)
    lista = cuotas(client, h, e.a3.id)
    barrera = threading.Barrier(len(cajeros))
    codigos = []

    def cobra(hc, cuota_id):
        cli = TestClient(app)
        barrera.wait()
        codigos.append(cobrar(cli, hc, e.a3.id, [(cuota_id, "1.00")]).status_code)

    hilos = [threading.Thread(target=cobra, args=(hc, x["id"])) for hc, x in zip(cajeros, lista)]
    for t in hilos:
        t.start()
    for t in hilos:
        t.join()
    assert codigos == [201] * 4
    db.expire_all()
    assert sorted(p.correlativo for p in db.scalars(select(Pago))) == [1, 2, 3, 4]
    assert db.get(ConfigPensiones, e.colegio.id).correlativo_recibo == 4


def test_recibo_en_pdf(client, e, h):
    armar(client, h, e)
    c = cuotas(client, h, e.a1.id)
    abrir(client, h)
    p = cobrar(client, h, e.a1.id, [(c[0]["id"], "50")]).json()
    assert p["recibo"] == "R001-000001"
    r = client.get(f"/api/caja/pagos/{p['id']}/recibo.pdf", headers=h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"


# --- Anulación y cierre ---------------------------------------------------------------------------

def test_anular_devuelve_el_saldo_y_no_borra(client, db, e, h):
    armar(client, h, e)
    c = cuotas(client, h, e.a1.id)
    abrir(client, h)
    p = cobrar(client, h, e.a1.id, [(c[0]["id"], "50.25"), (c[1]["id"], "10")], medio="yape", operacion="9").json()
    assert client.post(f"/api/caja/pagos/{p['id']}/anular", headers=h, json={"motivo": ""}).status_code == 422
    r = client.post(f"/api/caja/pagos/{p['id']}/anular", headers=h, json={"motivo": "Se cobró al alumno equivocado"})
    assert r.status_code == 200 and r.json()["anulado"] and r.json()["anulado_por"] == "Dir alfa"
    assert client.post(f"/api/caja/pagos/{p['id']}/anular", headers=h, json={"motivo": "Otra vez"}).status_code == 409
    c = cuotas(client, h, e.a1.id)
    assert (c[0]["pagado"], c[1]["pagado"]) == ("0.00", "0.00")
    assert db.scalar(select(func.count()).select_from(Pago)) == 1
    assert db.scalar(select(func.count()).select_from(PagoDetalle)) == 2
    # El número de operación de un pago anulado se puede volver a usar.
    assert cobrar(client, h, e.a1.id, [(c[0]["id"], "50.25")], medio="yape", operacion="9").status_code == 201
    # La lista muestra el anulado.
    estados = {x["recibo"]: x["anulado"] for x in client.get("/api/caja/pagos", headers=h).json()["items"]}
    assert estados == {"R001-000001": True, "R001-000002": False}


def test_caja_cerrada_no_deja_anular_al_cajero_pero_si_al_director(client, db, e, h):
    armar(client, h, e)
    crear_personal(db, e.colegio, "50000001", {"caja": "editar"})
    crear_personal(db, e.colegio, "50000002", {"caja": "editar"})
    hc = auth("alfa", token(client, "alfa", "50000001"))
    otro = auth("alfa", token(client, "alfa", "50000002"))
    c = cuotas(client, h, e.a1.id)
    abrir(client, hc)
    p1 = cobrar(client, hc, e.a1.id, [(c[0]["id"], "20")]).json()
    p2 = cobrar(client, hc, e.a1.id, [(c[1]["id"], "30")], medio="tarjeta", operacion="T1").json()
    # Otro cajero no anula lo ajeno.
    assert client.post(f"/api/caja/pagos/{p1['id']}/anular", headers=otro, json={"motivo": "xxx"}).status_code == 403
    r = client.post("/api/caja/cerrar", headers=hc, json={"contado": "15.50"})
    assert r.status_code == 200, r.text
    cierre = r.json()
    assert cierre["totales"]["efectivo"] == "20.00" and cierre["totales"]["tarjeta"] == "30.00"
    assert (cierre["total"], cierre["contado"], cierre["diferencia"]) == ("50.00", "15.50", "-4.50")
    # Caja cerrada: el cajero ya no anula ni cobra con ella.
    r = client.post(f"/api/caja/pagos/{p1['id']}/anular", headers=hc, json={"motivo": "xxx"})
    assert r.status_code == 403 and "director" in r.json()["detail"]
    assert cobrar(client, hc, e.a1.id, [(c[0]["id"], "1")]).status_code == 409
    assert client.post(f"/api/caja/pagos/{p2['id']}/anular", headers=h, json={"motivo": "Revisión"}).status_code == 200
    # El cierre guardado no cambia; los reportes sí cuentan solo lo válido.
    cajas = client.get("/api/caja/cajas", headers=h).json()["items"]
    assert cajas[0]["total"] == "50.00"
    r = client.get("/api/caja/reportes/ingresos", headers=h, params={"agrupar": "medio"}).json()
    assert r["total"] == "20.00" and r["items"] == [{"grupo": "Efectivo", "pagos": 1, "total": "20.00"}]


# --- Gastos -----------------------------------------------------------------------------------------

def _gasto(client, h, categoria_id, archivo=None, **extra):
    datos = {"fecha": HOY.isoformat(), "categoria_id": categoria_id, "descripcion": "Recibo de luz",
             "monto": "120.40", "medio": "transferencia", "comprobante_tipo": "Recibo", "comprobante_numero": "001-9",
             **extra}
    return client.post("/api/caja/gastos", headers=h, data={"datos": json.dumps(datos)},
                       files={"archivo": archivo} if archivo else None)


def test_categorias_por_defecto_y_gastos(client, db, e, h):
    from app.configuracion import crear_categorias_por_defecto
    crear_categorias_por_defecto(db, e.colegio.id)
    db.commit()
    cats = client.get("/api/caja/categorias", headers=h).json()
    assert [c["nombre"] for c in cats] == ["Servicios", "Materiales", "Mantenimiento", "Planilla", "Otros"]
    servicios = cats[0]["id"]
    assert _gasto(client, h, servicios, ("foto.png", b"no es imagen", "image/png")).status_code == 422
    assert _gasto(client, h, servicios, ("a.pdf", b"%PDF" + b"0" * (5 * 1024 * 1024), "application/pdf")
                  ).status_code == 422  # más de 5 MB
    r = _gasto(client, h, servicios, ("comprobante.jpg", PNG, "image/jpeg"))  # dice JPG, es PNG: vale lo real
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["archivo"] and db.get(Gasto, g["id"]).archivo_tipo == "image/png"
    archivo = client.get(f"/api/caja/gastos/{g['id']}/archivo", headers=h)
    assert archivo.status_code == 200 and archivo.content == PNG
    assert _gasto(client, h, servicios, monto="-1").status_code == 422
    r = client.post(f"/api/caja/gastos/{g['id']}/anular", headers=h, json={"motivo": "Duplicado"})
    assert r.status_code == 200 and r.json()["anulado"]
    assert db.scalar(select(func.count()).select_from(Gasto)) == 1  # no se borra
    _gasto(client, h, servicios, monto="10.10")
    _gasto(client, h, cats[1]["id"], monto="5.05")
    r = client.get("/api/caja/reportes/gastos", headers=h).json()
    assert r["total"] == "15.15" and r["items"][0] == {"grupo": "Servicios", "gastos": 1, "total": "10.10"}


# --- Reportes ---------------------------------------------------------------------------------------

def test_morosidad_e_ingresos_con_excel(client, db, e, h):
    armar(client, h, e, monto="100.00")
    c = cuotas(client, h, e.a1.id)
    abrir(client, h)
    cobrar(client, h, e.a1.id, [(c[0]["id"], "100.00"), (c[1]["id"], "40.00")])
    r = client.get("/api/pensiones/morosidad", headers=h).json()
    filas = {f["alumno"]: f for f in r["items"]}
    assert filas["Ape0, Niño0"]["cuotas"] == 1 and filas["Ape0, Niño0"]["monto"] == "60.00"
    assert filas["Ape1, Niño1"]["cuotas"] == 2 and filas["Ape1, Niño1"]["dias"] == 40
    assert filas["Ape2, Niño2"]["monto"] == "840.00"
    assert r["monto_total"] == "1100.00"
    for ruta in ("/api/pensiones/morosidad.xlsx", "/api/caja/reportes/ingresos.xlsx?agrupar=concepto",
                 "/api/caja/reportes/gastos.xlsx"):
        x = client.get(ruta, headers=h)
        assert x.status_code == 200 and x.content[:2] == b"PK", ruta
    por_concepto = client.get("/api/caja/reportes/ingresos", headers=h, params={"agrupar": "concepto"}).json()
    assert por_concepto["items"] == [{"grupo": "Pensión", "pagos": 1, "total": "140.00"}]
    por_cajero = client.get("/api/caja/reportes/ingresos", headers=h, params={"agrupar": "cajero"}).json()
    assert por_cajero["items"] == [{"grupo": "Dir alfa", "pagos": 1, "total": "140.00"}]
    inicio = client.get("/api/panel/resumen", headers=h).json()["pensiones"]
    assert inicio == {"cobrado_mes": "140.00", "deuda_vencida": "1100.00", "morosos": 3}


def test_paginacion_en_servidor(client, e, h):
    armar(client, h, e)
    r = client.get("/api/pensiones/alumnos", headers=h, params={"por_pagina": 2}).json()
    assert (r["total"], r["paginas"], len(r["items"])) == (3, 2, 2)
    r = client.get("/api/pensiones/alumnos", headers=h, params={"estado": "con_deuda_vencida"}).json()
    assert r["total"] == 3
    assert client.get("/api/pensiones/alumnos", headers=h, params={"por_pagina": 101}).status_code == 422


# --- Módulo apagado y permisos ---------------------------------------------------------------------

@pytest.mark.parametrize("modulo,ruta", [("pensiones", "/api/pensiones/conceptos"), ("caja", "/api/caja/mi-caja"),
                                         ("caja", "/api/caja/pagos"), ("pensiones", "/api/pensiones/morosidad")])
def test_modulo_apagado_da_403_aun_al_director(client, db, e, h, modulo, ruta):
    assert client.get(ruta, headers=h).status_code == 200
    e.colegio.modulos_apagados = [modulo]
    db.commit()
    r = client.get(ruta, headers=h)
    assert r.status_code == 403 and r.json()["detail"] == "Este módulo no está activo en el colegio"
    inicio = client.get("/api/panel/resumen", headers=h).json()
    assert ("pensiones" in inicio) == (modulo == "caja")  # las tarjetas, solo con pensiones encendido


def test_familia_sin_modulo_no_ve_pagos(client, db, e, h):
    hf = auth("alfa", token_familia(client, "alfa"))
    assert client.get("/api/familia/pagos", headers=hf).status_code == 200
    e.colegio.modulos_apagados = ["pensiones"]
    db.commit()
    assert client.get("/api/familia/pagos", headers=hf).status_code == 403


def test_rol_sin_permiso_da_403(client, db, e, h):
    armar(client, h, e)
    crear_personal(db, e.colegio, "50000001", {"pensiones": "ver", "caja": "ver"})
    crear_personal(db, e.colegio, "50000002", {"asistencia": "editar"})
    hv = auth("alfa", token(client, "alfa", "50000001"))
    hn = auth("alfa", token(client, "alfa", "50000002"))
    assert client.get("/api/pensiones/conceptos", headers=hv).status_code == 200
    assert client.post("/api/pensiones/generar", headers=hv).status_code == 403
    assert client.post("/api/pensiones/conceptos", headers=hv, json={"nombre": "X", "tipo": "otro"}).status_code == 403
    assert client.post("/api/caja/abrir", headers=hv).status_code == 403
    c = cuotas(client, h, e.a1.id)
    assert cobrar(client, hv, e.a1.id, [(c[0]["id"], "1")]).status_code == 403
    for ruta in ("/api/pensiones/conceptos", "/api/caja/pagos", "/api/caja/mi-caja", "/api/caja/gastos"):
        assert client.get(ruta, headers=hn).status_code == 403
    assert "pensiones" not in client.get("/api/panel/resumen", headers=hn).json()


# --- La familia ----------------------------------------------------------------------------------

def test_solo_el_responsable_de_pago_ve_la_deuda_y_sus_recibos(client, db, e, h):
    armar(client, h, e)
    c = cuotas(client, h, e.a1.id)
    abrir(client, h)
    p = cobrar(client, h, e.a1.id, [(c[0]["id"], "10")]).json()
    hf = auth("alfa", token_familia(client, "alfa"))
    # Nadie marcado: el primero (la madre, de id menor) ve a sus dos hijos.
    r = client.get("/api/familia/pagos", headers=hf).json()
    assert [x["id"] for x in r["hijos"]] == [e.a1.id, e.a2.id]
    hijo = r["hijos"][0]
    assert len(hijo["cuotas"]) == 4 and hijo["pagos"][0]["recibo"] == "R001-000001"
    assert client.get(f"/api/familia/pagos/{p['id']}/recibo.pdf", headers=hf).content.startswith(b"%PDF")
    # El director marca al padre como responsable de a1: la madre deja de ver esa deuda.
    r = client.post(f"/api/padron/alumnos/{e.a1.id}/apoderados", headers=h, json={
        "numero_documento": e.padre.numero_documento, "nombres": "Juan", "apellidos": "Quispe", "parentesco": "Padre",
        "responsable_pago": True})
    assert r.status_code == 201 and r.json()["responsable_pago"] is True
    detalle = client.get(f"/api/padron/alumnos/{e.a1.id}", headers=h).json()
    assert {a["parentesco"]: a["responsable_pago"] for a in detalle["apoderados"]} == {"Madre": False, "Padre": True}
    r = client.get("/api/familia/pagos", headers=hf).json()
    assert [x["id"] for x in r["hijos"]] == [e.a2.id]
    assert client.get(f"/api/familia/pagos/{p['id']}/recibo.pdf", headers=hf).status_code == 404
    # Uno solo por alumno, también en la base.
    db.expire_all()
    v = db.get(AlumnoApoderado, (e.a1.id, e.madre.id))
    v.responsable_pago = True
    with pytest.raises(IntegrityError):
        db.commit()


def test_la_deuda_no_bloquea_asistencia_ni_familia(client, db, e, h):
    armar(client, h, e)
    assert client.get("/api/pensiones/morosidad", headers=h).json()["total"] == 3
    r = client.post("/api/asistencia/marcaciones", headers=h, json={"marcaciones": [
        {"id_cliente": "x" * 20, "alumno_id": e.a1.id}]})
    assert r.status_code == 200, r.text
    hf = auth("alfa", token_familia(client, "alfa"))
    assert client.get("/api/familia/hijos", headers=hf).status_code == 200
    assert client.get("/api/familia/cuaderno", headers=hf).status_code == 200
    assert client.get("/api/familia/avisos", headers=hf).status_code == 200


# --- Avisos de cobro -----------------------------------------------------------------------------

def _push(db, ap):
    db.add(SuscripcionPush(colegio_id=ap.colegio_id, cuenta_id=ap.cuenta_id, endpoint=f"https://push.test/{ap.id}",
                           p256dh="k", auth="a"))
    db.commit()


def _cobros(db, colegio) -> list[ColaAviso]:
    return db.scalars(select(ColaAviso).where(ColaAviso.colegio_id == colegio.id, ColaAviso.tipo == "cobro")
                      .order_by(ColaAviso.id)).all()


def test_aviso_de_cobro_uno_por_apoderado_y_dia_sin_repetir(client, db, e, h):
    armar(client, h, e, vences=(-10, 0, 3, 30))
    assert pensiones.revisar_cobros(db, HOY) == 1  # la madre: a1 y a2, la que vence hoy y la de 3 días
    db.expire_all()
    cola = _cobros(db, e.colegio)
    assert len(cola) == 1 and cola[0].apoderado_id == e.madre.id
    assert len(cola[0].datos["cuotas"]) == 4 and "4 cuotas" in cola[0].datos["mensaje"]
    assert pensiones.revisar_cobros(db, HOY) == 0  # mismo día: nada nuevo
    marcadas = db.scalars(select(CuotaAlumno).where(CuotaAlumno.alumno_id == e.a1.id)).all()
    assert sum(c.aviso_previo_en is not None for c in marcadas) == 1
    assert sum(c.aviso_vencido_en is not None for c in marcadas) == 1
    # a3 no tiene apoderado: no hay a quién avisar (pero su cuota queda marcada).
    assert all(c.apoderado_id != e.padre.id for c in cola)


def test_aviso_de_cobro_no_sale_si_ya_pago_o_si_el_director_lo_apago(client, db, e, h):
    armar(client, h, e, vences=(-10, 0, 3, 30))
    abrir(client, h)
    for a in (e.a1, e.a2):
        c = cuotas(client, h, a.id)
        cobrar(client, h, a.id, [(c[1]["id"], c[1]["saldo"]), (c[2]["id"], c[2]["saldo"])])
    assert pensiones.revisar_cobros(db, HOY) == 0  # a1 y a2 pagaron: no hay a quién recordar


def test_aviso_de_cobro_apagado_por_el_director(client, db, e, h):
    armar(client, h, e, vences=(-10, 0, 3, 30))
    r = client.put("/api/configuracion/avisos", headers=h, json={
        "tipos": {"cobro": False}, "silencio_desde": "21:00", "silencio_hasta": "06:00"})
    assert r.status_code == 200 and r.json()["tipos"]["cobro"] is False
    db.expire_all()
    assert pensiones.revisar_cobros(db, HOY) == 0
    # Uno que ya estaba en la cola tampoco sale.
    db.add(ColaAviso(colegio_id=e.colegio.id, tipo="cobro", apoderado_id=e.madre.id, fecha=HOY,
                     datos={"mensaje": "x"}))
    db.commit()
    avisos.procesar_cola(db, enviar=lambda sus, m: "ok")
    assert _cobros(db, e.colegio)[0].estado == "descartado"


def test_aviso_de_cobro_respeta_el_horario_sin_molestar(client, db, e, h):
    e.colegio.silencio_desde, e.colegio.silencio_hasta = time(21, 0), time(6, 0)
    db.commit()
    armar(client, h, e, vences=(-10, 0, 3, 30))
    _push(db, e.madre)
    pensiones.revisar_cobros(db, HOY)
    noche = datetime.combine(HOY, time(22, 30), LIMA).astimezone(UTC)
    enviados = []
    db.expire_all()
    aviso = _cobros(db, e.colegio)[0]
    aviso.procesar_desde = noche - timedelta(minutes=1)
    db.commit()
    avisos.procesar_cola(db, enviar=lambda sus, m: enviados.append(m) or "ok", ahora=noche)
    db.expire_all()
    aviso = _cobros(db, e.colegio)[0]
    assert enviados == [] and aviso.estado == "pendiente"
    manana = datetime.combine(HOY + timedelta(days=1), time(6, 0), LIMA).astimezone(UTC)
    assert aviso.procesar_desde == manana
    avisos.procesar_cola(db, enviar=lambda sus, m: enviados.append(m) or "ok", ahora=manana + timedelta(minutes=1))
    assert len(enviados) == 1 and enviados[0]["url"] == "/familia/pagos"
    assert enviados[0]["etiqueta"] == f"cobro-{aviso.id}"


# --- Historial ------------------------------------------------------------------------------------

def test_cada_accion_queda_en_el_historial(client, db, e, h):
    armar(client, h, e)
    c = cuotas(client, h, e.a1.id)
    abrir(client, h)
    p = cobrar(client, h, e.a1.id, [(c[0]["id"], "10")]).json()
    client.post(f"/api/caja/pagos/{p['id']}/anular", headers=h, json={"motivo": "Prueba"})
    client.post("/api/caja/cerrar", headers=h, json={"contado": "0"})
    acciones = set(db.execute(select(RegistroActividad.modulo, RegistroActividad.que, RegistroActividad.accion)).all())
    assert {("pensiones", "concepto", "crear"), ("pensiones", "cronograma", "crear"), ("pensiones", "cuotas", "crear"),
            ("caja", "caja", "crear"), ("caja", "pago", "crear"), ("caja", "pago", "anular"),
            ("caja", "caja", "editar")} <= acciones


# --- Excel del padrón: responsable de pago -----------------------------------------------------------

def test_excel_marca_al_responsable_de_pago(client, db, e, h):
    from io import BytesIO

    from openpyxl import Workbook

    from app.importacion import COL_ALUMNOS, COL_APODERADO

    wb = Workbook()
    ws = wb.active
    ws.title = "Alumnos"
    cab = list(COL_ALUMNOS.values())
    for n in (1, 2):
        cab += [f"Apoderado {n} {v}" for v in COL_APODERADO.values()]
    ws.append(cab)
    fila = ["DNI", e.a1.numero_documento, e.a1.apellidos, e.a1.nombres, "", "Primaria", "1°", "A",
            "DNI", e.madre.numero_documento, "Mamani", "Rosa", "Madre", "", "", "No",
            "DNI", e.padre.numero_documento, "Quispe", "Juan", "Padre", "", "", "Sí"]
    ws.append(fila)
    ws.append(["DNI", e.a2.numero_documento, e.a2.apellidos, e.a2.nombres, "", "Primaria", "2°", "A",
               "DNI", e.madre.numero_documento, "Mamani", "Rosa", "Madre", "", "", "Sí",
               "DNI", e.padre.numero_documento, "Quispe", "Juan", "Padre", "", "", "Sí"])
    buf = BytesIO()
    wb.save(buf)
    archivo = {"archivo": ("padron.xlsx", buf.getvalue(), "application/vnd.ms-excel")}
    r = client.post("/api/padron/importacion/vista-previa", headers=h, files=archivo)
    assert r.status_code == 200, r.text
    errores = r.json()["errores"]
    assert [x["fila"] for x in errores] == [3] and "Solo un apoderado" in errores[0]["mensaje"]
    ws.delete_rows(3)
    buf = BytesIO()
    wb.save(buf)
    archivo = {"archivo": ("padron.xlsx", buf.getvalue(), "application/vnd.ms-excel")}
    r = client.post("/api/padron/importacion/confirmar", headers=h, files=archivo)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert pensiones.responsables(db, e.colegio.id, [e.a1.id]) == {e.a1.id: e.padre.id}


# --- Demo -----------------------------------------------------------------------------------------

def test_demo_trae_pagos_variados_y_consistentes(db):
    from app import demo

    for _ in range(2):  # reiniciar también funciona
        res = demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=4)
    cid = res.colegio_id
    pagos = db.scalars(select(Pago).where(Pago.colegio_id == cid)).all()
    assert len({p.medio for p in pagos}) >= 4
    assert sorted(p.correlativo for p in pagos) == list(range(1, len(pagos) + 1))
    assert sum(p.anulado_en is not None for p in pagos) == 1
    # Lo pagado de cada cuota es la suma de sus pagos válidos.
    pagado = dict(db.execute(select(PagoDetalle.cuota_id, func.sum(PagoDetalle.monto))
                             .join(Pago, Pago.id == PagoDetalle.pago_id)
                             .where(Pago.colegio_id == cid, Pago.anulado_en.is_(None))
                             .group_by(PagoDetalle.cuota_id)).all())
    lista = db.scalars(select(CuotaAlumno).where(CuotaAlumno.colegio_id == cid)).all()
    assert all(c.pagado == pagado.get(c.id, 0) for c in lista)
    cfg = pensiones.config(db, cid)
    estados = {pensiones.situacion(c, db.get(CuotaProgramada, c.cuota_programada_id).vence, cfg, HOY).estado
               for c in lista}
    if HOY.month >= 4:  # con varias cuotas vencidas ya hay de todo
        assert {"pagada", "vencida", "pendiente"} <= estados
    assert db.scalar(select(func.count()).select_from(Gasto).where(Gasto.colegio_id == cid)) > 0


# --- Correcciones del PR #15 -------------------------------------------------------------------------

def _con_casilla(db, colegio, dni: str, permisos: dict[str, str]):
    """Personal cuyo rol tiene "Puede anular pagos de caja cerrada y gastos de días anteriores"."""
    u = crear_personal(db, colegio, dni, permisos)
    u.rol.puede_anular_caja = True
    db.commit()
    return u


def test_casilla_del_rol_para_anular_pagos(client, db, e, h):
    armar(client, h, e)
    crear_personal(db, e.colegio, "50000001", {"caja": "editar"})
    crear_personal(db, e.colegio, "50000002", {"caja": "editar"})
    _con_casilla(db, e.colegio, "50000003", {"caja": "editar"})
    _con_casilla(db, e.colegio, "50000004", {"caja": "ver"})
    cajero = auth("alfa", token(client, "alfa", "50000001"))
    otro = auth("alfa", token(client, "alfa", "50000002"))
    autorizado = auth("alfa", token(client, "alfa", "50000003"))
    solo_ver = auth("alfa", token(client, "alfa", "50000004"))
    c = cuotas(client, h, e.a1.id)
    abrir(client, cajero)
    p1, p2, p3, p4 = (cobrar(client, cajero, e.a1.id, [(c[0]["id"], m)]).json() for m in ("10", "11", "12", "13"))

    def anular(cabecera, p):
        return client.post(f"/api/caja/pagos/{p['id']}/anular", headers=cabecera, json={"motivo": "Revisión"})

    # Caja abierta de otro cajero: sin casilla 403, con casilla 200; la casilla no reemplaza "caja › editar".
    r = anular(otro, p1)
    assert r.status_code == 403 and "cajero que cobró" in r.json()["detail"]
    assert anular(solo_ver, p1).status_code == 403
    assert anular(autorizado, p1).status_code == 200
    assert client.post("/api/caja/cerrar", headers=cajero, json={"contado": "36"}).status_code == 200
    # Caja cerrada: el cajero 403; un rol con la casilla y el director, 200.
    r = anular(cajero, p2)
    assert r.status_code == 403 and "La caja ya se cerró" in r.json()["detail"]
    assert anular(solo_ver, p2).status_code == 403
    assert anular(autorizado, p2).status_code == 200
    assert anular(h, p3).status_code == 200
    assert anular(otro, p4).status_code == 403


def test_casilla_se_ve_y_se_edita_en_roles(client, db, e, h):
    r = client.post("/api/roles", headers=h, json={"nombre": "Tesorería", "permisos": {"caja": "editar"},
                                                   "puede_anular_caja": True})
    assert r.status_code == 201, r.text
    rol = r.json()
    assert rol["puede_anular_caja"] is True
    r = client.put(f"/api/roles/{rol['id']}", headers=h, json={"nombre": "Tesorería", "permisos": {"caja": "editar"}})
    assert r.status_code == 200 and r.json()["puede_anular_caja"] is False
    director = next(x for x in client.get("/api/roles", headers=h).json() if x["es_director"])
    assert director["puede_anular_caja"] is False  # no la necesita: siempre puede


def test_anular_gastos_con_la_misma_regla(client, db, e, h):
    from app.configuracion import crear_categorias_por_defecto
    crear_categorias_por_defecto(db, e.colegio.id)
    db.commit()
    crear_personal(db, e.colegio, "50000001", {"caja": "editar"})
    crear_personal(db, e.colegio, "50000002", {"caja": "editar"})
    _con_casilla(db, e.colegio, "50000003", {"caja": "editar"})
    quien = auth("alfa", token(client, "alfa", "50000001"))
    otro = auth("alfa", token(client, "alfa", "50000002"))
    autorizado = auth("alfa", token(client, "alfa", "50000003"))
    servicios = client.get("/api/caja/categorias", headers=h).json()[0]["id"]

    def anular(cabecera, g):
        return client.post(f"/api/caja/gastos/{g['id']}/anular", headers=cabecera, json={"motivo": "Duplicado"})

    # Del mismo día: quien lo registró sí; otro sin casilla no.
    hoy = _gasto(client, quien, servicios).json()
    r = anular(otro, hoy)
    assert r.status_code == 403 and "quien lo registró" in r.json()["detail"]
    assert anular(quien, hoy).status_code == 200
    # De un día anterior: quien lo registró ya no; un rol con la casilla sí.
    ayer = _gasto(client, quien, servicios, fecha=(HOY - timedelta(days=1)).isoformat()).json()
    r = anular(quien, ayer)
    assert r.status_code == 403 and "día anterior" in r.json()["detail"]
    assert anular(autorizado, ayer).status_code == 200
    antes = _gasto(client, quien, servicios, fecha=(HOY - timedelta(days=3)).isoformat()).json()
    assert anular(h, antes).status_code == 200  # el director siempre


def test_excel_sin_si_deja_al_apoderado_1_aunque_el_2_ya_exista_por_un_hermano(client, db, e, h):
    from io import BytesIO

    from openpyxl import Workbook

    from app.importacion import COL_ALUMNOS, COL_APODERADO

    # La madre ya existe (hermanos a1 y a2) y el padre de a1 ya está marcado como responsable.
    pensiones.marcar_responsable(db, e.colegio.id, e.a1.id, e.padre.id)
    db.commit()
    wb = Workbook()
    ws = wb.active
    ws.title = "Alumnos"
    cab = list(COL_ALUMNOS.values())
    for n in (1, 2):
        cab += [f"Apoderado {n} {v}" for v in COL_APODERADO.values()]
    ws.append(cab)
    # Hermano nuevo: apoderado 1 nuevo (la tía), apoderado 2 la madre que ya existía; nadie con "Sí".
    ws.append(["DNI", "71111111", "QUISPE MAMANI", "Teo", "", "Primaria", "1°", "A",
               "DNI", "42222222", "Mamani", "Ana", "Tía", "", "", "",
               "DNI", e.madre.numero_documento, "Mamani", "Rosa", "Madre", "", "", "No"])
    # a1 ya tiene responsable (el padre): sin "Sí" en la fila no cambia.
    ws.append(["DNI", e.a1.numero_documento, e.a1.apellidos, e.a1.nombres, "", "Primaria", "1°", "A",
               "DNI", e.madre.numero_documento, "Mamani", "Rosa", "Madre", "", "", "",
               "DNI", e.padre.numero_documento, "Quispe", "Juan", "Padre", "", "", ""])
    buf = BytesIO()
    wb.save(buf)
    r = client.post("/api/padron/importacion/confirmar", headers=h,
                    files={"archivo": ("padron.xlsx", buf.getvalue(), "application/vnd.ms-excel")})
    assert r.status_code == 200, r.text
    db.expire_all()
    teo = db.scalar(select(Alumno).where(Alumno.colegio_id == e.colegio.id, Alumno.numero_documento == "71111111"))
    tia = db.scalar(select(Apoderado).where(Apoderado.colegio_id == e.colegio.id,
                                            Apoderado.numero_documento == "42222222"))
    assert tia.id > e.madre.id  # por orden de id saldría la madre; manda la fila
    marcados = db.scalars(select(AlumnoApoderado.apoderado_id).where(
        AlumnoApoderado.colegio_id == e.colegio.id, AlumnoApoderado.alumno_id == teo.id,
        AlumnoApoderado.responsable_pago)).all()
    assert marcados == [tia.id]
    assert pensiones.responsables(db, e.colegio.id, [e.a1.id]) == {e.a1.id: e.padre.id}


def test_vencimiento_hasta_3_meses_antes_del_inicio_de_clases(client, db, e, h):
    e.anio.inicio = date(HOY.year, 3, 1)
    db.commit()
    c = concepto(client, h, "Matrícula", "matricula")

    def agregar(vence: date):
        return client.post(f"/api/pensiones/conceptos/{c['id']}/cronograma", headers=h,
                           json={"numero": 1, "mes": "Matrícula", "vence": vence.isoformat()})

    assert agregar(date(HOY.year - 1, 11, 30)).status_code == 422  # noviembre del año anterior: no
    r = agregar(e.anio.fin + timedelta(days=1))  # después del fin: no
    assert r.status_code == 422 and "3 meses antes del inicio" in r.json()["detail"]
    assert agregar(date(HOY.year - 1, 12, 1)).status_code == 201  # justo 3 meses antes: sí
    r = client.put(f"/api/pensiones/cronograma/{client.get('/api/pensiones/conceptos', headers=h).json()['conceptos'][0]['cronograma'][0]['id']}",
                   headers=h, json={"numero": 1, "mes": "Matrícula", "vence": date(HOY.year, 1, 15).isoformat()})
    assert r.status_code == 200, r.text  # enero, antes de marzo: sí
    assert client.get("/api/pensiones/conceptos", headers=h).json()["anio"]["vence_desde"] == f"{HOY.year - 1}-12-01"
    assert desde_vencimiento(date(2026, 5, 31)) == date(2026, 2, 28)  # el día que no existe: último del mes


def test_colegio_nuevo_sin_pensiones_ni_caja_y_la_demo_con_ambos(client, db):
    from app import demo

    nuevo = crear_colegio(db, "nuevo")
    assert set(nuevo.modulos_contratados) == {"asistencia", "cuaderno", "familias", "reuniones"}
    hn = auth("nuevo", token(client, "nuevo"))
    assert client.get("/api/pensiones/config", headers=hn).status_code == 403
    assert client.get("/api/caja/mi-caja", headers=hn).status_code == 403
    # El servidor de la base también: un INSERT sin la columna nace sin ellos.
    defecto = db.scalar(text("SELECT column_default FROM information_schema.columns "
                             "WHERE table_name = 'colegio' AND column_name = 'modulos_contratados'"))
    assert "reuniones" in defecto and "pensiones" not in defecto and "caja" not in defecto
    res = demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=2)
    d = db.get(Colegio, res.colegio_id)
    assert d.modulo_activo("pensiones") and d.modulo_activo("caja")
    hd = auth("demo", token(client, "demo", res.credenciales["director"]["usuario"],
                            res.credenciales["director"]["clave"]))
    assert client.get("/api/pensiones/config", headers=hd).status_code == 200
    assert client.get("/api/caja/mi-caja", headers=hd).status_code == 200


def test_migracion_de_correcciones_sube_y_baja(db):
    import os

    from alembic import command
    from alembic.config import Config

    real = crear_colegio(db, "real")
    db.execute(text("UPDATE colegio SET modulos_contratados = modulos_contratados || '[\"pensiones\"]'::jsonb "
                    "WHERE id = :c"), {"c": real.id})  # pensiones contratado antes de la corrección
    prueba = crear_colegio(db, "demo2", es_demo=True)
    al = Alumno(colegio_id=real.id, numero_documento="70000001", nombres="A", apellidos="B", codigo="MIGRAAAA")
    ap1 = Apoderado(colegio_id=real.id, numero_documento="40000011", nombres="P", apellidos="Uno")
    ap2 = Apoderado(colegio_id=real.id, numero_documento="40000012", nombres="P", apellidos="Dos")
    db.add_all([al, ap1, ap2])
    db.flush()
    db.add_all([AlumnoApoderado(colegio_id=real.id, alumno_id=al.id, apoderado_id=ap2.id, parentesco="Padre"),
                AlumnoApoderado(colegio_id=real.id, alumno_id=al.id, apoderado_id=ap1.id, parentesco="Madre")])
    db.commit()
    db.close()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))

    def modulos(cid):
        with get_engine().connect() as conn:
            return conn.execute(text("SELECT modulos_contratados, modulos_apagados FROM colegio WHERE id = :c"),
                                {"c": cid}).one()

    try:
        command.downgrade(cfg, "8319188332ef")
        contratados, apagados = modulos(real.id)
        assert {"pensiones", "caja"} <= set(contratados) and "caja" in apagados and "pensiones" not in apagados
        command.upgrade(cfg, "head")
    finally:
        command.upgrade(cfg, "head")
    contratados, apagados = modulos(real.id)
    assert "pensiones" not in contratados and "caja" not in contratados and apagados == []
    contratados, apagados = modulos(prueba.id)
    assert {"pensiones", "caja"} <= set(contratados) and apagados == []
    with get_engine().connect() as conn:
        marcados = conn.execute(text("SELECT apoderado_id FROM alumno_apoderado WHERE alumno_id = :a "
                                     "AND responsable_pago"), {"a": al.id}).scalars().all()
        assert marcados == [ap1.id]  # el de apoderado_id menor
        assert conn.execute(text("SELECT puede_anular_caja FROM rol LIMIT 1")).scalar() is False
