"""Comprobantes electrónicos SUNAT (listos para conectar, sin proveedor real): configuración solo del director
y de Tikray Labs con el token cifrado, boleta o factura al cobrar sin esperar al proveedor, cola con
reintentos, correlativo sin saltos, anulación e IGV. El aislamiento entre colegios está en test_aislamiento.py."""

import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app import facturacion
from app.config import get_settings
from app.db import get_engine
from app.main import app
from app.models import ColaComprobante, Comprobante, ConfigFacturacion, RegistroActividad
from tests.conftest import auth, crear_admin, crear_personal, token, token_plataforma
from tests.test_pensiones import HOY, abrir, armar, cobrar, concepto, cuotas, linea, montos, preparar

D = Decimal
RUC = "20999999990"  # ficticio, con dígito verificador válido
RUC_CLIENTE = "20888888889"
TOKEN = "tok-proveedor-SECRETO-1234567890"
CLAVE = "clave-de-facturacion-de-pruebas-" + "x" * 16


@pytest.fixture
def e(db):
    return preparar(db, "alfa")


@pytest.fixture
def h(client, e):
    return auth("alfa", token(client, "alfa"))


@pytest.fixture
def prueba(monkeypatch):
    """Clave en el .env y el proveedor de prueba registrado."""
    monkeypatch.setattr(get_settings(), "facturacion_clave", CLAVE)
    monkeypatch.setitem(facturacion.PROVEEDORES, "prueba", facturacion.FacturadorPrueba)
    facturacion.FacturadorPrueba.reiniciar()
    return facturacion.FacturadorPrueba


def _plataforma(client, db) -> dict:
    crear_admin(db)
    return {"Authorization": f"Bearer {token_plataforma(client)}"}


def configurar(client, h, **cambios):
    datos = {"emite": True, "ruc": RUC, "razon_social": "Colegio Alfa SAC", "serie_boleta": "B001",
             "serie_factura": "F001", "proveedor": "prueba", "token": TOKEN, **cambios}
    return client.put("/api/configuracion/facturacion", headers=h, json=datos)


def activar(client, h, **cambios) -> dict:
    r = configurar(client, h, **cambios)
    assert r.status_code == 200, r.text
    return r.json()


def procesar(db, ahora=None) -> int:
    n = facturacion.procesar_cola(db, ahora=ahora)
    db.expire_all()
    return n


def comprobantes(db, colegio_id) -> list[Comprobante]:
    return list(db.scalars(select(Comprobante).where(Comprobante.colegio_id == colegio_id).order_by(Comprobante.id)))


# --- RUC y configuración -------------------------------------------------------------------------

def test_ruc_con_digito_verificador(client, e, h, prueba):
    assert facturacion.ruc_valido(RUC) and facturacion.ruc_valido("10777777772")
    assert not facturacion.ruc_valido("20999999991") and not facturacion.ruc_valido("2099999999")
    assert not facturacion.ruc_valido("2099999999A")
    r = configurar(client, h, ruc="20999999991")
    assert r.status_code == 422 and "RUC no es válido" in r.json()["detail"]
    assert configurar(client, h, ruc="123").status_code == 422
    # También el RUC del cliente de una factura.
    activar(client, h)
    armar(client, h, e)
    abrir(client, h)
    c = cuotas(client, h, e.a1.id)
    r = client.post("/api/caja/pagos", headers=h, json={
        "alumno_id": e.a1.id, "medio": "efectivo", "detalles": [{"cuota_id": c[0]["id"], "monto": "10"}],
        "factura": {"ruc": "20888888880", "razon_social": "Empresa"}})
    assert r.status_code == 422 and "RUC no es válido" in r.json()["detail"]


def test_sin_facturacion_clave_no_se_activa(client, db, e, h, monkeypatch):
    monkeypatch.setitem(facturacion.PROVEEDORES, "prueba", facturacion.FacturadorPrueba)
    monkeypatch.setattr(get_settings(), "facturacion_clave", "")
    r = configurar(client, h)
    assert r.status_code == 422 and "FACTURACION_CLAVE" in r.json()["detail"]
    r = configurar(client, h, emite=False)  # tampoco se puede guardar el token sin cifrarlo
    assert r.status_code == 422
    r = configurar(client, h, emite=False, token=None)  # los demás datos sí se guardan
    assert r.status_code == 200 and r.json()["emite"] is False and r.json()["clave_configurada"] is False
    assert db.get(ConfigFacturacion, e.colegio.id).token_cifrado is None
    with pytest.raises(ValueError):  # una clave corta no deja arrancar
        type(get_settings())(facturacion_clave="corta")


