"""Aislamiento entre colegios y entre tipos de token."""

import re

import pytest
from fastapi.routing import iter_route_contexts
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError

from app.db import Base, get_engine
from app.main import app
from app.models import Rol, Usuario
from app.models.colegio import CONTRATABLES
from tests.conftest import (auth, crear_admin, crear_colegio, crear_familia, crear_personal, host, token,
                            token_familia, token_plataforma)

# Globales a propósito: la cuenta de familia (y sus passkeys) une hijos de varios colegios.
SIN_COLEGIO = {"colegio", "admin_plataforma", "cuenta_familia", "passkey_familia",
               "intento_fallido"}  # límite de intentos: claves de plataforma, de colegio o de IP
RUTAS_PUBLICAS = {"/api/auth/ingreso", "/api/publico/colegio", "/plataforma/auth/ingreso",
                  "/api/familia/ingreso", "/api/familia/activacion/revisar", "/api/familia/activacion/completar",
                  "/api/familia/passkey/opciones-ingreso", "/api/familia/passkey/ingreso",
                  # Modo reunión: el padre con el QR del aula (y luego con el código de su ficha), sin sesión.
                  "/api/familia/reunion/abrir", "/api/familia/reunion/alumno", "/api/familia/reunion/ficha",
                  "/api/familia/reunion/estado", "/api/familia/reunion/activar"}
FAMILIA = "/api/familia/"


def _rutas(prefijo: str, excluir: str | None = None) -> list[tuple[str, str]]:
    salida = []
    for ctx in iter_route_contexts(app.routes):
        if not ctx.methods or not ctx.path.startswith(prefijo) or ctx.path in RUTAS_PUBLICAS:
            continue
        if excluir and ctx.path.startswith(excluir):
            continue
        ruta = re.sub(r"\{[^}]+\}", "1", ctx.path)
        salida += [(m, ruta) for m in ctx.methods if m != "HEAD"]
    assert salida, f"No se encontraron rutas bajo {prefijo}"
    return sorted(salida)


RUTAS_API = _rutas("/api/", excluir=FAMILIA)  # del personal
RUTAS_FAMILIA = _rutas(FAMILIA)
RUTAS_PLATAFORMA = _rutas("/plataforma/")


@pytest.fixture
def dos(db):
    # Con todo contratado: un 403 en pensiones o caja no debe venir de un módulo apagado.
    return (crear_colegio(db, "alfa", modulos_contratados=list(CONTRATABLES)),
            crear_colegio(db, "beta", modulos_contratados=list(CONTRATABLES)))


# --- Esquema ---------------------------------------------------------------

def test_toda_tabla_tiene_colegio_id_con_llave_foranea():
    for tabla in Base.metadata.sorted_tables:
        if tabla.name in SIN_COLEGIO:
            continue
        assert "colegio_id" in tabla.c, f"{tabla.name} no tiene colegio_id"
        assert not tabla.c.colegio_id.nullable, f"{tabla.name}.colegio_id acepta NULL"
        destinos = {fk.column.table.name for fk in tabla.c.colegio_id.foreign_keys}
        assert "colegio" in destinos, f"{tabla.name}.colegio_id sin llave foránea a colegio"


def test_las_llaves_existen_en_la_base_migrada():
    insp = sa_inspect(get_engine())
    for tabla in Base.metadata.sorted_tables:
        if tabla.name in SIN_COLEGIO:
            continue
        fks = insp.get_foreign_keys(tabla.name)
        assert any(fk["referred_table"] == "colegio" and fk["constrained_columns"] == ["colegio_id"]
                   for fk in fks), f"Falta FK colegio_id en {tabla.name} (¿migración desactualizada?)"


