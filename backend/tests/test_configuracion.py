"""Configuración del administrador: perfil del colegio, módulos contratados, avisos a los padres (tipos y horario
sin molestar), comunicados programados, plantillas, categorías de incidencias, historial de actividad y el
paso de prueba a activo. Todo con aislamiento entre colegios."""

import json
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import func, select

from app import activacion, avisos, configuracion
from app.asistencia import marcar_faltas
from app.db import Base
from app.fechas import LIMA
from app.models import (Alumno, AlumnoApoderado, Apoderado, AsistenciaAlumno, CategoriaIncidencia, ColaAviso,
                        Colegio, CuentaFamilia, EntradaCuaderno, Grado, Marcacion, Nivel, PlantillaComunicado,
                        RegistroActividad, Rol, Seccion, Turno, Usuario)
from tests.conftest import (auth, crear_admin, crear_colegio, crear_familia, crear_personal, host, hoy, token,
                           token_familia, token_plataforma)
from tests.test_cuaderno import cola_cuaderno, escribir, preparar



@pytest.fixture
def e(db):
    return preparar(db, "alfa")


@pytest.fixture
def b(db):
    return preparar(db, "beta", dni_madre="45555555", dni_otro="46666666")


@pytest.fixture
def h(client, e):
    return auth("alfa", token(client, "alfa"))


@pytest.fixture
def hb(client, b):
    return auth("beta", token(client, "beta"))


@pytest.fixture
def hf(client, e):
    return auth("alfa", token_familia(client, "alfa"))


@pytest.fixture
def hp(client, db):
    crear_admin(db)
    return {"Authorization": f"Bearer {token_plataforma(client)}"}


def _categoria(db, colegio: Colegio, nombre: str = "Participación", tipo: str = "merito") -> CategoriaIncidencia:
    c = CategoriaIncidencia(colegio_id=colegio.id, nombre=nombre, tipo=tipo, orden=1)
    db.add(c)
    db.commit()
    return c


# --- Perfil del colegio --------------------------------------------------------------------