def test_para_emitir_pide_ruc_razon_social_y_token(client, e, h, prueba):
    assert configurar(client, h, ruc=None).status_code == 422
    assert configurar(client, h, razon_social="  ").status_code == 422
    assert configurar(client, h, token=None).status_code == 422
    assert configurar(client, h, serie_boleta="F001").status_code == 422
    assert configurar(client, h, proveedor="otro").status_code == 422
    cfg = activar(client, h, serie_boleta="b002")
    assert cfg["serie_boleta"] == "B002" and cfg["token_configurado"] is True
    # Sin escribir el token otra vez, se queda el que estaba.
    assert activar(client, h, token=None)["token_configurado"] is True


def test_token_nunca_aparece_en_respuestas_ni_historial(client, db, e, h, prueba):
    respuestas = [configurar(client, h).text, client.get("/api/configuracion/facturacion", headers=h).text]
    cfg = db.get(ConfigFacturacion, e.colegio.id)
    assert cfg.token_cifrado and TOKEN not in cfg.token_cifrado
    armar(client, h, e)
    abrir(client, h)
    p = cobrar(client, h, e.a1.id, [(cuotas(client, h, e.a1.id)[0]["id"], "10")])
    respuestas.append(p.text)
    procesar(db)
    assert prueba.tokens == [TOKEN]  # solo el proveedor lo recibe, descifrado
    respuestas += [client.get(f"/api/caja/pagos/{p.json()['id']}", headers=h).text,
                   client.get("/api/caja/comprobantes/errores", headers=h).text,
                   client.get("/api/configuracion/historial", headers=h).text]
    ht = _plataforma(client, db)
    respuestas.append(client.get(f"/plataforma/colegios/{e.colegio.id}/facturacion", headers=ht).text)
    respuestas.append(client.put(f"/plataforma/colegios/{e.colegio.id}/facturacion", headers=ht, json={
        "emite": True, "ruc": RUC, "razon_social": "Colegio Alfa SAC", "proveedor": "prueba",
        "token": TOKEN + "-nuevo"}).text)
    for r in respuestas:
        assert TOKEN not in r and "SECRETO" not in r
    assert '"token_configurado":true' in respuestas[0].replace(" ", "")
    for resumen in db.scalars(select(RegistroActividad.resumen).where(RegistroActividad.colegio_id == e.colegio.id)):
        assert "SECRETO" not in resumen


def test_solo_el_director_y_tikray_labs(client, db, e, h, prueba):
    crear_personal(db, e.colegio, "50000001", {"configuracion": "editar", "caja": "editar"})
    hp = auth("alfa", token(client, "alfa", "50000001"))
    assert client.get("/api/configuracion/facturacion", headers=hp).status_code == 403
    assert configurar(client, hp).status_code == 403
    ht = _plataforma(client, db)
    r = client.put(f"/plataforma/colegios/{e.colegio.id}/facturacion", headers=ht, json={
        "emite": True, "ruc": RUC, "razon_social": "Colegio Alfa SAC", "proveedor": "prueba", "token": TOKEN})
    assert r.status_code == 200 and r.json()["emite"] is True
    assert client.get("/plataforma/colegios/999999/facturacion", headers=ht).status_code == 404
    quien = db.scalar(select(RegistroActividad.quien).where(RegistroActividad.que == "facturacion"))
    assert quien == "Tikray Labs"


# --- Sin facturación todo sigue como hoy -----------------------------------------------------------

@pytest.mark.parametrize("como", ["sin_configurar", "apagada", "ninguno"])
def test_sin_facturacion_el_cobro_sigue_igual(client, db, e, h, prueba, como):
    if como == "apagada":
        activar(client, h, emite=False)
    elif como == "ninguno":
        activar(client, h, proveedor="ninguno", token=None)
    armar(client, h, e)
    caja = client.get("/api/caja/mi-caja", headers=h).json()
    assert caja["comprobantes"] is False
    abrir(client, h)
    c = cuotas(client, h, e.a1.id)
    r = cobrar(client, h, e.a1.id, [(c[0]["id"], "10")])
    assert r.status_code == 201 and r.json()["comprobante"] is None and r.json()["recibo"] == "R001-000001"
    assert comprobantes(db, e.colegio.id) == []
    assert db.scalar(select(func.count()).select_from(ColaComprobante)) == 0
    r = client.post("/api/caja/pagos", headers=h, json={
        "alumno_id": e.a1.id, "medio": "efectivo", "detalles": [{"cuota_id": c[0]["id"], "monto": "1"}],
        "factura": {"ruc": RUC_CLIENTE, "razon_social": "Empresa SAC"}})
    assert r.status_code == 422 and "no emite" in r.json()["detail"]
    assert procesar(db) == 0 and prueba.llamadas == []