def test_base_rechaza_colegio_inexistente(db):
    db.add(Rol(colegio_id=9999, nombre="Fantasma"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_base_rechaza_rol_de_otro_colegio(db, dos):
    a, b = dos
    rol_b = db.query(Rol).filter_by(colegio_id=b.id).first()
    db.add(Usuario(colegio_id=a.id, numero_documento="20000000", usuario="20000000", nombres="X", apellidos="Y",
                   rol_id=rol_b.id, clave_hash="x"))
    with pytest.raises(IntegrityError):
        db.commit()


# --- Host ------------------------------------------------------------------

@pytest.mark.parametrize("h", ["nadie.tikray.test", "www.tikray.test", "a.b.tikray.test", "tikray.test",
                               "otro-sitio.com"])
def test_host_desconocido_da_404(client, dos, h):
    assert client.get("/api/publico/colegio", headers={"Host": h}).status_code == 404


def test_dominio_propio(client, db):
    crear_colegio(db, "gamma", dominio_propio="colegiogamma.edu.pe")
    r = client.get("/api/publico/colegio", headers={"Host": "ColegioGamma.edu.pe:443"})
    assert r.status_code == 200 and r.json()["nombre"] == "Colegio gamma"


def test_colegio_suspendido_no_responde(client, db):
    c = crear_colegio(db, "alfa")
    tok = token(client, "alfa")
    c.estado = "suspendido"
    db.commit()
    assert client.get("/api/auth/yo", headers=auth("alfa", tok)).status_code == 403
    r = client.get("/api/publico/colegio", headers=host("alfa"))
    assert r.status_code == 403 and r.json()["detail"] == "El acceso a este colegio está suspendido"


# --- Token de un colegio en el Host de otro: 403 en todas las rutas ----------

@pytest.mark.parametrize("metodo,ruta", RUTAS_API)
def test_token_de_otro_colegio_da_403(client, dos, metodo, ruta):
    tok_alfa = token(client, "alfa")
    r = client.request(metodo, ruta, headers=auth("beta", tok_alfa))
    assert r.status_code == 403, (metodo, ruta, r.status_code)
    assert r.json()["detail"] == "El token no corresponde a este colegio"


@pytest.mark.parametrize("metodo,ruta", RUTAS_API)
def test_rutas_api_exigen_token(client, dos, metodo, ruta):
    assert client.request(metodo, ruta, headers=host("alfa")).status_code == 401


# --- Plataforma y colegio no se mezclan ------------------------------------

@pytest.mark.parametrize("metodo,ruta", RUTAS_API)
def test_token_plataforma_no_entra_a_colegio(client, db, dos, metodo, ruta):
    crear_admin(db)
    tok = token_plataforma(client)
    assert client.request(metodo, ruta, headers=auth("alfa", tok)).status_code == 401


@pytest.mark.parametrize("metodo,ruta", RUTAS_PLATAFORMA)
def test_token_colegio_no_entra_a_plataforma(client, dos, metodo, ruta):
    tok = token(client, "alfa")
    r = client.request(metodo, ruta, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401, (metodo, ruta, r.status_code)


@pytest.mark.parametrize("metodo,ruta", RUTAS_PLATAFORMA)
def test_plataforma_exige_token(client, metodo, ruta):
    assert client.request(metodo, ruta).status_code == 401


def test_director_no_entra_por_ingreso_de_plataforma(client, dos):
    r = client.post("/plataforma/auth/ingreso", json={"correo": "10000000", "clave": "ClaveBuena123"})
    assert r.status_code == 401


# --- Datos de otro colegio -------------------------------------------------

def test_listados_solo_del_propio_colegio(client, db, dos):
    a, b = dos
    crear_personal(db, b, "30000000", {"personal": "ver"})
    h = auth("alfa", token(client, "alfa"))
    personal = client.get("/api/personal", headers=h).json()
    assert [p["numero_documento"] for p in personal] == ["10000000"]
    roles = client.get("/api/roles", headers=h).json()
    assert [r["nombre"] for r in roles] == ["Director"]


def test_no_toca_recursos_de_otro_colegio_por_id(client, db, dos):
    a, b = dos
    otro = crear_personal(db, b, "30000000", {"personal": "ver"})
    h = auth("alfa", token(client, "alfa"))
    assert client.put(f"/api/roles/{otro.rol_id}", json={"nombre": "X"}, headers=h).status_code == 404
    assert client.delete(f"/api/roles/{otro.rol_id}", headers=h).status_code == 404
    assert client.post(f"/api/personal/{otro.id}/reiniciar-clave", headers=h).status_code == 404
    r = client.post("/api/personal", headers=h, json={
        "numero_documento": "40000000", "nombres": "N", "apellidos": "A", "rol_id": otro.rol_id})
    assert r.status_code == 422


def test_colegio_id_del_navegador_se_ignora(client, db, dos):
    a, b = dos
    h = auth("alfa", token(client, "alfa"))
    r = client.post("/api/roles", headers=h, json={"nombre": "Docente", "colegio_id": b.id})
    assert r.status_code == 201
    rol = db.get(Rol, r.json()["id"])
    assert rol.colegio_id == a.id


def test_mismo_dni_en_dos_colegios_son_cuentas_distintas(client, dos):
    tok_a, tok_b = token(client, "alfa"), token(client, "beta")
    yo_a = client.get("/api/auth/yo", headers=auth("alfa", tok_a)).json()
    yo_b = client.get("/api/auth/yo", headers=auth("beta", tok_b)).json()
    assert yo_a["apellidos"] == "alfa" and yo_b["apellidos"] == "beta"


# --- Familias: su propio token, también atado al colegio del Host ------------------

@pytest.mark.parametrize("metodo,ruta", RUTAS_FAMILIA)
def test_token_familia_de_otro_colegio_da_403(client, db, dos, metodo, ruta):
    a, b = dos
    crear_familia(db, a)
    crear_familia(db, b)  # la misma persona también es apoderada en beta
    tok = token_familia(client, "alfa")
    r = client.request(metodo, ruta, headers=auth("beta", tok))
    assert r.status_code == 403, (metodo, ruta, r.status_code)
    assert r.json()["detail"] == "El token no corresponde a este colegio"


@pytest.mark.parametrize("metodo,ruta", RUTAS_FAMILIA)
def test_rutas_familia_exigen_token_de_familia(client, db, dos, metodo, ruta):
    assert client.request(metodo, ruta, headers=host("alfa")).status_code == 401
    personal = token(client, "alfa")  # el token del personal no sirve como el de un padre
    assert client.request(metodo, ruta, headers=auth("alfa", personal)).status_code == 401


@pytest.mark.parametrize("metodo,ruta", RUTAS_API)
def test_token_familia_no_entra_a_rutas_del_personal(client, db, dos, metodo, ruta):
    crear_familia(db, dos[0])
    tok = token_familia(client, "alfa")
    assert client.request(metodo, ruta, headers=auth("alfa", tok)).status_code == 401


# --- Pensiones y caja: el colegio A no ve ni paga lo de B, ni con ids adivinados ------------------

def test_pensiones_y_caja_aisladas_por_colegio(client, db):
    import json

    from app.models import CuotaAlumno, Gasto, Pago
    from tests.test_pensiones import HOY, abrir, armar, cobrar, cuotas, preparar

    ea, eb = preparar(db, "alfa"), preparar(db, "beta", dni_madre="45555555")
    ha, hb = auth("alfa", token(client, "alfa")), auth("beta", token(client, "beta"))
    ca, cb = armar(client, ha, ea), armar(client, hb, eb)
    cuota_b = cuotas(client, hb, eb.a1.id)[0]
    abrir(client, hb)
    pago_b = cobrar(client, hb, eb.a1.id, [(cuota_b["id"], "10")]).json()
    from app.configuracion import crear_categorias_por_defecto
    crear_categorias_por_defecto(db, eb.colegio.id)
    crear_categorias_por_defecto(db, ea.colegio.id)
    db.commit()
    cat_b = client.get("/api/caja/categorias", headers=hb).json()[0]["id"]
    gasto_b = client.post("/api/caja/gastos", headers=hb, data={"datos": json.dumps({
        "fecha": HOY.isoformat(), "categoria_id": cat_b, "descripcion": "Luz", "monto": "5", "medio": "efectivo"})},
        files={"archivo": ("a.pdf", b"%PDF-1.4", "application/pdf")}).json()

    # Listados: solo lo propio.
    assert {c["id"] for c in client.get("/api/pensiones/conceptos", headers=ha).json()["conceptos"]} == {ca["id"]}
    assert client.get("/api/caja/pagos", headers=ha).json()["total"] == 0
    assert client.get("/api/caja/gastos", headers=ha).json()["total"] == 0
    assert client.get("/api/caja/cajas", headers=ha).json()["total"] == 0
    assert {a["id"] for a in client.get("/api/pensiones/alumnos", headers=ha).json()["items"]} == {
        ea.a1.id, ea.a2.id, ea.a3.id}
    assert client.get("/api/caja/alumnos", headers=ha, params={"q": "Ape"}).json() and all(
        a["id"] in (ea.a1.id, ea.a2.id, ea.a3.id) for a in client.get("/api/caja/alumnos", headers=ha,
                                                                        params={"q": "Ape"}).json())
    assert client.get("/api/caja/reportes/ingresos", headers=ha).json()["total"] == "0.00"
    assert {f["alumno_id"] for f in client.get("/api/pensiones/morosidad", headers=ha).json()["items"]} == {
        ea.a1.id, ea.a2.id, ea.a3.id}

    # Por id: 404 como si no existiera.
    assert client.get(f"/api/pensiones/alumnos/{eb.a1.id}", headers=ha).status_code == 404
    assert client.get(f"/api/caja/alumnos/{eb.a1.id}", headers=ha).status_code == 404
    assert client.get(f"/api/caja/pagos/{pago_b['id']}", headers=ha).status_code == 404
    assert client.get(f"/api/caja/pagos/{pago_b['id']}/recibo.pdf", headers=ha).status_code == 404
    assert client.post(f"/api/caja/pagos/{pago_b['id']}/anular", headers=ha, json={"motivo": "xxx"}).status_code == 404
    assert client.get(f"/api/caja/gastos/{gasto_b['id']}/archivo", headers=ha).status_code == 404
    assert client.post(f"/api/caja/gastos/{gasto_b['id']}/anular", headers=ha, json={"motivo": "xxx"}).status_code == 404
    assert client.put(f"/api/pensiones/conceptos/{cb['id']}", headers=ha, json={"nombre": "X", "tipo": "otro"}
                      ).status_code == 404
    assert client.put(f"/api/pensiones/conceptos/{cb['id']}/montos", headers=ha, json={"montos": []}).status_code == 404
    assert client.put(f"/api/pensiones/conceptos/{ca['id']}/montos", headers=ha, json={"montos": [
        {"grado_id": eb.g1.id, "monto": "1"}]}).status_code == 404
    assert client.delete(f"/api/pensiones/cronograma/{cb['cronograma'][0]['id']}", headers=ha).status_code == 404
    assert client.post("/api/pensiones/descuentos", headers=ha, json={
        "alumno_id": eb.a1.id, "tipo": "porcentaje", "valor": "10", "motivo": "Beca"}).status_code == 404
    assert client.post("/api/pensiones/descuentos", headers=ha, json={
        "alumno_id": ea.a1.id, "concepto_id": cb["id"], "tipo": "porcentaje", "valor": "10", "motivo": "Beca"}
                       ).status_code == 404

    # Cobrar una cuota de B desde A: ni con el alumno de B ni mezclada con un alumno propio.
    abrir(client, ha)
    assert cobrar(client, ha, eb.a1.id, [(cuota_b["id"], "1")]).status_code == 404
    assert cobrar(client, ha, ea.a1.id, [(cuota_b["id"], "1")]).status_code == 404
    db.expire_all()
    assert db.get(CuotaAlumno, cuota_b["id"]).pagado == 10
    assert db.scalar(select_count(Pago, ea.colegio.id)) == 0
    assert db.scalar(select_count(Gasto, ea.colegio.id)) == 0

    # La base tampoco acepta un detalle de pago que apunte a una cuota de otro colegio.
    from app.models import PagoDetalle
    otro_pago = cobrar(client, ha, ea.a1.id, [(cuotas(client, ha, ea.a1.id)[0]["id"], "1")]).json()
    db.add(PagoDetalle(colegio_id=ea.colegio.id, pago_id=otro_pago["id"], cuota_id=cuota_b["id"], monto=1))
    with pytest.raises(IntegrityError):
        db.commit()


def test_familia_no_ve_pagos_de_otro_colegio(client, db):
    from tests.test_pensiones import abrir, armar, cobrar, cuotas, preparar

    ea, eb = preparar(db, "alfa"), preparar(db, "beta", dni_madre="45555555")
    ha, hb = auth("alfa", token(client, "alfa")), auth("beta", token(client, "beta"))
    armar(client, ha, ea)
    armar(client, hb, eb)
    abrir(client, hb)
    pago_b = cobrar(client, hb, eb.a1.id, [(cuotas(client, hb, eb.a1.id)[0]["id"], "10")]).json()
    hf = auth("alfa", token_familia(client, "alfa"))
    assert {x["id"] for x in client.get("/api/familia/pagos", headers=hf).json()["hijos"]} == {ea.a1.id, ea.a2.id}
    assert client.get(f"/api/familia/pagos/{pago_b['id']}/recibo.pdf", headers=hf).status_code == 404


def select_count(modelo, colegio_id):
    from sqlalchemy import func, select

    return select(func.count()).select_from(modelo).where(modelo.colegio_id == colegio_id)


# --- Comprobantes electrónicos: A no ve, emite ni anula los de B, ni con ids adivinados ---------------

def test_comprobantes_aislados_por_colegio(client, db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app import facturacion
    from app.config import get_settings
    from app.models import ColaComprobante, Comprobante
    from tests.test_facturacion import CLAVE, RUC, TOKEN
    from tests.test_pensiones import abrir, armar, cobrar, cuotas, preparar

    monkeypatch.setattr(get_settings(), "facturacion_clave", CLAVE)
    monkeypatch.setitem(facturacion.PROVEEDORES, "prueba", facturacion.FacturadorPrueba)
    ea, eb = preparar(db, "alfa"), preparar(db, "beta", dni_madre="45555555")
    ha, hb = auth("alfa", token(client, "alfa")), auth("beta", token(client, "beta"))
    for hx, ex in ((ha, ea), (hb, eb)):
        r = client.put("/api/configuracion/facturacion", headers=hx, json={
            "emite": True, "ruc": RUC, "razon_social": "Colegio", "proveedor": "prueba", "token": TOKEN})
        assert r.status_code == 200, r.text
        armar(client, hx, ex)
        abrir(client, hx)
    # B cobra y su emisión falla 5 veces: queda en su lista de error.
    facturacion.FacturadorPrueba.reiniciar(*["fallar"] * 5)
    cuota_b = cuotas(client, hb, eb.a1.id)[0]
    pago_b = cobrar(client, hb, eb.a1.id, [(cuota_b["id"], "10")]).json()
    ahora = datetime.now(UTC)
    for _ in range(5):
        ahora += timedelta(hours=1)
        facturacion.procesar_cola(db, ahora=ahora)
    db.expire_all()
    tarea_b = db.scalar(select(ColaComprobante).where(ColaComprobante.colegio_id == eb.colegio.id))
    comp_b = db.scalar(select(Comprobante).where(Comprobante.colegio_id == eb.colegio.id))
    assert tarea_b.estado == "error"
    assert client.get("/api/caja/comprobantes/errores", headers=hb).json()["total"] == 1

    # A no lo ve, no lo reintenta (emitir) ni anula su pago (anular).
    assert client.get("/api/caja/comprobantes/errores", headers=ha).json()["total"] == 0
    assert client.get(f"/api/caja/pagos/{pago_b['id']}", headers=ha).status_code == 404
    assert client.post(f"/api/caja/comprobantes/tareas/{tarea_b.id}/reintentar", headers=ha).status_code == 404
    assert client.post(f"/api/caja/pagos/{pago_b['id']}/anular", headers=ha, json={"motivo": "xxx"}).status_code == 404
    # Ni cobrando una cuota de B se crea un comprobante.
    assert cobrar(client, ha, eb.a1.id, [(cuota_b["id"], "1")]).status_code == 404
    db.expire_all()
    assert db.get(ColaComprobante, tarea_b.id).estado == "error"
    assert db.scalar(select(ColaComprobante).where(ColaComprobante.accion == "anular")) is None
    assert db.scalar(select(Comprobante).where(Comprobante.colegio_id == ea.colegio.id)) is None
    # Cada colegio con su propio correlativo.
    propio = cobrar(client, ha, ea.a1.id, [(cuotas(client, ha, ea.a1.id)[0]["id"], "1")]).json()
    assert propio["comprobante"]["numero"] == "B001-00000001" == f"B001-{comp_b.numero:08d}"

    # La base tampoco acepta una orden de A que apunte a un comprobante de B.
    db.add(ColaComprobante(colegio_id=ea.colegio.id, comprobante_id=comp_b.id, accion="emitir"))
    with pytest.raises(IntegrityError):
        db.commit()
