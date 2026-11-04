"""Familias: activación con enlace de un solo uso, PIN, cuenta global, aprobación,
bloqueo, passkeys, push y cola de avisos, cambios de celular. Y aislamiento entre colegios."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import asistencia, avisos
from app.codigos import contenido_qr
from app.models import (Apoderado, AsistenciaAlumno, CambioApoderado, ColaAviso, ConsentimientoApoderado,
                        CuentaFamilia, EntregaAviso, InvitacionFamilia, PasskeyFamilia, SuscripcionPush, Usuario)
from app.routers import familia as rutas_familia
from tests.conftest import PIN, auth, crear_colegio, crear_familia, host, token, token_familia
from tests.test_asistencia import LUNES, en, marcar, preparar
from tests.test_importacion import excel, fila, madre, subir
from tests.test_padron import armar



def apoderado_sin_cuenta(db, e, dni="41234567", alumnos=None, celular="987654321", recibe=True):
    from app.models import AlumnoApoderado
    ap = Apoderado(colegio_id=e.colegio.id, numero_documento=dni, nombres="Rosa", apellidos="Mamani", celular=celular)
    db.add(ap)
    db.flush()
    for a in alumnos if alumnos is not None else e.alumnos[:1]:
        db.add(AlumnoApoderado(colegio_id=e.colegio.id, alumno_id=a.id, apoderado_id=ap.id, parentesco="Madre",
                               recibe_avisos=recibe))
    db.commit()
    return ap


def invitar(client, sub, ap_id, **datos):
    r = client.post(f"/api/familias/apoderados/{ap_id}/invitacion", headers=auth(sub, token(client, sub)), json=datos)
    assert r.status_code == 201, r.text
    return r.json()["token"]


def enlace(tok, alumno, apoderado="41234567", **extra):
    return {"token": tok, "documento_alumno": alumno.numero_documento, "documento_apoderado": apoderado, **extra}


def activar(client, sub, tok, alumno, **extra):
    datos = enlace(tok, alumno, **({"acepto": True, "pin": PIN} | extra))
    return client.post("/api/familia/activacion/completar", headers=host(sub), json=datos)


def fam(sub, tok):
    return auth(sub, tok)


def pronto(minutos=1):
    """La cola guarda la hora real en que se encoló: el proceso corre "un poco después"."""
    return datetime.now(UTC) + timedelta(minutes=minutos)


# --- Activación -------------------------------------------------------------------

def test_activacion_completa_con_consentimiento(client, db):
    e = preparar(db, "alfa")
    ap = apoderado_sin_cuenta(db, e)
    tok = invitar(client, "alfa", ap.id)
    r = client.post("/api/familia/activacion/revisar", headers=host("alfa"), json=enlace(tok, e.alumnos[0]))
    assert r.status_code == 200
    assert r.json()["pide_pin_actual"] is False and "Ley 29733" in r.json()["consentimiento"]["texto"]
    assert "Colegio alfa" in r.json()["consentimiento"]["texto"]
    assert activar(client, "alfa", tok, e.alumnos[0], acepto=False).status_code == 422
    assert activar(client, "alfa", tok, e.alumnos[0], pin="111111").status_code == 422
    assert activar(client, "alfa", tok, e.alumnos[0], pin="123456").status_code == 422
    r = activar(client, "alfa", tok, e.alumnos[0])
    assert r.status_code == 200 and r.json()["estado"] == "activo"
    db.expire_all()
    c = db.scalar(select(ConsentimientoApoderado))
    assert c.apoderado_id == ap.id and c.version and c.aceptado_en is not None
    assert db.get(Apoderado, ap.id).activado_en is not None
    yo = client.get("/api/familia/yo", headers=fam("alfa", r.json()["token"])).json()
    assert yo["nombres"] == "Rosa" and yo["estado"] == "activo"
    # Un solo uso.
    r = client.post("/api/familia/activacion/revisar", headers=host("alfa"), json=enlace(tok, e.alumnos[0]))
    assert r.status_code == 410 and "ya se usó" in r.json()["detail"]
    # Y ahora entra con documento y PIN.
    assert client.post("/api/familia/ingreso", headers=host("alfa"),
                       json={"documento": "41234567", "pin": PIN}).status_code == 200
    assert client.post("/api/familia/ingreso", headers=host("alfa"),
                       json={"documento": "41234567", "pin": "000001"}).status_code == 401


def test_enlace_se_bloquea_tras_cinco_intentos(client, db):
    e = preparar(db, "alfa")
    ap = apoderado_sin_cuenta(db, e)
    tok = invitar(client, "alfa", ap.id)
    for quedan in (4, 3, 2, 1):
        r = client.post("/api/familia/activacion/revisar", headers=host("alfa"),
                        json=enlace(tok, e.alumnos[0], apoderado="49999999"))
        assert r.status_code == 400 and str(quedan) in r.json()["detail"]
    r = client.post("/api/familia/activacion/revisar", headers=host("alfa"), json=enlace(tok, e.alumnos[1]))
    assert r.status_code == 410  # el hijo equivocado también cuenta
    assert activar(client, "alfa", tok, e.alumnos[0]).status_code == 410  # ya ni con los datos correctos
    assert db.scalar(select(Apoderado.estado_acceso).where(Apoderado.id == ap.id)) == "sin_cuenta"


def test_enlace_vencido_o_reemplazado(client, db):
    e = preparar(db, "alfa")
    ap = apoderado_sin_cuenta(db, e)
    viejo = invitar(client, "alfa", ap.id)
    nuevo = invitar(client, "alfa", ap.id)
    r = activar(client, "alfa", viejo, e.alumnos[0])
    assert r.status_code == 410 and "ya no es válido" in r.json()["detail"]
    inv = db.scalar(select(InvitacionFamilia).where(InvitacionFamilia.anulada_en.is_(None)))
    inv.vence_en = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    r = activar(client, "alfa", nuevo, e.alumnos[0])
    assert r.status_code == 410 and "venció" in r.json()["detail"]
    assert activar(client, "alfa", "x" * 43, e.alumnos[0]).status_code == 404


def test_el_enlace_solo_activa_a_ese_apoderado(client, db):
    e = preparar(db, "alfa")
    madre_ = apoderado_sin_cuenta(db, e, dni="41234567")
    apoderado_sin_cuenta(db, e, dni="42222222")  # el padre, del mismo hijo
    tok = invitar(client, "alfa", madre_.id)
    r = activar(client, "alfa", tok, e.alumnos[0], documento_apoderado="42222222")
    assert r.status_code == 400
    assert db.scalar(select(CuentaFamilia)) is None


def test_activacion_con_aprobacion(client, db):
    e = preparar(db, "alfa")
    ap = apoderado_sin_cuenta(db, e)
    h = auth("alfa", token(client, "alfa"))
    assert client.put("/api/familias/configuracion", headers=h, json={"activacion": "aprobacion"}).status_code == 200
    r = activar(client, "alfa", invitar(client, "alfa", ap.id), e.alumnos[0])
    assert r.json()["estado"] == "pendiente"
    hf = fam("alfa", r.json()["token"])
    hijos = client.get("/api/familia/hijos", headers=hf).json()
    assert hijos["hijos"] == [] and hijos["pendientes_aprobacion"] == ["Colegio alfa"]
    assert client.post(f"/api/familias/apoderados/{ap.id}/aprobar", headers=h).json()["estado"] == "activo"
    assert [x["nombres"] for x in client.get("/api/familia/hijos", headers=hf).json()["hijos"]] == ["Niño0"]
    assert client.post(f"/api/familias/apoderados/{ap.id}/aprobar", headers=h).status_code == 409


def test_cuenta_global_une_hijos_de_dos_colegios(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    crear_familia(db, a.colegio, alumnos=a.alumnos[:1])
    ap_b = apoderado_sin_cuenta(db, b)
    tok = invitar(client, "beta", ap_b.id)
    r = client.post("/api/familia/activacion/revisar", headers=host("beta"), json=enlace(tok, b.alumnos[0]))
    assert r.json()["pide_pin_actual"] is True
    # Ya tiene cuenta: tiene que demostrarlo con su PIN, no puede poner otro.
    r = activar(client, "beta", tok, b.alumnos[0], pin_actual="000001", pin="777333")
    assert r.status_code == 400
    assert activar(client, "beta", tok, b.alumnos[0], pin_actual=PIN).status_code == 200
    assert db.scalar(select(CuentaFamilia.id).where(CuentaFamilia.numero_documento == "41234567")) is not None
    assert len(db.scalars(select(CuentaFamilia)).all()) == 1
    hf = fam("alfa", token_familia(client, "alfa"))
    hijos = client.get("/api/familia/hijos", headers=hf).json()["hijos"]
    assert sorted(x["colegio"] for x in hijos) == ["Colegio alfa", "Colegio beta"]
    # beta lo bloquea: desde alfa ya no ve al hijo de beta, y en beta no puede entrar.
    client.post(f"/api/familias/apoderados/{ap_b.id}/bloquear", headers=auth("beta", token(client, "beta")))
    assert [x["colegio"] for x in client.get("/api/familia/hijos", headers=hf).json()["hijos"]] == ["Colegio alfa"]
    r = client.post("/api/familia/ingreso", headers=host("beta"), json={"documento": "41234567", "pin": PIN})
    assert r.status_code == 403 and "bloqueado" in r.json()["detail"]


def test_cuenta_de_otro_colegio_no_entra_sin_activar_aqui(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    crear_familia(db, a.colegio, alumnos=a.alumnos[:1])
    apoderado_sin_cuenta(db, b)  # existe en beta pero no activó ahí
    r = client.post("/api/familia/ingreso", headers=host("beta"), json={"documento": "41234567", "pin": PIN})
    assert r.status_code == 403 and "aún no está activada" in r.json()["detail"]


def test_pin_olvidado_con_enlace_de_nuevo_pin(client, db):
    e = preparar(db, "alfa")
    ap = crear_familia(db, e.colegio, alumnos=e.alumnos[:1])
    viejo = token_familia(client, "alfa")
    tok = invitar(client, "alfa", ap.id, nuevo_pin=True)
    r = client.post("/api/familia/activacion/revisar", headers=host("alfa"), json=enlace(tok, e.alumnos[0]))
    assert r.json()["pide_pin_actual"] is False
    assert activar(client, "alfa", tok, e.alumnos[0], pin="502817").status_code == 200
    assert client.get("/api/familia/yo", headers=fam("alfa", viejo)).status_code == 401  # sesiones cerradas
    assert token_familia(client, "alfa", pin="502817")


def test_pin_nuevo_en_otro_colegio_deja_pendiente_y_avisa(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    ap_a = crear_familia(db, a.colegio, alumnos=a.alumnos[:1])
    ap_b = crear_familia(db, b.colegio, alumnos=b.alumnos[:1])
    suscribir(client, "alfa", endpoint="https://push.example/celular")
    tok = invitar(client, "beta", ap_b.id, nuevo_pin=True)
    assert activar(client, "beta", tok, b.alumnos[0], pin="502817").json()["estado"] == "activo"
    db.expire_all()
    assert db.get(Apoderado, ap_a.id).estado_acceso == "pendiente"
    cambio = db.scalar(select(CambioApoderado).where(CambioApoderado.colegio_id == a.colegio.id))
    assert (cambio.campo, cambio.antes, cambio.origen) == ("acceso", "activo", "familia")
    assert "Colegio beta" in cambio.despues
    # Con el PIN nuevo ve a su hijo de beta, pero no al de alfa.
    hf = fam("beta", token_familia(client, "beta", pin="502817"))
    hijos = client.get("/api/familia/hijos", headers=hf).json()
    assert [h["colegio"] for h in hijos["hijos"]] == ["Colegio beta"]
    assert hijos["pendientes_aprobacion"] == ["Colegio alfa"]
    # Los avisos de asistencia de alfa ya no le salen; el del PIN sí, a todos sus celulares.
    marcar(db, a, en(LUNES, 7, 40))
    push = Push()
    avisos.procesar_cola(db, push, ahora=pronto())
    assert len(push.enviados) == 1
    endpoint, m = push.enviados[0]
    assert endpoint == "https://push.example/celular" and m["titulo"] == "Colegio beta"
    assert "PIN nuevo" in m["cuerpo"] and "En Colegio alfa tu acceso queda pendiente" in m["cuerpo"]
    # Alfa lo aprueba y vuelve a verlo todo.
    client.post(f"/api/familias/apoderados/{ap_a.id}/aprobar", headers=auth("alfa", token(client, "alfa")))
    hijos = client.get("/api/familia/hijos", headers=hf).json()["hijos"]
    assert sorted(h["colegio"] for h in hijos) == ["Colegio alfa", "Colegio beta"]


def test_pendiente_por_pin_nuevo_vuelve_con_enlace_de_su_colegio(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    ap_a = crear_familia(db, a.colegio, alumnos=a.alumnos[:1])
    ap_b = crear_familia(db, b.colegio, alumnos=b.alumnos[:1])
    # Aunque alfa pida aprobación, a quien ya aprobó lo reactiva su propio enlace.
    client.put("/api/familias/configuracion", headers=auth("alfa", token(client, "alfa")),
               json={"activacion": "aprobacion"})
    activar(client, "beta", invitar(client, "beta", ap_b.id, nuevo_pin=True), b.alumnos[0], pin="502817")
    r = activar(client, "alfa", invitar(client, "alfa", ap_a.id), a.alumnos[0], pin_actual="502817")
    assert r.status_code == 200 and r.json()["estado"] == "activo"


def bloquear_pin(client, sub="alfa", veces=10, dni="41234567"):
    from app.proteccion import limpiar_limites
    respuestas = []
    for _ in range(veces):
        limpiar_limites()  # el límite por cuenta (5 cada 15 min) no es lo que se prueba aquí
        respuestas.append(client.post("/api/familia/ingreso", headers=host(sub),
                                      json={"documento": dni, "pin": "000001"}))
    return respuestas


def test_pin_se_bloquea_un_dia_tras_diez_fallidos(client, db, monkeypatch):
    from app.proteccion import limpiar_limites
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    crear_familia(db, a.colegio, alumnos=a.alumnos[:1])
    crear_familia(db, b.colegio, alumnos=b.alumnos[:1])
    suscribir(client, "alfa")
    # Se acumulan en el documento, intente donde intente.
    assert {r.status_code for r in bloquear_pin(client, "beta", 6)} == {401}
    respuestas = bloquear_pin(client, "alfa", 4)
    assert [r.status_code for r in respuestas] == [401, 401, 401, 429]
    assert "bloqueado hasta" in respuestas[-1].json()["detail"] and "huella" in respuestas[-1].json()["detail"]
    limpiar_limites()  # el bloqueo del PIN no depende del límite de intentos
    r = client.post("/api/familia/ingreso", headers=host("alfa"), json={"documento": "41234567", "pin": PIN})
    assert r.status_code == 429
    cuenta = db.scalar(select(CuentaFamilia))
    db.refresh(cuenta)
    assert cuenta.pin_bloqueado_hasta > datetime.now(UTC) + timedelta(hours=23)
    # Tampoco sirve el PIN para activar en otro colegio.
    otro = preparar(db, "gama")
    ap_g = apoderado_sin_cuenta(db, otro)
    r = activar(client, "gama", invitar(client, "gama", ap_g.id), otro.alumnos[0], pin_actual=PIN)
    assert r.status_code == 429
    # Se le avisa por push (por el colegio donde se bloqueó).
    push = Push()
    avisos.procesar_cola(db, push, ahora=pronto())
    assert [m["titulo"] for _, m in push.enviados] == ["Colegio alfa"]
    assert "10 intentos fallidos" in push.enviados[0][1]["cuerpo"]
    # Con huella sí entra.
    db.add(PasskeyFamilia(cuenta_id=cuenta.id, credencial_id="Y3JlZC0x", clave_publica=b"llave",
                          rp_id="alfa.tikray.test"))
    db.commit()

    class Verificada:
        new_sign_count = 1

    monkeypatch.setattr(rutas_familia, "verify_authentication_response", lambda **kw: Verificada)
    origen = {**host("alfa"), "Origin": "https://alfa.tikray.test"}
    reto = client.post("/api/familia/passkey/opciones-ingreso", headers=origen).json()["reto"]
    assert client.post("/api/familia/passkey/ingreso", headers=origen,
                       json={"credencial": {"id": "Y3JlZC0x"}, "reto": reto}).status_code == 200
    # Pasado el día, el PIN vuelve a servir y el contador empieza de cero.
    cuenta.pin_bloqueado_hasta = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert token_familia(client, "alfa")
    db.refresh(cuenta)
    assert cuenta.pin_fallidos == 0


def test_pin_correcto_reinicia_la_cuenta_y_cambiar_pin_tambien_suma(client, db):
    e = preparar(db, "alfa")
    crear_familia(db, e.colegio, alumnos=e.alumnos[:1])
    bloquear_pin(client, veces=4)
    cuenta = db.scalar(select(CuentaFamilia))
    db.refresh(cuenta)
    assert cuenta.pin_fallidos == 4
    hf = fam("alfa", token_familia(client, "alfa"))
    db.refresh(cuenta)
    assert cuenta.pin_fallidos == 0
    assert client.put("/api/familia/pin", headers=hf,
                      json={"pin_actual": "000001", "pin_nuevo": "602914"}).status_code == 400
    db.refresh(cuenta)
    assert cuenta.pin_fallidos == 1


def test_enlace_de_nuevo_pin_quita_el_bloqueo(client, db):
    e = preparar(db, "alfa")
    ap = crear_familia(db, e.colegio, alumnos=e.alumnos[:1])
    bloquear_pin(client)
    activar(client, "alfa", invitar(client, "alfa", ap.id, nuevo_pin=True), e.alumnos[0], pin="502817")
    assert token_familia(client, "alfa", pin="502817")


def test_cerrar_sesiones_bloquear_y_desbloquear(client, db):
    e = preparar(db, "alfa")
    ap = crear_familia(db, e.colegio, alumnos=e.alumnos[:1])
    h = auth("alfa", token(client, "alfa"))
    tf = token_familia(client, "alfa")
    client.post(f"/api/familias/apoderados/{ap.id}/cerrar-sesiones", headers=h)
    assert client.get("/api/familia/yo", headers=fam("alfa", tf)).status_code == 401
    tf = token_familia(client, "alfa")
    client.post(f"/api/familias/apoderados/{ap.id}/bloquear", headers=h)
    assert client.get("/api/familia/yo", headers=fam("alfa", tf)).status_code == 401
    assert client.post(f"/api/familias/apoderados/{ap.id}/invitacion", headers=h, json={}).status_code == 409
    assert client.post(f"/api/familias/apoderados/{ap.id}/desbloquear", headers=h).json()["estado"] == "activo"
    assert token_familia(client, "alfa")


def test_cambiar_pin(client, db):
    e = preparar(db, "alfa")
    crear_familia(db, e.colegio, alumnos=e.alumnos[:1])
    hf = fam("alfa", token_familia(client, "alfa"))
    assert client.put("/api/familia/pin", headers=hf, json={"pin_actual": "000000", "pin_nuevo": "602914"}).status_code == 400
    r = client.put("/api/familia/pin", headers=hf, json={"pin_actual": PIN, "pin_nuevo": "602914"})
    assert r.status_code == 200
    assert client.get("/api/familia/yo", headers=hf).status_code == 401  # el token anterior ya no sirve
    assert client.get("/api/familia/yo", headers=fam("alfa", r.json()["token"])).status_code == 200


# --- Panel: aislamiento -------------------------------------------------------------

def test_panel_de_cuentas_aislado_entre_colegios(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    apoderado_sin_cuenta(db, a)
    ap_b = apoderado_sin_cuenta(db, b, dni="43333333")
    h = auth("alfa", token(client, "alfa"))
    lista = client.get("/api/familias/apoderados", headers=h).json()
    assert [(x["tipo_documento"], x["numero_documento"]) for x in lista["filas"]] == [("DNI", "41234567")]
    assert lista["total"] == 1 and lista["resumen"]["total"] == 1
    for accion in ("invitacion", "aprobar", "bloquear", "desbloquear", "cerrar-sesiones"):
        assert client.post(f"/api/familias/apoderados/{ap_b.id}/{accion}", headers=h, json={}).status_code == 404
    assert client.get(f"/api/familias/apoderados/{ap_b.id}", headers=h).status_code == 404
    # El enlace de beta no sirve en la dirección de alfa.
    tok_b = invitar(client, "beta", ap_b.id)
    assert activar(client, "alfa", tok_b, b.alumnos[0], documento_apoderado="43333333").status_code == 404
    assert activar(client, "beta", tok_b, b.alumnos[0], documento_apoderado="43333333").status_code == 200


def test_panel_requiere_permiso_de_familias(client, db):
    from tests.conftest import crear_personal
    e = preparar(db, "alfa")
    ap = apoderado_sin_cuenta(db, e)
    crear_personal(db, e.colegio, "20000000", {"familias": "ver"})
    h = auth("alfa", token(client, "alfa", "20000000"))
    assert client.get("/api/familias/apoderados", headers=h).status_code == 200
    assert client.post(f"/api/familias/apoderados/{ap.id}/invitacion", headers=h, json={}).status_code == 403
    assert client.put("/api/familias/configuracion", headers=h, json={"activacion": "aprobacion"}).status_code == 403


def test_estado_de_notificaciones_por_padre(client, db):
    e = preparar(db, "alfa", alumnos=3)
    apoderado_sin_cuenta(db, e, dni="41111111", alumnos=e.alumnos[:1])
    crear_familia(db, e.colegio, dni="42222222", alumnos=e.alumnos[1:2])
    crear_familia(db, e.colegio, dni="43333333", alumnos=e.alumnos[2:])
    hf = fam("alfa", token_familia(client, "alfa", dni="43333333"))
    client.post("/api/familia/push/suscripcion", headers=hf,
                json={"endpoint": "https://push.example/abc", "keys": {"p256dh": "x" * 20, "auth": "y" * 10}})
    h = auth("alfa", token(client, "alfa"))
    estados = {x["numero_documento"]: x["notificaciones"]
               for x in client.get("/api/familias/apoderados", headers=h).json()["filas"]}
    assert estados == {"41111111": "sin_app", "42222222": "sin_permiso", "43333333": "activas"}
    # Filtro por avisos y resumen de todo el colegio.
    for filtro, docs in (("activas", ["43333333"]), ("sin_permiso", ["42222222"]), ("sin_app", ["41111111"])):
        r = client.get(f"/api/familias/apoderados?avisos={filtro}", headers=h).json()
        assert [x["numero_documento"] for x in r["filas"]] == docs
        assert r["resumen"]["total"] == 3  # el resumen no depende del filtro


# --- Cola de avisos ------------------------------------------------------------------

class Push:
    """Enviador falso: guarda lo enviado y responde lo que se le indique por endpoint."""

    def __init__(self, respuestas=None):
        self.enviados, self.respuestas = [], respuestas or {}

    def __call__(self, sus, mensaje):
        self.enviados.append((sus.endpoint, mensaje))
        return self.respuestas.get(sus.endpoint, "ok")


def suscribir(client, sub, dni="41234567", endpoint="https://push.example/1"):
    hf = fam(sub, token_familia(client, sub, dni=dni))
    r = client.post("/api/familia/push/suscripcion", headers=hf,
                    json={"endpoint": endpoint, "keys": {"p256dh": "p" * 30, "auth": "a" * 12}})
    assert r.status_code == 201
    return hf


def test_aviso_de_ingreso_llega_a_quien_recibe_avisos(client, db):
    e = preparar(db, "alfa")
    crear_familia(db, e.colegio, dni="41234567", alumnos=e.alumnos[:1])
    otro = crear_familia(db, e.colegio, dni="42222222", alumnos=e.alumnos[:1])
    apoderado_sin_cuenta(db, e, dni="43333333")  # sin cuenta: no es destinatario
    otro_v = db.scalar(select(Apoderado).where(Apoderado.id == otro.id))
    from app.models import AlumnoApoderado
    db.get(AlumnoApoderado, (e.alumnos[0].id, otro_v.id)).recibe_avisos = False
    db.commit()
    hf = suscribir(client, "alfa")
    marcar(db, e, en(LUNES, 7, 40))
    push = Push()
    assert avisos.procesar_cola(db, push, ahora=pronto()) == 1
    assert [(ep, m["cuerpo"]) for ep, m in push.enviados] == [
        ("https://push.example/1", "Niño0 ingresó al colegio a las 07:40.")]
    assert db.scalar(select(ColaAviso.estado)) == "enviado"
    feed = client.get("/api/familia/avisos", headers=hf).json()
    assert feed[0]["cuerpo"] == "Niño0 ingresó al colegio a las 07:40." and feed[0]["estado"] == "enviado"


def test_aviso_sin_destinatarios_y_sin_notificaciones(client, db):
    e = preparar(db, "alfa", alumnos=2)
    crear_familia(db, e.colegio, alumnos=e.alumnos[1:])  # activa pero sin aceptar notificaciones
    marcar(db, e, en(LUNES, 7, 40), e.alumnos[0])
    marcar(db, e, en(LUNES, 7, 41), e.alumnos[1])
    avisos.procesar_cola(db, Push(), ahora=pronto())
    estados = dict(db.execute(select(ColaAviso.alumno_id, ColaAviso.estado)).all())
    assert estados == {e.alumnos[0].id: "sin_destinatarios", e.alumnos[1].id: "enviado"}
    assert db.scalar(select(EntregaAviso.estado)) == "sin_notificaciones"


def test_aviso_de_falta_solo_si_sigue_con_falta(client, db):
    e = preparar(db, "alfa", alumnos=2)
    for i, a in enumerate(e.alumnos):
        crear_familia(db, e.colegio, dni=f"4100000{i}", alumnos=[a])
        suscribir(client, "alfa", dni=f"4100000{i}", endpoint=f"https://push.example/{i}")
    asistencia.marcar_faltas(db, LUNES)
    db.commit()
    # Entre la falta y el envío, el primero llegó (p. ej. una marcación que se sincronizó tarde).
    fila_ = db.scalar(select(AsistenciaAlumno).where(AsistenciaAlumno.alumno_id == e.alumnos[0].id))
    fila_.estado = "tarde"
    db.commit()
    push = Push()
    avisos.procesar_cola(db, push, ahora=pronto())
    assert [ep for ep, _ in push.enviados] == ["https://push.example/1"]
    estados = {a: (s, d.get("motivo")) for a, s, d in db.execute(select(ColaAviso.alumno_id, ColaAviso.estado,
                                                                           ColaAviso.datos))}
    assert estados[e.alumnos[0].id] == ("descartado", "ya llegó")
    assert estados[e.alumnos[1].id] == ("enviado", None)


def test_reintento_sin_repetir_y_suscripcion_expirada(client, db):
    e = preparar(db, "alfa")
    crear_familia(db, e.colegio, dni="41234567", alumnos=e.alumnos[:1])
    crear_familia(db, e.colegio, dni="42222222", alumnos=e.alumnos[:1])
    suscribir(client, "alfa", dni="41234567", endpoint="https://push.example/madre")
    suscribir(client, "alfa", dni="42222222", endpoint="https://push.example/padre")
    suscribir(client, "alfa", dni="42222222", endpoint="https://push.example/padre-viejo")
    marcar(db, e, en(LUNES, 7, 40))
    push = Push({"https://push.example/madre": "error", "https://push.example/padre-viejo": "expirada"})
    avisos.procesar_cola(db, push, ahora=pronto())
    aviso = db.scalar(select(ColaAviso))
    assert aviso.estado == "pendiente" and aviso.intentos == 1 and aviso.procesar_desde > pronto()
    assert db.scalar(select(SuscripcionPush).where(SuscripcionPush.endpoint.contains("viejo"))) is None
    push2 = Push()
    avisos.procesar_cola(db, push2, ahora=pronto(10))
    assert [ep for ep, _ in push2.enviados] == ["https://push.example/madre"]  # al padre ya le llegó
    db.refresh(aviso)
    assert aviso.estado == "enviado"
    assert sorted(db.scalars(select(EntregaAviso.estado))) == ["enviado", "enviado"]


def test_aviso_viejo_se_descarta(client, db):
    e = preparar(db, "alfa")
    crear_familia(db, e.colegio, alumnos=e.alumnos[:1])
    suscribir(client, "alfa")
    marcar(db, e, en(LUNES, 7, 40))
    aviso = db.scalar(select(ColaAviso))
    aviso.creado_en = datetime.now(UTC) - timedelta(hours=7)
    db.commit()
    push = Push()
    avisos.procesar_cola(db, push, ahora=pronto())
    assert push.enviados == [] and db.scalar(select(ColaAviso.estado)) == "descartado"


def test_avisos_de_un_colegio_no_salen_a_familias_de_otro(client, db):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    crear_familia(db, b.colegio, dni="49999999", alumnos=b.alumnos[:1])
    suscribir(client, "beta", dni="49999999")
    marcar(db, a, en(LUNES, 7, 40))
    push = Push()
    avisos.procesar_cola(db, push, ahora=pronto())
    assert push.enviados == []
    assert db.scalar(select(EntregaAviso)) is None


# --- Tarjeta en vivo -------------------------------------------------------------------

def test_tarjeta_en_vivo_del_hijo(client, db):
    e = preparar(db, "alfa")
    crear_familia(db, e.colegio, alumnos=e.alumnos[:1])
    hf = fam("alfa", token_familia(client, "alfa"))
    tarjeta = client.get("/api/familia/hijos", headers=hf).json()["hijos"][0]
    assert tarjeta["estado"] is None and tarjeta["seccion"] == "1° A"
    hd = auth("alfa", token(client, "alfa"))
    client.post("/api/asistencia/marcaciones", headers=hd, json={"marcaciones": [
        {"id_cliente": "x" * 12, "codigo": contenido_qr(e.alumnos[0].codigo)}]})
    tarjeta = client.get("/api/familia/hijos", headers=hf).json()["hijos"][0]
    assert tarjeta["estado"] in ("presente", "tarde") and tarjeta["entrada"]


def test_familia_no_ve_hijos_ajenos(client, db):
    e = preparar(db, "alfa", alumnos=2)
    crear_familia(db, e.colegio, alumnos=e.alumnos[:1])
    hf = fam("alfa", token_familia(client, "alfa"))
    assert [x["alumno_id"] for x in client.get("/api/familia/hijos", headers=hf).json()["hijos"]] == [e.alumnos[0].id]


# --- Cambio de celular -----------------------------------------------------------------

def test_recarga_de_excel_que_cambia_el_celular(client, db):
    c = crear_colegio(db, "alfa")
    h, _ = armar(client)
    assert subir(client, h, excel([fila(apo1=madre(cel="987654321"))]), "confirmar").status_code == 200
    ap = db.scalar(select(Apoderado))
    cuenta = CuentaFamilia(tipo_documento="DNI", numero_documento=ap.numero_documento, pin_hash="x")
    db.add(cuenta)
    db.flush()
    ap.cuenta_id, ap.estado_acceso = cuenta.id, "activo"
    db.commit()
    invitar(client, "alfa", ap.id, nuevo_pin=True)  # un enlace pendiente, enviado al número viejo

    assert subir(client, h, excel([fila(apo1=madre(cel="912345678"))]), "confirmar").status_code == 200
    db.expire_all()
    assert db.get(Apoderado, ap.id).celular == "912345678"
    cambio = db.scalar(select(CambioApoderado))
    director = db.scalar(select(Usuario).where(Usuario.colegio_id == c.id))
    assert (cambio.campo, cambio.antes, cambio.despues, cambio.origen, cambio.cambiado_por_id) == (
        "celular", "987654321", "912345678", "excel", director.id)
    inv = db.scalar(select(InvitacionFamilia))
    assert inv.anulada_en is not None and inv.motivo_anulacion == "Cambió el celular del apoderado"
    aviso = db.scalar(select(ColaAviso).where(ColaAviso.tipo == "cuenta"))
    assert aviso.apoderado_id == ap.id and "*** *** 321" in aviso.datos["mensaje"]
    assert "*** *** 678" in aviso.datos["mensaje"]
    # Recargar el mismo archivo no vuelve a avisar.
    subir(client, h, excel([fila(apo1=madre(cel="912345678"))]), "confirmar")
    assert len(db.scalars(select(ColaAviso).where(ColaAviso.tipo == "cuenta")).all()) == 1
    # El detalle del panel muestra quién lo cambió.
    det = client.get(f"/api/familias/apoderados/{ap.id}", headers=h).json()
    assert det["cambios"][0]["por"] == "alfa, Dir" and det["cambios"][0]["origen"] == "excel"


def test_cambio_de_celular_sin_cuenta_no_avisa_pero_anula_el_enlace(client, db):
    e = preparar(db, "alfa")
    ap = apoderado_sin_cuenta(db, e)
    invitar(client, "alfa", ap.id)
    h = auth("alfa", token(client, "alfa"))
    r = client.put(f"/api/padron/apoderados/{ap.id}", headers=h, json={
        "numero_documento": "41234567", "nombres": "Rosa", "apellidos": "Mamani", "celular": "912345678"})
    assert r.status_code == 200
    assert db.scalar(select(InvitacionFamilia.motivo_anulacion)) == "Cambió el celular del apoderado"
    assert db.scalar(select(ColaAviso)) is None
    assert db.scalar(select(CambioApoderado.origen)) == "panel"


def test_no_se_cambia_el_documento_de_quien_ya_activo(client, db):
    e = preparar(db, "alfa")
    ap = crear_familia(db, e.colegio, alumnos=e.alumnos[:1])
    h = auth("alfa", token(client, "alfa"))
    r = client.put(f"/api/padron/apoderados/{ap.id}", headers=h, json={
        "numero_documento": "49999999", "nombres": "Rosa", "apellidos": "Mamani"})
    assert r.status_code == 409


def test_aviso_de_cuenta_llega_al_apoderado(client, db):
    e = preparar(db, "alfa")
    ap = crear_familia(db, e.colegio, alumnos=e.alumnos[:1])
    suscribir(client, "alfa")
    db.add(ColaAviso(colegio_id=e.colegio.id, tipo="cuenta", apoderado_id=ap.id, fecha=LUNES,
                     datos={"mensaje": "El celular registrado en el colegio cambió."}))
    db.commit()
    push = Push()
    avisos.procesar_cola(db, push)
    assert push.enviados[0][1]["cuerpo"] == "El celular registrado en el colegio cambió."


# --- Passkeys ----------------------------------------------------------------------

def test_passkey_atada_al_dominio_del_colegio(client, db, monkeypatch):
    a, b = preparar(db, "alfa"), preparar(db, "beta")
    crear_familia(db, a.colegio, alumnos=a.alumnos[:1])
    crear_familia(db, b.colegio, alumnos=b.alumnos[:1])
    origen_a = {"Origin": "https://alfa.tikray.test"}
    hf = {**fam("alfa", token_familia(client, "alfa")), **origen_a}
    # Sin Origin, o con el de otro sitio, no hay opciones.
    assert client.post("/api/familia/passkey/opciones-ingreso", headers=host("alfa")).status_code == 400
    assert client.post("/api/familia/passkey/opciones-ingreso",
                       headers={**host("alfa"), "Origin": "https://malo.com"}).status_code == 400
    op = client.post("/api/familia/passkey/opciones-registro", headers=hf).json()
    assert op["opciones"]["rp"]["id"] == "alfa.tikray.test"
    assert op["opciones"]["authenticatorSelection"]["userVerification"] == "required"

    class Verificada:
        credential_id, credential_public_key, sign_count, new_sign_count = b"cred-1", b"llave", 0, 1

    monkeypatch.setattr(rutas_familia, "verify_registration_response", lambda **kw: Verificada)
    monkeypatch.setattr(rutas_familia, "verify_authentication_response", lambda **kw: Verificada)
    assert client.post("/api/familia/passkey/registro", headers=hf,
                       json={"credencial": {}, "reto": op["reto"]}).status_code == 201
    assert db.scalar(select(PasskeyFamilia.rp_id)) == "alfa.tikray.test"
    assert client.post("/api/familia/passkey/registro", headers=hf,
                       json={"credencial": {}, "reto": op["reto"]}).status_code == 400
    assert client.get("/api/familia/yo", headers=hf).json()["tiene_passkey"] is True

    reto = client.post("/api/familia/passkey/opciones-ingreso", headers={**host("alfa"), **origen_a}).json()["reto"]
    credencial = {"id": "Y3JlZC0x"}  # base64url de "cred-1"
    r = client.post("/api/familia/passkey/ingreso", headers={**host("alfa"), **origen_a},
                    json={"credencial": credencial, "reto": reto})
    assert r.status_code == 200 and r.json()["token"]
    # Cada reto sirve una sola vez.
    r = client.post("/api/familia/passkey/ingreso", headers={**host("alfa"), **origen_a},
                    json={"credencial": credencial, "reto": reto})
    assert r.status_code == 400 and "ya se usó" in r.json()["detail"]
    # En beta (otro dominio) esa passkey no existe, aunque la persona también tenga acceso ahí.
    origen_b = {**host("beta"), "Origin": "https://beta.tikray.test"}
    reto_b = client.post("/api/familia/passkey/opciones-ingreso", headers=origen_b).json()["reto"]
    assert client.post("/api/familia/passkey/ingreso", headers=origen_b,
                       json={"credencial": credencial, "reto": reto_b}).status_code == 401
    # Un reto de alfa (sin usar) no sirve en beta.
    reto_a = client.post("/api/familia/passkey/opciones-ingreso", headers={**host("alfa"), **origen_a}).json()["reto"]
    r = client.post("/api/familia/passkey/ingreso", headers=origen_b, json={"credencial": credencial, "reto": reto_a})
    assert r.status_code == 400 and "venció" in r.json()["detail"]


def test_reto_de_registro_es_de_la_cuenta(client, db, monkeypatch):
    e = preparar(db, "alfa")
    crear_familia(db, e.colegio, dni="41111111", alumnos=e.alumnos[:1])
    crear_familia(db, e.colegio, dni="42222222", alumnos=e.alumnos[1:])
    origen = {"Origin": "https://alfa.tikray.test"}
    h1 = {**fam("alfa", token_familia(client, "alfa", dni="41111111")), **origen}
    h2 = {**fam("alfa", token_familia(client, "alfa", dni="42222222")), **origen}
    reto = client.post("/api/familia/passkey/opciones-registro", headers=h1).json()["reto"]
    monkeypatch.setattr(rutas_familia, "verify_registration_response", lambda **kw: pytest.fail("no debe llegar"))
    assert client.post("/api/familia/passkey/registro", headers=h2,
                       json={"credencial": {}, "reto": reto}).status_code == 400