# --- Con el proveedor de prueba ----------------------------------------------------------------------

def test_el_cobro_no_espera_al_proveedor_y_luego_se_acepta(client, db, e, h, prueba):
    activar(client, h)
    armar(client, h, e)
    assert client.get("/api/caja/mi-caja", headers=h).json()["comprobantes"] is True
    abrir(client, h)
    r = cobrar(client, h, e.a1.id, [(cuotas(client, h, e.a1.id)[0]["id"], "100")])
    assert r.status_code == 201
    comp = r.json()["comprobante"]
    assert comp["estado"] == "pendiente" and comp["tipo"] == "boleta" and comp["numero"] == "B001-00000001"
    assert r.json()["recibo"] == "R001-000001"  # E3: el recibo interno sale siempre
    assert prueba.llamadas == []  # el cobro no habló con el proveedor
    assert procesar(db) == 1
    assert prueba.llamadas == [("emitir", "B001-1")]
    comp = client.get(f"/api/caja/pagos/{r.json()['id']}", headers=h).json()["comprobante"]
    assert comp["estado"] == "aceptado" and comp["enlace_pdf"].endswith(".pdf") and comp["enlace_cdr"]
    assert client.get(f"/api/caja/pagos/{r.json()['id']}/recibo.pdf", headers=h).status_code == 200
    assert procesar(db) == 0  # ya no queda nada


def test_boleta_al_responsable_de_pago_y_factura_si_el_cajero_la_pide(client, db, e, h, prueba):
    from app import pensiones

    pensiones.marcar_responsable(db, e.colegio.id, e.a1.id, e.padre.id)
    db.commit()
    activar(client, h)
    armar(client, h, e)
    abrir(client, h)
    c = cuotas(client, h, e.a1.id)
    boleta = cobrar(client, h, e.a1.id, [(c[0]["id"], "10")]).json()["comprobante"]
    assert boleta["cliente_documento"] == f"DNI {e.padre.numero_documento}" and "Quispe" in boleta["cliente"]
    r = client.post("/api/caja/pagos", headers=h, json={
        "alumno_id": e.a1.id, "medio": "efectivo", "detalles": [{"cuota_id": c[0]["id"], "monto": "10"}],
        "factura": {"ruc": RUC_CLIENTE, "razon_social": "  Empresa   del Padre SAC "}})
    assert r.status_code == 201, r.text
    factura = r.json()["comprobante"]
    assert factura["tipo"] == "factura" and factura["numero"] == "F001-00000001"
    assert factura["cliente_documento"] == f"RUC {RUC_CLIENTE}" and factura["cliente"] == "Empresa del Padre SAC"


def test_rechazado_queda_en_la_lista_de_error(client, db, e, h, prueba):
    activar(client, h)
    armar(client, h, e)
    abrir(client, h)
    prueba.reiniciar("rechazar")
    p = cobrar(client, h, e.a1.id, [(cuotas(client, h, e.a1.id)[0]["id"], "10")]).json()
    procesar(db)
    lista = client.get("/api/caja/comprobantes/errores", headers=h).json()
    assert lista["total"] == 1
    item = lista["items"][0]
    assert item["estado"] == "rechazado" and item["pago_id"] == p["id"] and "Rechazado" in item["error"]
    assert item["tarea_id"] is None  # rechazado por SUNAT: no se reintenta igual