def test_perfil_lo_edita_el_administrador_y_lo_ve_solo_su_colegio(client, e, b, h, hb):
    r = client.get("/api/configuracion/perfil", headers=h)
    assert r.status_code == 200 and r.json()["tipo_gestion"] == "particular"
    nuevo = {"tipo_gestion": "estatal", "ugel": "UGEL 03", "codigo_modular": "0123456", "direccion": "Av. Lima 123",
             "telefono": "01 456 7890", "correo_contacto": "Info@Alfa.EDU.pe"}
    r = client.put("/api/configuracion/perfil", json=nuevo, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {**nuevo, "correo_contacto": "info@alfa.edu.pe"}
    # Beta sigue con lo suyo.
    assert client.get("/api/configuracion/perfil", headers=hb).json()["ugel"] is None
    # Validaciones.
    for malo in ({"codigo_modular": "12345"}, {"tipo_gestion": "mixta"}, {"correo_contacto": "no-es-correo"},
                 {"telefono": "abc"}):
        assert client.put("/api/configuracion/perfil", json={**nuevo, **malo}, headers=h).status_code == 422
    # Vaciar un campo con texto en blanco lo deja en nada.
    assert client.put("/api/configuracion/perfil", json={**nuevo, "ugel": "  "}, headers=h).json()["ugel"] is None


def test_perfil_requiere_permiso_de_configuracion(client, db, e):
    crear_personal(db, e.colegio, "20000001", {"configuracion": "ver"})
    hv = auth("alfa", token(client, "alfa", "20000001"))
    assert client.get("/api/configuracion/perfil", headers=hv).status_code == 200
    assert client.put("/api/configuracion/perfil", json={"tipo_gestion": "estatal"}, headers=hv).status_code == 403


def test_tikray_labs_ve_y_edita_el_perfil(client, db, e, b, hp):
    r = client.patch(f"/plataforma/colegios/{e.colegio.id}", headers=hp,
                     json={"perfil": {"tipo_gestion": "estatal", "ugel": "UGEL 01", "codigo_modular": "7654321"}})
    assert r.status_code == 200, r.text
    assert r.json()["perfil"]["ugel"] == "UGEL 01" and r.json()["perfil"]["tipo_gestion"] == "estatal"
    db.expire_all()
    assert db.get(Colegio, e.colegio.id).codigo_modular == "7654321"
    assert db.get(Colegio, b.colegio.id).codigo_modular is None
    lista = {c["subdominio"]: c for c in client.get("/plataforma/colegios", headers=hp).json()}
    assert lista["alfa"]["perfil"]["ugel"] == "UGEL 01" and lista["beta"]["perfil"]["ugel"] is None


# --- Módulos contratados -------------------------------------------------------------------

def test_modulo_apagado_sale_del_menu_y_su_api_da_403_aunque_el_rol_tenga_permiso(client, db, e, b, h, hb, hf):
    crear_personal(db, e.colegio, "20000002", {"cuaderno": "editar", "asistencia": "editar"})
    hd = auth("alfa", token(client, "alfa", "20000002"))
    assert "cuaderno" in client.get("/api/auth/yo", headers=hd).json()["permisos"]
    assert client.get("/api/cuaderno/entradas", headers=hd).status_code == 200

    r = client.put("/api/configuracion/modulos", json={"activos": ["asistencia", "familias", "reuniones"]}, headers=h)
    assert r.status_code == 200, r.text
    assert {m["clave"]: m["activo"] for m in r.json()}["cuaderno"] is False

    # Menú: el permiso ya no aparece (ni para el docente ni para el administrador).
    assert "cuaderno" not in client.get("/api/auth/yo", headers=hd).json()["permisos"]
    assert "cuaderno" not in client.get("/api/auth/yo", headers=h).json()["permisos"]
    assert "asistencia" in client.get("/api/auth/yo", headers=hd).json()["permisos"]
    # API: 403 para el docente con permiso, para el administrador y para la familia.
    for hh in (hd, h):
        assert client.get("/api/cuaderno/entradas", headers=hh).status_code == 403
        assert escribir(client, hh, tipo="comunicado", alcance="colegio").status_code == 403
    assert client.get("/api/familia/cuaderno", headers=hf).status_code == 403
    assert client.get("/api/familia/yo", headers=hf).json()["modulos"]["cuaderno"] is False
    # Beta no se entera.
    assert client.get("/api/cuaderno/entradas", headers=hb).status_code == 200
    assert "cuaderno" in client.get("/api/auth/yo", headers=hb).json()["permisos"]

    # Se vuelve a prender y todo regresa.
    client.put("/api/configuracion/modulos",
               json={"activos": ["asistencia", "cuaderno", "familias", "reuniones"]}, headers=h)
    assert client.get("/api/cuaderno/entradas", headers=hd).status_code == 200


def test_asistencia_apagada_no_marca_ni_pone_faltas(client, db, e, b, h):
    client.put("/api/configuracion/modulos", json={"activos": ["cuaderno", "familias", "reuniones"]}, headers=h)
    r = client.post("/api/asistencia/marcaciones", headers=h, json={"marcaciones": [
        {"id_cliente": uuid.uuid4().hex, "alumno_id": e.a1.id}]})
    assert r.status_code == 403
    assert client.get("/api/asistencia/marcaciones", headers=h).status_code == 403
    db.expire_all()  # el proceso de fondo abre una sesión nueva en cada vuelta
    marcar_faltas(db, hoy(), avisar=False)
    db.commit()
    assert db.scalar(select(func.count()).select_from(AsistenciaAlumno)
                     .where(AsistenciaAlumno.colegio_id == e.colegio.id)) == 0
    # Beta sí tuvo sus faltas.
    assert db.scalar(select(func.count()).select_from(AsistenciaAlumno)
                     .where(AsistenciaAlumno.colegio_id == b.colegio.id)) == 3


def test_el_administrador_solo_prende_lo_contratado(client, db, e, h, hp):
    r = client.patch(f"/plataforma/colegios/{e.colegio.id}", json={"modulos_contratados": ["asistencia"]}, headers=hp)
    assert r.status_code == 200, r.text
    modulos = {m["clave"]: m for m in client.get("/api/configuracion/modulos", headers=h).json()}
    assert modulos["cuaderno"] == {"clave": "cuaderno", "nombre": modulos["cuaderno"]["nombre"],
                                   "contratado": False, "activo": False}
    assert client.put("/api/configuracion/modulos", json={"activos": ["asistencia", "cuaderno"]},
                      headers=h).status_code == 403
    assert client.put("/api/configuracion/modulos", json={"activos": ["notas"]}, headers=h).status_code == 422
    # No contratado: fuera del menú y 403 en la API, aunque sea el administrador.
    assert "cuaderno" not in client.get("/api/auth/yo", headers=h).json()["permisos"]
    assert client.get("/api/cuaderno/entradas", headers=h).status_code == 403
    # Apagar lo contratado sí puede, y al recontratar vuelve a quedar como el administrador lo dejó.
    assert client.put("/api/configuracion/modulos", json={"activos": []}, headers=h).status_code == 200
    client.patch(f"/plataforma/colegios/{e.colegio.id}", headers=hp,
                 json={"modulos_contratados": ["asistencia", "cuaderno"]})
    activos = {m["clave"] for m in client.get("/api/configuracion/modulos", headers=h).json() if m["activo"]}
    assert activos == {"cuaderno"}


# --- Avisos a los padres -------------------------------------------------------------------

def _aviso(db, colegio, alumno, tipo: str) -> ColaAviso:
    a = ColaAviso(colegio_id=colegio.id, alumno_id=alumno.id, fecha=hoy(), tipo=tipo, momento=datetime.now(UTC),
                  datos={"hora": "07:50"})
    db.add(a)
    db.commit()
    return a


def test_el_administrador_elige_que_avisos_salen(client, db, e, b, h):
    tipos = {"ingreso": False, "tardanza": True, "falta": True, "salida": True, "cuaderno": False}
    r = client.put("/api/configuracion/avisos", headers=h,
                   json={"tipos": tipos, "silencio_desde": "00:00", "silencio_hasta": "00:00"})
    assert r.status_code == 200 and r.json()["tipos"] == tipos | {"cobro": True, "calendario": True, "autorizaciones": True}  # los que no se mandan, quedan
    ingreso, tarde = _aviso(db, e.colegio, e.a1, "ingreso"), _aviso(db, e.colegio, e.a1, "tarde")
    ingreso_beta = _aviso(db, b.colegio, b.a1, "ingreso")
    escribir(client, h, tipo="comunicado", alcance="colegio")
    db.expire_all()
    avisos.procesar_cola(db, enviar=lambda sus, m: "ok")
    db.expire_all()
    assert db.get(ColaAviso, ingreso.id).estado == "descartado"
    assert db.get(ColaAviso, ingreso.id).datos["motivo"] == "apagado por el colegio"
    assert db.get(ColaAviso, tarde.id).estado != "descartado"
    assert db.get(ColaAviso, ingreso_beta.id).estado != "descartado"
    assert {a.estado for a in cola_cuaderno(db, e.colegio)} == {"descartado"}


def test_horario_sin_molestar_retiene_el_cuaderno_y_no_la_asistencia(client, db, e, h):
    ahora = datetime.now(UTC)
    local = ahora.astimezone(LIMA)
    desde = (local - timedelta(hours=1)).strftime("%H:%M")
    hasta = (local + timedelta(hours=1)).strftime("%H:%M")
    r = client.put("/api/configuracion/avisos", headers=h,
                   json={"tipos": {}, "silencio_desde": desde, "silencio_hasta": hasta})
    assert r.status_code == 200 and r.json()["silencio_desde"] == desde
    ingreso = _aviso(db, e.colegio, e.a1, "ingreso")
    escribir(client, h, tipo="comunicado", alcance="colegio")
    db.expire_all()
    avisos.procesar_cola(db, enviar=lambda sus, m: "ok", ahora=datetime.now(UTC))
    db.expire_all()
    assert db.get(ColaAviso, ingreso.id).estado != "pendiente"  # la asistencia sale siempre
    cola = cola_cuaderno(db, e.colegio)
    assert cola and {a.estado for a in cola} == {"pendiente"}
    fin = datetime.combine(local.date() if hasta > local.strftime("%H:%M") else local.date() + timedelta(days=1),
                           time.fromisoformat(hasta), LIMA)
    assert {a.procesar_desde for a in cola} == {fin}
    # Al terminar el horario, sale.
    avisos.procesar_cola(db, enviar=lambda sus, m: "ok", ahora=fin + timedelta(minutes=1))
    db.expire_all()
    assert {a.estado for a in cola_cuaderno(db, e.colegio)} == {"enviado"}


def test_fin_del_silencio_cruza_la_medianoche():
    c = Colegio(silencio_desde=time(21), silencio_hasta=time(6))
    d = date(2026, 5, 4)
    noche = datetime.combine(d, time(22, 30), LIMA)
    madrugada = datetime.combine(d, time(5, 0), LIMA)
    assert configuracion.fin_del_silencio(c, noche) == datetime.combine(d + timedelta(days=1), time(6), LIMA)
    assert configuracion.fin_del_silencio(c, madrugada) == datetime.combine(d, time(6), LIMA)
    assert configuracion.fin_del_silencio(c, datetime.combine(d, time(12), LIMA)) is None
    assert configuracion.fin_del_silencio(Colegio(silencio_desde=time(0), silencio_hasta=time(0)), noche) is None


# --- Comunicados programados ---------------------------------------------------------------

def test_comunicado_programado_no_lo_ve_la_familia_hasta_su_hora_y_se_puede_cancelar(client, db, e, b, h, hb, hf):
    cuando = (datetime.now(UTC) + timedelta(hours=3)).replace(microsecond=0)
    r = escribir(client, h, tipo="comunicado", alcance="colegio", programado_para=cuando.isoformat())
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert datetime.fromisoformat(r.json()["programado_para"]) == cuando
    # El colegio lo ve en la bandeja con su hora; la familia no.
    lista = client.get("/api/cuaderno/entradas", headers=h).json()["entradas"]
    assert [datetime.fromisoformat(x["programado_para"]) for x in lista if x["id"] == eid] == [cuando]
    assert eid not in [x["id"] for x in client.get("/api/familia/cuaderno", headers=hf).json()["entradas"]]
    assert client.get(f"/api/familia/cuaderno/{eid}", headers=hf).status_code == 404
    # El aviso espera hasta su hora.
    assert {a.procesar_desde for a in cola_cuaderno(db, e.colegio)} == {cuando}
    avisos.procesar_cola(db, enviar=lambda sus, m: "ok")
    db.expire_all()
    assert {a.estado for a in cola_cuaderno(db, e.colegio)} == {"pendiente"}

    # Otro colegio no lo cancela; el suyo sí, y desaparece con sus avisos.
    assert client.post(f"/api/cuaderno/entradas/{eid}/cancelar", headers=hb).status_code == 404
    assert client.post(f"/api/cuaderno/entradas/{eid}/cancelar", headers=h).status_code in (200, 204)
    db.expire_all()
    assert db.get(EntradaCuaderno, eid) is None
    assert cola_cuaderno(db, e.colegio) == []
    hist = db.scalars(select(RegistroActividad).where(RegistroActividad.colegio_id == e.colegio.id,
                                                      RegistroActividad.accion == "anular")).all()
    assert any(x.que == "comunicado" for x in hist)


def test_comunicado_programado_sale_a_su_hora(client, db, e, h, hf):
    cuando = (datetime.now(UTC) + timedelta(hours=2)).replace(microsecond=0)
    eid = escribir(client, h, tipo="comunicado", alcance="colegio", programado_para=cuando.isoformat()).json()["id"]
    client.put("/api/configuracion/avisos", headers=h,
               json={"tipos": {}, "silencio_desde": "00:00", "silencio_hasta": "00:00"})
    db.expire_all()
    avisos.procesar_cola(db, enviar=lambda sus, m: "ok", ahora=cuando + timedelta(minutes=1))
    db.expire_all()
    assert {a.estado for a in cola_cuaderno(db, e.colegio)} == {"enviado"}
    # Ya pasó su hora: no se cancela.
    db.execute(EntradaCuaderno.__table__.update().where(EntradaCuaderno.id == eid)
               .values(programado_para=datetime.now(UTC) - timedelta(minutes=5)))
    db.commit()
    assert client.post(f"/api/cuaderno/entradas/{eid}/cancelar", headers=h).status_code == 409
    assert eid in [x["id"] for x in client.get("/api/familia/cuaderno", headers=hf).json()["entradas"]]


def test_programado_solo_comunicados_y_con_limites(client, e, h):
    futuro = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    # Una hora ya pasada se envía en el momento.
    r = escribir(client, h, tipo="comunicado", alcance="colegio",
                 programado_para=(datetime.now(UTC) - timedelta(hours=1)).isoformat())
    assert r.status_code == 201 and r.json()["programado_para"] is None
    assert escribir(client, h, tipo="comunicado", alcance="colegio",
                    programado_para=(datetime.now(UTC) + timedelta(days=120)).isoformat()).status_code == 422
    assert escribir(client, h, tipo="comunicado", alcance="colegio",
                    programado_para="2030-01-01T10:00:00").status_code == 422  # sin zona horaria
    assert escribir(client, h, tipo="incidencia", alcance="alumno", alumno_id=e.a1.id,
                    programado_para=futuro).status_code == 422


# --- Plantillas ------------------------------------------------------------------------------

def test_plantillas_crud_permisos_y_aislamiento(client, db, e, b, h, hb):
    r = client.post("/api/configuracion/plantillas", headers=h,
                    json={"nombre": "Reunión", "titulo": "Reunión de padres", "cuerpo": "El viernes a las 6"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert client.post("/api/configuracion/plantillas", headers=h,
                       json={"nombre": "Reunión", "titulo": "Otra"}).status_code == 409
    # El docente que escribe en el cuaderno las ve, pero no las crea.
    crear_personal(db, e.colegio, "20000003", {"cuaderno": "editar"})
    hd = auth("alfa", token(client, "alfa", "20000003"))
    assert [p["nombre"] for p in client.get("/api/configuracion/plantillas", headers=hd).json()] == ["Reunión"]
    assert client.post("/api/configuracion/plantillas", headers=hd,
                       json={"nombre": "X", "titulo": "X"}).status_code == 403
    crear_personal(db, e.colegio, "20000004", {"asistencia": "ver"})
    hx = auth("alfa", token(client, "alfa", "20000004"))
    assert client.get("/api/configuracion/plantillas", headers=hx).status_code == 403
    # Beta no las ve ni las toca.
    assert client.get("/api/configuracion/plantillas", headers=hb).json() == []
    assert client.put(f"/api/configuracion/plantillas/{pid}", headers=hb,
                      json={"nombre": "Mía", "titulo": "Mía"}).status_code == 404
    assert client.delete(f"/api/configuracion/plantillas/{pid}", headers=hb).status_code == 404
    r = client.put(f"/api/configuracion/plantillas/{pid}", headers=h,
                   json={"nombre": "Reunión general", "titulo": "Reunión", "cuerpo": "Sábado"})
    assert r.json()["nombre"] == "Reunión general"
    assert client.delete(f"/api/configuracion/plantillas/{pid}", headers=h).status_code == 204
    assert db.scalar(select(func.count()).select_from(PlantillaComunicado)) == 0


# --- Categorías de incidencias ---------------------------------------------------------------

def test_colegio_nuevo_trae_categorias_por_defecto(client, db, hp):
    r = client.post("/plataforma/colegios", headers=hp, json={
        "nombre": "Colegio Gamma", "subdominio": "gamma",
        "administrador": {"numero_documento": "40000001", "nombres": "Ana", "apellidos": "Ramos"}})
    assert r.status_code == 201, r.text
    cats = db.scalars(select(CategoriaIncidencia).where(CategoriaIncidencia.colegio_id == r.json()["colegio"]["id"])).all()
    assert {c.tipo for c in cats} == {"merito", "mejora"}
    assert {c.nombre for c in cats} == {n for n, _ in configuracion.CATEGORIAS_POR_DEFECTO}


def test_incidencia_con_categoria_y_la_familia_ve_el_merito(client, db, e, b, h, hf):
    merito = _categoria(db, e.colegio, "Participación", "merito")
    _categoria(db, e.colegio, "Conducta", "mejora")
    ajena = _categoria(db, b.colegio, "Ajena", "merito")
    base = {"tipo": "incidencia", "alcance": "alumno", "alumno_id": e.a1.id, "titulo": "Excelente exposición"}
    assert escribir(client, h, **base).status_code == 422  # el colegio tiene categorías: se elige una
    assert escribir(client, h, **base, categoria_id=ajena.id).status_code == 422
    r = escribir(client, h, **base, categoria_id=merito.id)
    assert r.status_code == 201, r.text
    entrada = next(x for x in client.get("/api/familia/cuaderno", headers=hf).json()["entradas"]
                   if x["id"] == r.json()["id"])
    assert entrada["categoria"] == {"id": merito.id, "nombre": "Participación", "tipo": "merito"}
    # Una categoría desactivada no se elige; en uso, no se borra.
    client.put(f"/api/configuracion/categorias/{merito.id}", headers=h,
               json={"nombre": "Participación", "tipo": "merito", "activa": False})
    assert escribir(client, h, **base, categoria_id=merito.id).status_code == 422
    assert client.delete(f"/api/configuracion/categorias/{merito.id}", headers=h).status_code == 409
    usos = {c["nombre"]: c["usos"] for c in client.get("/api/configuracion/categorias", headers=h).json()}
    assert usos == {"Participación": 1, "Conducta": 0}


def test_categorias_aislamiento_y_permisos(client, db, e, b, h, hb):
    r = client.post("/api/configuracion/categorias", headers=h, json={"nombre": "Deportes", "tipo": "merito"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert client.post("/api/configuracion/categorias", headers=h,
                       json={"nombre": "Deportes", "tipo": "mejora"}).status_code == 409
    assert client.post("/api/configuracion/categorias", headers=h,
                       json={"nombre": "X", "tipo": "otro"}).status_code == 422
    assert client.get("/api/configuracion/categorias", headers=hb).json() == []
    assert client.put(f"/api/configuracion/categorias/{cid}", headers=hb,
                      json={"nombre": "Y", "tipo": "merito"}).status_code == 404
    assert client.delete(f"/api/configuracion/categorias/{cid}", headers=hb).status_code == 404
    crear_personal(db, e.colegio, "20000005", {"cuaderno": "editar"})
    hd = auth("alfa", token(client, "alfa", "20000005"))
    assert len(client.get("/api/configuracion/categorias", headers=hd).json()) == 1  # para elegirla
    assert client.post("/api/configuracion/categorias", headers=hd,
                       json={"nombre": "Z", "tipo": "merito"}).status_code == 403
    assert client.delete(f"/api/configuracion/categorias/{cid}", headers=h).status_code == 204


# --- Historial de actividad ------------------------------------------------------------------

def test_historial_solo_el_administrador_y_sin_datos_sensibles(client, db, e, b, h, hb, hf):
    # Personal nuevo y clave reiniciada: la clave temporal nunca va al historial.
    rol = client.post("/api/roles", headers=h, json={"nombre": "Docente", "permisos": {"cuaderno": "editar"}}).json()
    r = client.post("/api/personal", headers=h, json={"numero_documento": "30000001", "nombres": "Rosa",
                                                     "apellidos": "Díaz", "rol_id": rol["id"]})
    assert r.status_code == 201, r.text
    uid, claves = r.json()["personal"]["id"], [r.json()["clave_temporal"]]
    claves.append(client.post(f"/api/personal/{uid}/reiniciar-clave", headers=h).json()["clave_temporal"])
    # Licencia con motivo de salud: el motivo no se guarda en el historial.
    r = client.post("/api/asistencia/licencias", headers=h, json={
        "usuario_id": uid, "tipo": "salud", "desde": str(hoy()), "hasta": str(hoy()), "motivo": "Diagnóstico secreto"})
    assert r.status_code == 201, r.text
    # Justificación del padre, aprobada: el texto tampoco.
    r = client.post("/api/familia/cuaderno/justificaciones", headers=hf, data={"datos": json.dumps({
        "alumno_id": e.a1.id, "desde": str(hoy()), "motivo": "Texto privado de la familia"})})
    assert client.post(f"/api/cuaderno/entradas/{r.json()['id']}/resolver", headers=h,
                       json={"estado": "aprobada"}).status_code == 200
    # Invitación a un padre: ni el enlace ni el PIN.
    inv = client.post(f"/api/familias/apoderados/{e.padre.id}/invitacion", headers=h, json={})
    assert inv.status_code == 201, inv.text
    # Marcación manual.
    client.post("/api/asistencia/marcaciones", headers=h, json={"marcaciones": [
        {"id_cliente": uuid.uuid4().hex, "alumno_id": e.a1.id}]})

    hist = client.get("/api/configuracion/historial", headers=h)
    assert hist.status_code == 200, hist.text
    items = hist.json()["items"]
    texto = json.dumps(items, ensure_ascii=False)
    for secreto in (*claves, "Diagnóstico secreto", "Texto privado de la familia", inv.json()["token"], "PIN"):
        assert secreto not in texto, secreto
    que = {(i["modulo"], i["que"], i["accion"]) for i in items}
    assert {("roles", "rol", "crear"), ("personal", "personal", "crear"), ("asistencia", "licencia", "crear"),
            ("asistencia", "marcación manual", "crear"), ("familias", "invitación", "crear")} <= que
    assert any(i["modulo"] == "cuaderno" and i["accion"] == "editar" for i in items)  # justificación aprobada
    assert all(i["quien"] == "Dir alfa" for i in items)

    # Solo el administrador: ni con todos los permisos.
    crear_personal(db, e.colegio, "20000006", {m: "editar" for m in ("configuracion", "roles", "personal")})
    hx = auth("alfa", token(client, "alfa", "20000006"))
    assert client.get("/api/configuracion/historial", headers=hx).status_code == 403
    # Beta no ve nada de alfa.
    assert client.get("/api/configuracion/historial", headers=hb).json()["total"] == 0


def test_historial_filtros_y_paginas(client, db, e, h):
    administrador = db.scalar(select(Usuario).where(Usuario.colegio_id == e.colegio.id, Usuario.usuario == "10000000"))
    otro = crear_personal(db, e.colegio, "20000007")
    for i in range(55):
        configuracion.registrar(db, e.colegio.id, administrador, "crear", "padron", "alumno", i, f"Alumno {i}")
    configuracion.registrar(db, e.colegio.id, otro, "editar", "cuaderno", "comunicado", 1, "Comunicado «Hola»")
    viejo = RegistroActividad(colegio_id=e.colegio.id, quien="Sistema", accion="editar", modulo="configuracion",
                              que="perfil", resumen="Viejo", creado_en=datetime.now(UTC) - timedelta(days=40))
    db.add(viejo)
    db.commit()

    r = client.get("/api/configuracion/historial", headers=h).json()
    assert r["total"] == 57 and r["paginas"] == 3 and len(r["items"]) == 25
    assert r["items"][0]["resumen"] == "Comunicado «Hola»"  # lo último primero
    assert len(client.get("/api/configuracion/historial?pagina=3", headers=h).json()["items"]) == 7
    assert len(client.get("/api/configuracion/historial?por_pagina=50&pagina=2", headers=h).json()["items"]) == 7
    assert client.get("/api/configuracion/historial?por_pagina=101", headers=h).status_code == 422
    assert {p["id"] for p in r["personas"]} == {administrador.id, otro.id}
    assert {m["clave"] for m in r["modulos"]} == {"padron", "cuaderno", "configuracion"}
    assert client.get(f"/api/configuracion/historial?usuario_id={otro.id}", headers=h).json()["total"] == 1
    assert client.get("/api/configuracion/historial?modulo=padron", headers=h).json()["total"] == 55
    desde = hoy() - timedelta(days=7)
    assert client.get(f"/api/configuracion/historial?desde={desde}", headers=h).json()["total"] == 56
    hasta = hoy() - timedelta(days=30)
    assert client.get(f"/api/configuracion/historial?hasta={hasta}", headers=h).json()["total"] == 1


def test_cambios_de_configuracion_quedan_en_el_historial(client, db, e, h):
    client.put("/api/configuracion/perfil", headers=h, json={"tipo_gestion": "estatal", "ugel": "UGEL 05"})
    client.put("/api/configuracion/modulos", headers=h, json={"activos": ["asistencia", "familias", "reuniones"]})
    client.put("/api/configuracion/avisos", headers=h,
               json={"tipos": {"salida": False}, "silencio_desde": "22:00", "silencio_hasta": "06:00"})
    client.put("/api/colegio/imagen", headers=h, json={"color_primario": "#112233", "color_secundario": "#445566"})
    resumenes = [i["resumen"] for i in client.get("/api/configuracion/historial", headers=h).json()["items"]]
    assert any("UGEL" in r and "tipo de gestión" in r and "UGEL 05" not in r for r in resumenes)
    assert any("apagó Cuaderno" in r or "apagó" in r for r in resumenes)
    assert any("salida" in r and "22:00" in r for r in resumenes)
    assert any("#112233" in r for r in resumenes)


# --- Pasar de prueba a activo ------------------------------------------------------------------

def test_toda_tabla_del_colegio_esta_clasificada_para_la_activacion():
    tablas = activacion.tablas_del_colegio()
    assert activacion.BORRAR | activacion.CONSERVAR == tablas
    assert not activacion.BORRAR & activacion.CONSERVAR


def _en_prueba(db, colegio):
    colegio.estado, colegio.vence_en = "prueba", hoy() + timedelta(days=15)
    db.commit()


def _conteo(db, modelo, colegio) -> int:
    return db.scalar(select(func.count()).select_from(modelo).where(modelo.colegio_id == colegio.id))


def test_activar_borra_solo_los_datos_de_ejemplo_de_ese_colegio(client, db, e, b, h, hp):
    _en_prueba(db, e.colegio)
    _en_prueba(db, b.colegio)
    client.post("/api/asistencia/marcaciones", headers=h, json={"marcaciones": [
        {"id_cliente": uuid.uuid4().hex, "alumno_id": e.a1.id}]})
    escribir(client, h, tipo="comunicado", alcance="colegio")
    _categoria(db, e.colegio)
    for hh in (h,):
        client.post("/api/configuracion/plantillas", headers=hh, json={"nombre": "P", "titulo": "T"})
    cuentas_antes = db.scalar(select(func.count()).select_from(CuentaFamilia))
    antes_beta = {m: _conteo(db, m, b.colegio) for m in (Alumno, Apoderado, EntradaCuaderno, ColaAviso)}

    assert client.post(f"/plataforma/colegios/{e.colegio.id}/activar", headers=hp,
                       json={"borrar_ejemplo": True, "confirmar": "beta"}).status_code == 422
    r = client.post(f"/plataforma/colegios/{e.colegio.id}/activar", headers=hp,
                    json={"borrar_ejemplo": True, "confirmar": " Alfa "})
    assert r.status_code == 200, r.text
    assert r.json()["colegio"]["estado"] == "activo" and r.json()["colegio"]["vence_en"] is None
    assert r.json()["borrados"]["alumno"] == 3

    db.expire_all()
    # Alfa: se fueron los datos de ejemplo…
    for modelo in (Alumno, Apoderado, AlumnoApoderado, Marcacion, AsistenciaAlumno, EntradaCuaderno, ColaAviso):
        assert _conteo(db, modelo, e.colegio) == 0, modelo.__name__
    # …y se quedó lo del colegio.
    for modelo in (Nivel, Grado, Seccion, Turno, Rol, Usuario, CategoriaIncidencia, PlantillaComunicado,
                   RegistroActividad):
        assert _conteo(db, modelo, e.colegio) > 0, modelo.__name__
    # La madre tenía cuenta solo por alfa: su cuenta global se va; el resto, no.
    assert db.scalar(select(func.count()).select_from(CuentaFamilia)) == cuentas_antes - 2
    # Beta, intacto (y sigue en prueba).
    assert {m: _conteo(db, m, b.colegio) for m in antes_beta} == antes_beta
    assert db.get(Colegio, b.colegio.id).estado == "prueba"
    # El administrador sigue entrando.
    assert client.get("/api/configuracion/perfil", headers=h).status_code == 200


def test_activar_sin_borrar_conserva_todo(client, db, e, hp):
    _en_prueba(db, e.colegio)
    r = client.post(f"/plataforma/colegios/{e.colegio.id}/activar", headers=hp,
                    json={"borrar_ejemplo": False, "confirmar": "alfa"})
    assert r.status_code == 200 and r.json()["borrados"] == {}
    db.expire_all()
    assert _conteo(db, Alumno, e.colegio) == 3
    assert db.get(Colegio, e.colegio.id).estado == "activo"


def test_activar_solo_colegios_en_prueba_y_nunca_la_demo(client, db, e, hp):
    assert client.post(f"/plataforma/colegios/{e.colegio.id}/activar", headers=hp,
                       json={"borrar_ejemplo": True, "confirmar": "alfa"}).status_code == 409  # ya activo
    demo = crear_colegio(db, "demo", es_demo=True, estado="prueba", vence_en=hoy() + timedelta(days=5))
    assert client.post(f"/plataforma/colegios/{demo.id}/activar", headers=hp,
                       json={"borrar_ejemplo": True, "confirmar": "demo"}).status_code == 409
    assert client.post("/plataforma/colegios/99999/activar", headers=hp,
                       json={"borrar_ejemplo": True, "confirmar": "x"}).status_code == 404
    # Desde un colegio no se llega.
    h = auth("alfa", token(client, "alfa"))
    assert client.post(f"/plataforma/colegios/{e.colegio.id}/activar", headers=h,
                       json={"borrar_ejemplo": True, "confirmar": "alfa"}).status_code in (401, 403)