def test_falla_reintenta_con_espera_creciente_y_luego_reintentar(client, db, e, h, prueba):
    activar(client, h)
    armar(client, h, e)
    abrir(client, h)
    prueba.reiniciar(*["fallar"] * 5)
    p = cobrar(client, h, e.a1.id, [(cuotas(client, h, e.a1.id)[0]["id"], "10")]).json()
    ahora = datetime.now(UTC) + timedelta(seconds=1)
    esperas = []
    for _ in range(5):
        assert procesar(db, ahora) == 1
        t = db.scalar(select(ColaComprobante))
        if t.estado == "pendiente":
            esperas.append(round((t.procesar_desde - ahora).total_seconds() / 60))
            assert procesar(db, t.procesar_desde - timedelta(seconds=1)) == 0  # antes de su turno, nada
            ahora = t.procesar_desde
    assert esperas == [2, 4, 8, 16]
    t = db.scalar(select(ColaComprobante))
    assert t.estado == "error" and t.intentos == 5 and "no responde" in t.error
    assert db.scalar(select(Comprobante)).estado == "pendiente"
    assert procesar(db, ahora + timedelta(days=1)) == 0  # ya no sigue solo
    lista = client.get("/api/caja/comprobantes/errores", headers=h).json()
    assert lista["total"] == 1 and lista["items"][0]["tarea_id"] == t.id and lista["items"][0]["accion"] == "emitir"
    # Reintentar pide caja › editar.
    crear_personal(db, e.colegio, "50000001", {"caja": "ver"})
    hv = auth("alfa", token(client, "alfa", "50000001"))
    assert client.get("/api/caja/comprobantes/errores", headers=hv).status_code == 200
    assert client.post(f"/api/caja/comprobantes/tareas/{t.id}/reintentar", headers=hv).status_code == 403
    r = client.post(f"/api/caja/comprobantes/tareas/{t.id}/reintentar", headers=h)
    assert r.status_code == 200, r.text
    assert client.post(f"/api/caja/comprobantes/tareas/{t.id}/reintentar", headers=h).status_code == 409
    assert procesar(db) == 1
    assert client.get(f"/api/caja/pagos/{p['id']}", headers=h).json()["comprobante"]["estado"] == "aceptado"
    assert client.get("/api/caja/comprobantes/errores", headers=h).json()["total"] == 0


def test_enviado_se_consulta_despues(client, db, e, h, prueba):
    activar(client, h)
    armar(client, h, e)
    abrir(client, h)
    prueba.reiniciar("enviar", "aceptar")
    cobrar(client, h, e.a1.id, [(cuotas(client, h, e.a1.id)[0]["id"], "10")])
    procesar(db)
    assert db.scalar(select(Comprobante)).estado == "enviado"
    t = db.scalar(select(ColaComprobante))
    procesar(db, t.procesar_desde)
    assert prueba.llamadas == [("emitir", "B001-1"), ("consultar", "B001-1")]
    assert db.scalar(select(Comprobante)).estado == "aceptado"


def test_correlativo_sin_saltos_con_cobros_simultaneos(client, db, e, h, prueba):
    activar(client, h)
    armar(client, h, e)
    cajeros = []
    for dni in ("50000001", "50000002", "50000003", "50000004"):
        crear_personal(db, e.colegio, dni, {"caja": "editar"})
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

    hilos = [threading.Thread(target=cobra, args=(hc, x["id"])) for hc, x in zip(cajeros, lista, strict=True)]
    for t in hilos:
        t.start()
    for t in hilos:
        t.join()
    assert codigos == [201] * 4
    db.expire_all()
    assert sorted((c.serie, c.numero) for c in comprobantes(db, e.colegio.id)) == [("B001", n) for n in (1, 2, 3, 4)]


def test_anular_el_pago_encola_la_anulacion(client, db, e, h, prueba):
    activar(client, h)
    armar(client, h, e)
    abrir(client, h)
    c = cuotas(client, h, e.a1.id)
    p1 = cobrar(client, h, e.a1.id, [(c[0]["id"], "10")]).json()
    procesar(db)
    r = client.post(f"/api/caja/pagos/{p1['id']}/anular", headers=h, json={"motivo": "Cobro equivocado"})
    assert r.status_code == 200 and r.json()["comprobante"]["estado"] == "aceptado"
    tarea = db.scalar(select(ColaComprobante).where(ColaComprobante.accion == "anular"))
    assert tarea.estado == "pendiente" and tarea.motivo == "Cobro equivocado"
    procesar(db)
    assert prueba.llamadas[-1] == ("anular", "B001-1")
    comp = db.scalar(select(Comprobante).where(Comprobante.pago_id == p1["id"]))
    assert comp.estado == "anulado" and comp.anulado_en is not None
    assert "se pide anular la boleta B001-00000001" in db.scalar(
        select(RegistroActividad.resumen).where(RegistroActividad.accion == "anular"))

    # Anulado antes de que salga: la anulación espera a que termine la emisión.
    p2 = cobrar(client, h, e.a1.id, [(c[0]["id"], "10")]).json()
    prueba.reiniciar("fallar")
    procesar(db)  # la emisión falla una vez
    assert prueba.llamadas == [("emitir", "B001-2")]
    prueba.llamadas.clear()
    client.post(f"/api/caja/pagos/{p2['id']}/anular", headers=h, json={"motivo": "Otro error"})
    ahora = datetime.now(UTC) + timedelta(seconds=1)
    procesar(db, ahora)
    assert prueba.llamadas == []  # ni emite (espera su turno) ni anula antes de emitir
    procesar(db, ahora + timedelta(minutes=3))
    assert prueba.llamadas[0] == ("emitir", "B001-2")
    procesar(db, ahora + timedelta(minutes=5))
    assert prueba.llamadas[-1] == ("anular", "B001-2")
    assert db.scalar(select(Comprobante).where(Comprobante.pago_id == p2["id"])).estado == "anulado"


def test_anular_un_rechazado_no_llama_al_proveedor(client, db, e, h, prueba):
    activar(client, h)
    armar(client, h, e)
    abrir(client, h)
    prueba.reiniciar("rechazar")
    p = cobrar(client, h, e.a1.id, [(cuotas(client, h, e.a1.id)[0]["id"], "10")]).json()
    procesar(db)
    client.post(f"/api/caja/pagos/{p['id']}/anular", headers=h, json={"motivo": "Rechazado"})
    procesar(db)
    assert prueba.llamadas == [("emitir", "B001-1")]
    assert db.scalar(select(Comprobante)).estado == "anulado"


def test_igv_de_un_concepto_gravado_y_uno_inafecto_en_el_mismo_pago(client, db, e, h, prueba):
    activar(client, h)
    armar(client, h, e)  # pensión inafecta: 350.50
    uniforme = concepto(client, h, "Uniforme", "otro")
    assert uniforme["igv"] == "gravado"
    montos(client, h, uniforme["id"], [{"nivel_id": e.primaria.id, "monto": "118.00"},
                                       {"nivel_id": e.secundaria.id, "monto": "118.00"}])
    linea(client, h, uniforme["id"], 1, HOY + timedelta(days=5), "Uniforme")
    assert client.post("/api/pensiones/generar", headers=h).status_code == 200
    c = cuotas(client, h, e.a1.id)
    pension = next(x for x in c if x["concepto"] == "Pensión")
    unif = next(x for x in c if x["concepto"] == "Uniforme")
    abrir(client, h)
    r = cobrar(client, h, e.a1.id, [(pension["id"], "350.50"), (unif["id"], "118.00")])
    assert r.status_code == 201, r.text
    comp = r.json()["comprobante"]
    assert (comp["gravado"], comp["igv"], comp["inafecto"], comp["total"]) == ("100.00", "18.00", "350.50", "468.50")
    # Con céntimos que no dividen exacto, la suma cuadra con lo cobrado.
    unif2 = cuotas(client, h, e.a2.id)
    r = cobrar(client, h, e.a2.id, [(next(x for x in unif2 if x["concepto"] == "Uniforme")["id"], "10.01")])
    comp = r.json()["comprobante"]
    assert (comp["gravado"], comp["igv"]) == ("8.48", "1.53")
    assert D(comp["gravado"]) + D(comp["igv"]) + D(comp["inafecto"]) == D("10.01") == D(comp["total"])


def test_activar_un_colegio_de_prueba_borra_comprobantes_y_conserva_la_configuracion(client, db, e, h, prueba):
    from app.models import SerieComprobante

    activar(client, h)
    armar(client, h, e)
    abrir(client, h)
    cobrar(client, h, e.a1.id, [(cuotas(client, h, e.a1.id)[0]["id"], "10")])
    e.colegio.estado, e.colegio.vence_en = "prueba", HOY + timedelta(days=10)
    db.commit()
    ht = _plataforma(client, db)
    r = client.post(f"/plataforma/colegios/{e.colegio.id}/activar", headers=ht, json={"borrar_ejemplo": True, "confirmar": e.colegio.subdominio})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert comprobantes(db, e.colegio.id) == []
    assert db.scalar(select(func.count()).select_from(SerieComprobante)) == 0
    assert db.get(ConfigFacturacion, e.colegio.id).emite is True


# --- Migración ------------------------------------------------------------------------------------

def test_migracion_sube_y_baja(db):
    import os

    from alembic import command
    from alembic.config import Config

    db.close()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))

    def tablas():
        with get_engine().connect() as conn:
            return set(conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars())

    nuevas = {"config_facturacion", "serie_comprobante", "comprobante", "cola_comprobante"}
    try:
        command.downgrade(cfg, "bedf1d4d0ad5")
        assert not nuevas & tablas()
    finally:
        command.upgrade(cfg, "head")
    assert nuevas <= tablas()
