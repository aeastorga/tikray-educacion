"""Modo reunión: QR por aula con vigencia y límite de intentos, fichas pendientes hasta que el
tutor las aprueba, cambios resaltados, activación en el momento, quiosco, papel, quién faltó.
Y aislamiento entre colegios y entre secciones."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import reunion as reglas
from app.models import (AlumnoApoderado, Apoderado, CambioApoderado, ConfigFamilias, ConsentimientoApoderado,
                        FichaReunion, InvitacionFamilia, ReunionPadres)
from app.proteccion import FALLOS_IP
from tests.conftest import PIN, auth, crear_personal, host, token
from tests.test_cuaderno import Escuela, preparar


@pytest.fixture
def e(db) -> Escuela:
    return preparar(db, "alfa")


@pytest.fixture
def h(client, e) -> dict:
    return auth("alfa", token(client, "alfa"))


def tutor(client, db, e: Escuela, secciones, dni="50000000", sub="alfa") -> dict:
    """Docente con el módulo de reuniones que solo ve sus secciones."""
    from app.models import SeccionDocente

    u = crear_personal(db, e.colegio, dni, {"reuniones": "editar"})
    u.rol.solo_sus_secciones = True
    db.add_all([SeccionDocente(colegio_id=e.colegio.id, seccion_id=s.id, usuario_id=u.id) for s in secciones])
    db.commit()
    return auth(sub, token(client, sub, dni))


def abrir(client, hd, seccion, **extra) -> dict:
    r = client.post("/api/reuniones", json={"seccion_id": seccion.id, **extra}, headers=hd)
    assert r.status_code == 201, r.text
    return r.json()


def persona(dni="43333333", **extra) -> dict:
    return {"tipo_documento": "DNI", "numero_documento": dni, "nombres": "Juan", "apellidos": "Quispe",
            "celular": "912345678", "parentesco": "Padre", **extra}


def ficha(client, tok, alumno="70000000", sub="alfa", **extra):
    cuerpo = {"token": tok, "documento_alumno": alumno, "apoderado": persona(), "acepto": True, **extra}
    return client.post("/api/familia/reunion/ficha", json=cuerpo, headers=host(sub))


def detalle(client, hd, rid) -> dict:
    r = client.get(f"/api/reuniones/{rid}", headers=hd)
    assert r.status_code == 200, r.text
    return r.json()


# --- Flujo completo ---------------------------------------------------------------------------

def test_padre_llena_su_ficha_el_tutor_aprueba_y_activa_en_el_momento(client, db, e):
    hd = tutor(client, db, e, [e.sec_a])
    r = abrir(client, hd, e.sec_a, horas=2)
    assert r["estado"] == "abierta" and r["seccion"] == "1° A" and r["alumnos"] == 1

    info = client.post("/api/familia/reunion/abrir", json={"token": r["token"]}, headers=host("alfa")).json()
    assert info["seccion"] == "1° A" and "Ley 29733" in info["consentimiento"]["texto"]
    # Confirma el alumno sin revelar nada de los apoderados.
    a = client.post("/api/familia/reunion/alumno", json={"token": r["token"], "documento_alumno": "7000 0000"},
                    headers=host("alfa"))
    assert a.status_code == 200 and a.json() == {"alumno": "Niño0 A."}

    otro = persona("41234567", nombres="Rosa", apellidos="Mamani", celular="999888777", parentesco="Madre")
    f = ficha(client, r["token"], apoderado=persona(correo="juan@correo.pe"), otro=otro)
    assert f.status_code == 201, f.text
    codigo = f.json()["codigo"]
    estado = client.post("/api/familia/reunion/estado", json={"codigo": codigo}, headers=host("alfa")).json()
    assert estado["estado"] == "pendiente" and not estado["puede_activar"]
    # Nada entra al padrón todavía.
    db.expire_all()
    assert db.get(Apoderado, e.padre.id).celular is None

    # El tutor la ve con los cambios frente al padrón.
    fichas = detalle(client, hd, r["id"])["fichas"]
    assert len(fichas) == 1
    fi = fichas[0]
    assert fi["alumno"] == "Ape0, Niño0" and fi["origen"] == "celular"
    assert fi["apoderado"]["estado"] == "registrado"
    assert fi["apoderado"]["cambios"] == {"celular": [None, "912345678"], "correo": [None, "juan@correo.pe"]}
    assert fi["otro"]["estado"] == "registrado" and fi["otro"]["con_cuenta"]
    # La madre tiene cuenta propia: su celular distinto se muestra, pero no se aplicará.
    assert fi["otro"]["cambios"] == {} and fi["otro"]["sin_aplicar"] == {"celular": ["987654321", "999888777"]}
    assert fi["requiere_verificacion"]  # el padre cambia su celular

    ap = client.post(f"/api/reuniones/{r['id']}/fichas/{fi['id']}/aprobar", json={"activar": True, "dni_verificado": True}, headers=hd)
    assert ap.status_code == 200, ap.text
    ap = ap.json()
    assert ap["activacion"]["en_su_celular"] and ap["activacion"]["token"] is None
    # La madre tiene cuenta propia: su celular no lo cambia lo que escribió otro.
    assert any("Rosa" in n and "secretaría" in n for n in ap["notas"])
    db.expire_all()
    padre = db.get(Apoderado, e.padre.id)
    assert (padre.celular, padre.correo) == ("912345678", "juan@correo.pe")
    assert db.get(Apoderado, e.madre.id).celular == "987654321"
    assert {c.campo for c in db.scalars(select(CambioApoderado).where(CambioApoderado.origen == "reunion"))} == {
        "celular", "correo", "dni_verificado"}
    consentimiento = db.scalar(select(ConsentimientoApoderado).where(ConsentimientoApoderado.apoderado_id == padre.id))
    assert consentimiento is not None and consentimiento.version

    # En su celular: ya puede crear su PIN, y entra.
    estado = client.post("/api/familia/reunion/estado", json={"codigo": codigo}, headers=host("alfa")).json()
    assert estado["puede_activar"] and not estado["pide_pin_actual"]
    act = client.post("/api/familia/reunion/activar", json={"codigo": codigo, "pin": "271828"}, headers=host("alfa"))
    assert act.status_code == 200, act.text
    assert act.json()["estado"] == "activo"
    db.expire_all()
    assert db.get(Apoderado, e.padre.id).estado_acceso == "activo"
    # El código ya cumplió.
    assert client.post("/api/familia/reunion/estado", json={"codigo": codigo},
                       headers=host("alfa")).status_code == 404
    assert client.post("/api/familia/ingreso", json={"documento": "43333333", "pin": "271828"},
                       headers=host("alfa")).status_code == 200


def test_activacion_presencial_no_espera_otra_aprobacion(client, db, e, h):
    db.add(ConfigFamilias(colegio_id=e.colegio.id, activacion="aprobacion"))
    db.commit()
    r = abrir(client, h, e.sec_a)
    codigo = ficha(client, r["token"]).json()["codigo"]
    fid = detalle(client, h, r["id"])["fichas"][0]["id"]
    client.post(f"/api/reuniones/{r['id']}/fichas/{fid}/aprobar", json={"activar": True, "dni_verificado": True}, headers=h)
    act = client.post("/api/familia/reunion/activar", json={"codigo": codigo, "pin": "271828"}, headers=host("alfa"))
    assert act.json()["estado"] == "activo"


def test_padre_con_cuenta_en_otro_colegio_confirma_con_su_pin(client, db, e, h):
    r = abrir(client, h, e.sec_a)
    # La madre ya tiene cuenta: llena su propia ficha.
    codigo = ficha(client, r["token"], apoderado=persona("41234567", nombres="Rosa", apellidos="Mamani",
                                                         celular="987654321", parentesco="Madre")).json()["codigo"]
    fid = detalle(client, h, r["id"])["fichas"][0]["id"]
    db.query(Apoderado).filter(Apoderado.id == e.madre.id).update({"estado_acceso": "pendiente"})
    db.commit()
    res = client.post(f"/api/reuniones/{r['id']}/fichas/{fid}/aprobar", json={"activar": True}, headers=h).json()
    assert res["activacion"]["pide_pin_actual"]
    estado = client.post("/api/familia/reunion/estado", json={"codigo": codigo}, headers=host("alfa")).json()
    assert estado["pide_pin_actual"]
    mal = client.post("/api/familia/reunion/activar", json={"codigo": codigo, "pin_actual": "000111"},
                      headers=host("alfa"))
    assert mal.status_code == 400
    bien = client.post("/api/familia/reunion/activar", json={"codigo": codigo, "pin_actual": PIN},
                       headers=host("alfa"))
    assert bien.status_code == 200 and bien.json()["estado"] == "activo"


def test_apoderado_nuevo_se_crea_y_se_une_al_alumno_al_aprobar(client, db, e, h):
    r = abrir(client, h, e.sec_a)
    nuevo = persona("45555555", nombres="Lucía", apellidos="Torres", parentesco="Abuela")
    assert ficha(client, r["token"], apoderado=nuevo).status_code == 201
    fi = detalle(client, h, r["id"])["fichas"][0]
    assert fi["apoderado"]["estado"] == "nuevo"
    client.post(f"/api/reuniones/{r['id']}/fichas/{fi['id']}/aprobar", json={"dni_verificado": True}, headers=h)
    ap = db.scalar(select(Apoderado).where(Apoderado.numero_documento == "45555555"))
    assert ap.colegio_id == e.colegio.id and ap.estado_acceso == "sin_cuenta"
    vinculo = db.scalar(select(AlumnoApoderado).where(AlumnoApoderado.apoderado_id == ap.id))
    assert (vinculo.alumno_id, vinculo.parentesco) == (e.a1.id, "Abuela")


def test_rechazar_no_toca_el_padron(client, db, e, h):
    r = abrir(client, h, e.sec_a)
    codigo = ficha(client, r["token"], apoderado=persona("45555555")).json()["codigo"]
    fid = detalle(client, h, r["id"])["fichas"][0]["id"]
    res = client.post(f"/api/reuniones/{r['id']}/fichas/{fid}/rechazar", json={"motivo": "No es el apoderado"},
                      headers=h)
    assert res.status_code == 200
    assert db.scalar(select(Apoderado).where(Apoderado.numero_documento == "45555555")) is None
    estado = client.post("/api/familia/reunion/estado", json={"codigo": codigo}, headers=host("alfa")).json()
    assert estado == estado | {"estado": "rechazada", "motivo": "No es el apoderado", "puede_activar": False}
    assert client.post(f"/api/reuniones/{r['id']}/fichas/{fid}/aprobar", json={},
                       headers=h).status_code == 409


def test_reenviar_reemplaza_la_ficha_pendiente_y_hay_tope_por_alumno(client, db, e, h):
    r = abrir(client, h, e.sec_a)
    ficha(client, r["token"], apoderado=persona(celular="911111111"))
    ficha(client, r["token"], apoderado=persona(celular="922222222"))
    fichas = detalle(client, h, r["id"])["fichas"]
    assert len(fichas) == 1 and fichas[0]["datos"]["apoderado"]["celular"] == "922222222"
    assert fichas[0]["reenviada"]
    client.post(f"/api/reuniones/{r['id']}/fichas/{fichas[0]['id']}/aprobar", json={"dni_verificado": True}, headers=h)
    assert ficha(client, r["token"]).status_code == 409  # ya aprobada
    for dni in ("46000001", "46000002", "46000003"):
        assert ficha(client, r["token"], apoderado=persona(dni)).status_code == 201
    assert ficha(client, r["token"], apoderado=persona("46000004")).status_code == 409


def test_ficha_exige_consentimiento_y_celular(client, e, h):
    r = abrir(client, h, e.sec_a)
    assert ficha(client, r["token"], acepto=False).status_code == 422
    assert ficha(client, r["token"], apoderado=persona(celular=None)).status_code == 422
    assert ficha(client, r["token"], otro=persona()).status_code == 422  # mismo documento


# --- Contacto de quien tiene cuenta y DNI verificado en persona ------------------------------

def test_quien_llena_con_cuenta_no_cambia_su_contacto_desde_la_ficha(client, db, e, h):
    """La madre tiene cuenta activa: su propia ficha no le cambia el celular ni el correo (alguien con su
    DNI y el del hijo podría desviar sus avisos). Lo pide en persona en secretaría."""
    r = abrir(client, h, e.sec_a)
    ficha(client, r["token"], apoderado=persona("41234567", nombres="Rosa", apellidos="Mamani", celular="955000111",
                                                correo="nuevo@correo.pe", parentesco="Madre"))
    fi = detalle(client, h, r["id"])["fichas"][0]
    assert fi["apoderado"]["con_cuenta"] and fi["apoderado"]["cambios"] == {}
    assert fi["apoderado"]["sin_aplicar"] == {"celular": ["987654321", "955000111"], "correo": [None, "nuevo@correo.pe"]}
    # No suma apoderado ni cambia un celular que se vaya a aplicar: no exige verificar el DNI.
    assert not fi["requiere_verificacion"]
    res = client.post(f"/api/reuniones/{r['id']}/fichas/{fi['id']}/aprobar", json={}, headers=h)
    assert res.status_code == 200, res.text
    assert any("secretaría" in n for n in res.json()["notas"])
    db.expire_all()
    madre = db.get(Apoderado, e.madre.id)
    assert (madre.celular, madre.correo) == ("987654321", None)
    assert not db.scalars(select(CambioApoderado).where(CambioApoderado.apoderado_id == madre.id)).all()
    assert db.scalar(select(ConsentimientoApoderado).where(ConsentimientoApoderado.apoderado_id == madre.id))


@pytest.mark.parametrize("caso", ["nuevo", "nuevo_vinculo", "celular"])
def test_aprobar_exige_verificar_el_dni_y_lo_registra(client, db, e, h, caso):
    if caso == "nuevo":  # apoderado que no está en el padrón
        apoderado = persona("45555555", nombres="Lucía", apellidos="Torres", parentesco="Abuela")
    elif caso == "nuevo_vinculo":  # el del otro alumno (a3), ahora también de a1
        apoderado = persona("42222222", nombres="Rosa", apellidos="Mamani", celular="987654321")
    else:  # el padre, sin cuenta, cambia su celular
        apoderado = persona()
    r = abrir(client, h, e.sec_a)
    ficha(client, r["token"], apoderado=apoderado)
    fi = detalle(client, h, r["id"])["fichas"][0]
    assert fi["requiere_verificacion"]
    url = f"/api/reuniones/{r['id']}/fichas/{fi['id']}/aprobar"
    sin = client.post(url, json={"activar": True}, headers=h)
    assert sin.status_code == 422 and "Verifiqué su DNI en persona" in sin.json()["detail"]
    db.expire_all()
    assert db.get(FichaReunion, fi["id"]).estado == "pendiente"
    assert not db.scalars(select(CambioApoderado)).all()

    assert client.post(url, json={"dni_verificado": True}, headers=h).status_code == 200
    db.expire_all()
    f = db.get(FichaReunion, fi["id"])
    assert f.dni_verificado_por == "Dir alfa" and f.dni_verificado_en is not None
    assert f.dni_verificado_por_id is not None
    registro = db.scalar(select(CambioApoderado).where(CambioApoderado.apoderado_id == f.apoderado_id,
                                                       CambioApoderado.campo == "dni_verificado"))
    assert registro.despues == f"DNI visto en persona por Dir alfa (reunión #{r['id']})"
    assert registro.cambiado_por_id == f.dni_verificado_por_id
    # El tutor lo ve en la ficha revisada, y el colegio en el historial del apoderado.
    revisada = detalle(client, h, r["id"])["fichas"][0]
    assert revisada["dni_verificado_por"] == "Dir alfa" and revisada["dni_verificado_en"]
    historial = client.get(f"/api/familias/apoderados/{f.apoderado_id}", headers=h).json()["cambios"]
    assert any(c["campo"] == "dni_verificado" and c["por"] for c in historial)


def test_otro_apoderado_nuevo_tambien_exige_verificar(client, db, e, h):
    r = abrir(client, h, e.sec_a)
    # Quien llena no cambia nada (el padre, mismo celular que ya tenía: ninguno); el otro es nuevo.
    padre = persona(celular="912345678")
    db.get(Apoderado, e.padre.id).celular = "912345678"
    db.commit()
    ficha(client, r["token"], apoderado=padre, otro=persona("47777777", nombres="Ana", apellidos="Rojas",
                                                            parentesco="Tía"))
    fi = detalle(client, h, r["id"])["fichas"][0]
    assert fi["apoderado"]["cambios"] == {} and fi["otro"]["estado"] == "nuevo" and fi["requiere_verificacion"]
    url = f"/api/reuniones/{r['id']}/fichas/{fi['id']}/aprobar"
    assert client.post(url, json={}, headers=h).status_code == 422
    assert client.post(url, json={"dni_verificado": True}, headers=h).status_code == 200
    otra = db.scalar(select(Apoderado).where(Apoderado.numero_documento == "47777777"))
    assert db.scalar(select(CambioApoderado).where(CambioApoderado.apoderado_id == otra.id,
                                                   CambioApoderado.campo == "dni_verificado"))


def test_ficha_sin_cambios_de_riesgo_se_aprueba_sin_verificar(client, db, e, h):
    """Solo corrige el nombre: no suma apoderado ni cambia celular."""
    r = abrir(client, h, e.sec_a)
    db.get(Apoderado, e.padre.id).celular = "912345678"
    db.commit()
    ficha(client, r["token"], apoderado=persona(nombres="Juan Carlos"))
    fi = detalle(client, h, r["id"])["fichas"][0]
    assert fi["apoderado"]["cambios"] == {"nombres": ["Juan", "Juan Carlos"]} and not fi["requiere_verificacion"]
    assert client.post(f"/api/reuniones/{r['id']}/fichas/{fi['id']}/aprobar", json={}, headers=h).status_code == 200
    f = db.get(FichaReunion, fi["id"])
    assert f.dni_verificado_por is None and f.dni_verificado_en is None


def test_la_base_exige_verificacion_completa(db, e):
    r = ReunionPadres(colegio_id=e.colegio.id, seccion_id=e.sec_a.id, nonce="x",
                      vence_en=datetime.now(UTC) + timedelta(hours=1))
    db.add(r)
    db.commit()
    db.add(FichaReunion(colegio_id=e.colegio.id, reunion_id=r.id, alumno_id=e.a1.id, origen="papel", datos={},
                        documento="1", consentimiento_version="v", dni_verificado_por="Alguien"))
    with pytest.raises(IntegrityError):
        db.commit()


# --- Sin registro libre -----------------------------------------------------------------------

def test_qr_solo_sirve_para_alumnos_de_esa_aula(client, db, e, h):
    r = abrir(client, h, e.sec_a)
    # a2 es de 1° B, a3 de secundaria: con este QR no existen.
    for doc in ("70000001", "70000002", "99999999"):
        res = client.post("/api/familia/reunion/alumno", json={"token": r["token"], "documento_alumno": doc},
                          headers=host("alfa"))
        assert res.status_code == 400
        assert ficha(client, r["token"], alumno=doc).status_code == 400
    assert db.get(ReunionPadres, r["id"]).intentos_fallidos == 6
    assert not db.scalars(select(FichaReunion)).all()


def test_limite_de_intentos_por_celular_y_por_qr(client, db, e, h):
    r = abrir(client, h, e.sec_a)
    for _ in range(reglas.FALLOS_REUNION.maximo):
        client.post("/api/familia/reunion/alumno", json={"token": r["token"], "documento_alumno": "1"},
                    headers=host("alfa"))
    res = client.post("/api/familia/reunion/alumno", json={"token": r["token"], "documento_alumno": "70000000"},
                      headers=host("alfa"))
    assert res.status_code == 429
    reglas.FALLOS_REUNION.limpiar()
    # Tope del QR entero: queda bloqueado para todos.
    db.get(ReunionPadres, r["id"]).intentos_fallidos = reglas.tope_fallos(1)
    db.commit()
    assert client.post("/api/familia/reunion/abrir", json={"token": r["token"]},
                       headers=host("alfa")).status_code == 410
    assert detalle(client, h, r["id"])["estado"] == "bloqueada"
    # Un QR nuevo para la misma reunión: el viejo deja de servir.
    nuevo = client.post(f"/api/reuniones/{r['id']}/nuevo-qr", headers=h).json()
    assert nuevo["estado"] == "abierta" and nuevo["token"] != r["token"]
    assert client.post("/api/familia/reunion/abrir", json={"token": r["token"]},
                       headers=host("alfa")).status_code == 404
    assert ficha(client, nuevo["token"]).status_code == 201


def test_qr_vencido_cerrado_o_falso(client, db, e, h):
    r = abrir(client, h, e.sec_a)
    falso = r["token"][:-2] + ("AA" if not r["token"].endswith("AA") else "BB")
    for tok in (falso, f"{r['id']}000", "abc.def", f"{r['id'] + 1}.{r['token'].split('.')[1]}"):
        assert client.post("/api/familia/reunion/abrir", json={"token": tok}, headers=host("alfa")).status_code == 404
    reunion = db.get(ReunionPadres, r["id"])
    reunion.creado_en, reunion.vence_en = datetime.now(UTC) - timedelta(hours=3), datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert ficha(client, r["token"]).status_code == 410
    assert detalle(client, h, r["id"])["token"] is None
    otra = abrir(client, h, e.sec_a)
    client.post(f"/api/reuniones/{otra['id']}/cerrar", headers=h)
    assert ficha(client, otra["token"]).status_code == 410


def test_abrir_otra_reunion_en_la_seccion_cierra_la_anterior(client, db, e, h):
    r1, r2 = abrir(client, h, e.sec_a), abrir(client, h, e.sec_a)
    assert detalle(client, h, r1["id"])["estado"] == "cerrada"
    assert ficha(client, r1["token"]).status_code == 410
    assert ficha(client, r2["token"]).status_code == 201
    assert client.post("/api/reuniones", json={"seccion_id": e.sec_a.id, "horas": 9}, headers=h).status_code == 422


def test_codigo_del_celular_vence_despues_de_la_reunion(client, db, e, h):
    r = abrir(client, h, e.sec_a)
    codigo = ficha(client, r["token"]).json()["codigo"]
    reunion = db.get(ReunionPadres, r["id"])
    reunion.cerrada_en = datetime.now(UTC) - reglas.MARGEN_ACTIVACION - timedelta(minutes=1)
    db.commit()
    assert client.post("/api/familia/reunion/estado", json={"codigo": codigo}, headers=host("alfa")).status_code == 410


def test_codigo_falso_cuenta_como_intento(client, e, h):
    for _ in range(FALLOS_IP.maximo):
        client.post("/api/familia/reunion/estado", json={"codigo": "1.xxxxxxxxxxxxxxxx"}, headers=host("alfa"))
    r = client.post("/api/familia/reunion/estado", json={"codigo": "1.xxxxxxxxxxxxxxxx"}, headers=host("alfa"))
    assert r.status_code == 429


# --- Quiosco, papel y quién faltó ------------------------------------------------------------

def test_quiosco_no_guarda_codigo_y_el_tutor_da_el_enlace(client, db, e, h):
    r = abrir(client, h, e.sec_a)
    f = ficha(client, r["token"], quiosco=True)
    assert f.status_code == 201 and f.json()["codigo"] is None
    fi = detalle(client, h, r["id"])["fichas"][0]
    assert fi["origen"] == "quiosco"
    res = client.post(f"/api/reuniones/{r['id']}/fichas/{fi['id']}/aprobar", json={"activar": True, "dni_verificado": True}, headers=h).json()
    tok = res["activacion"]["token"]
    assert tok and not res["activacion"]["en_su_celular"] and res["activacion"]["celular"] == "912345678"
    # Con ese enlace activa como siempre (el tutor le muestra el QR o se lo manda por WhatsApp).
    act = client.post("/api/familia/activacion/completar", headers=host("alfa"), json={
        "token": tok, "documento_alumno": "70000000", "documento_apoderado": "43333333", "acepto": True,
        "pin": "271828"})
    assert act.status_code == 200 and act.json()["estado"] == "activo"
    assert detalle(client, h, r["id"])["fichas"][0]["cuenta"] == "activa"


def test_ficha_en_papel_y_pdf_prellenado(client, db, e, h):
    r = abrir(client, h, e.sec_a)
    res = client.post(f"/api/reuniones/{r['id']}/fichas", headers=h,
                      json={"alumno_id": e.a1.id, "apoderado": persona(), "acepto": True})
    assert res.status_code == 201, res.text
    assert detalle(client, h, r["id"])["fichas"][0]["origen"] == "papel"
    # Solo alumnos del aula.
    assert client.post(f"/api/reuniones/{r['id']}/fichas", headers=h,
                       json={"alumno_id": e.a2.id, "apoderado": persona(), "acepto": True}).status_code == 404
    p = client.get(f"/api/reuniones/secciones/{e.sec_a.id}/fichas.pdf", headers=h)
    assert p.status_code == 200 and p.content.startswith(b"%PDF")
    assert "fichas-1-a" in p.headers["content-disposition"]


def test_quien_falto_y_su_enlace_por_whatsapp(client, db, e, h):
    r = abrir(client, h, e.sec_b)  # 1° B: solo a2, de la madre (con cuenta activa)
    faltan = client.get(f"/api/reuniones/{r['id']}/ausentes", headers=h).json()
    assert [a["id"] for a in faltan] == [e.a2.id]
    assert [p["id"] for p in faltan[0]["apoderados"]] == [e.madre.id]
    assert client.post(f"/api/reuniones/{r['id']}/apoderados/{e.madre.id}/invitacion",
                       headers=h).status_code == 409  # ya activa

    r = abrir(client, h, e.sec_a)  # 1° A: a1, con madre y padre (sin cuenta)
    inv = client.post(f"/api/reuniones/{r['id']}/apoderados/{e.padre.id}/invitacion", headers=h)
    assert inv.status_code == 201 and inv.json()["token"]
    # El de otra aula no.
    assert client.post(f"/api/reuniones/{r['id']}/apoderados/{e.otro.id}/invitacion",
                       headers=h).status_code == 404
    ficha(client, r["token"])
    assert client.get(f"/api/reuniones/{r['id']}/ausentes", headers=h).json() == []


# --- Permisos y secciones ---------------------------------------------------------------------

def test_tutor_solo_sus_secciones(client, db, e, h):
    hd = tutor(client, db, e, [e.sec_a])
    assert [s["nombre"] for s in client.get("/api/reuniones/secciones", headers=hd).json()] == ["1° A"]
    assert client.post("/api/reuniones", json={"seccion_id": e.sec_b.id}, headers=hd).status_code == 404
    ajena = abrir(client, h, e.sec_b)
    for metodo, ruta in (("get", ""), ("post", "/cerrar"), ("post", "/nuevo-qr"), ("get", "/ausentes")):
        assert client.request(metodo, f"/api/reuniones/{ajena['id']}{ruta}", headers=hd).status_code == 404
    assert client.get(f"/api/reuniones/secciones/{e.sec_b.id}/fichas.pdf", headers=hd).status_code == 404
    assert [x["id"] for x in client.get("/api/reuniones", headers=hd).json()] == []
    # Sin el módulo: nada.
    crear_personal(db, e.colegio, "60000000", {"cuaderno": "editar"})
    hs = auth("alfa", token(client, "alfa", "60000000"))
    assert client.get("/api/reuniones/secciones", headers=hs).status_code == 403
    # Con solo "ver": mira pero no aprueba.
    crear_personal(db, e.colegio, "61000000", {"reuniones": "ver"})
    hv = auth("alfa", token(client, "alfa", "61000000"))
    assert client.get(f"/api/reuniones/{ajena['id']}", headers=hv).status_code == 200
    assert client.post("/api/reuniones", json={"seccion_id": e.sec_a.id}, headers=hv).status_code == 403


# --- Aislamiento entre colegios ---------------------------------------------------------------

def test_aislamiento_entre_colegios(client, db, e, h):
    otro = preparar(db, "beta", dni_madre="48888888", dni_otro="49999999")
    hb = auth("beta", token(client, "beta"))
    r = abrir(client, h, e.sec_a)
    codigo = ficha(client, r["token"]).json()["codigo"]
    fid = detalle(client, h, r["id"])["fichas"][0]["id"]

    # El QR de alfa no existe en beta (aunque el alumno tenga el mismo documento allá).
    assert client.post("/api/familia/reunion/abrir", json={"token": r["token"]}, headers=host("beta")).status_code == 404
    assert ficha(client, r["token"], sub="beta").status_code == 404
    assert client.post("/api/familia/reunion/estado", json={"codigo": codigo},
                       headers=host("beta")).status_code == 404
    # El personal de beta no ve ni toca la reunión de alfa.
    for metodo, ruta, cuerpo in (("get", "", None), ("post", "/cerrar", None), ("post", "/nuevo-qr", None),
                                 ("get", "/ausentes", None), ("post", f"/fichas/{fid}/aprobar", {}),
                                 ("post", f"/fichas/{fid}/rechazar", {"motivo": "x"}),
                                 ("post", f"/apoderados/{e.padre.id}/invitacion", None)):
        res = client.request(metodo, f"/api/reuniones/{r['id']}{ruta}", json=cuerpo, headers=hb)
        assert res.status_code == 404, (ruta, res.status_code)
    assert client.get("/api/reuniones", headers=hb).json() == []
    assert client.post("/api/reuniones", json={"seccion_id": e.sec_a.id}, headers=hb).status_code == 404
    assert client.get(f"/api/reuniones/secciones/{e.sec_a.id}/fichas.pdf", headers=hb).status_code == 404
    # Beta en su propia reunión no puede meter un alumno ni un apoderado de alfa.
    rb = abrir(client, hb, otro.sec_a)
    assert client.post(f"/api/reuniones/{rb['id']}/fichas", headers=hb,
                       json={"alumno_id": e.a1.id, "apoderado": persona(), "acepto": True}).status_code == 404
    assert client.post(f"/api/reuniones/{rb['id']}/apoderados/{e.padre.id}/invitacion",
                       headers=hb).status_code == 404
    assert db.get(FichaReunion, fid).estado == "pendiente"


def test_la_base_rechaza_mezclar_colegios(db, e):
    otro = preparar(db, "beta", dni_madre="48888888", dni_otro="49999999")
    r = ReunionPadres(colegio_id=e.colegio.id, seccion_id=e.sec_a.id, nonce="x", vence_en=datetime.now(UTC) + timedelta(hours=1))
    db.add(r)
    db.commit()
    casos = [
        ReunionPadres(colegio_id=otro.colegio.id, seccion_id=e.sec_a.id, nonce="x",
                      vence_en=datetime.now(UTC) + timedelta(hours=1)),
        FichaReunion(colegio_id=otro.colegio.id, reunion_id=r.id, alumno_id=otro.a1.id, origen="papel", datos={},
                     documento="1", consentimiento_version="v"),
        FichaReunion(colegio_id=e.colegio.id, reunion_id=r.id, alumno_id=otro.a1.id, origen="papel", datos={},
                     documento="1", consentimiento_version="v"),
        FichaReunion(colegio_id=e.colegio.id, reunion_id=r.id, alumno_id=e.a1.id, origen="papel", datos={},
                     documento="1", consentimiento_version="v", apoderado_id=otro.madre.id),
    ]
    inv = InvitacionFamilia(colegio_id=otro.colegio.id, apoderado_id=otro.madre.id, token_hash="h" * 64,
                            vence_en=datetime.now(UTC) + timedelta(days=1))
    db.add(inv)
    db.commit()
    casos.append(FichaReunion(colegio_id=e.colegio.id, reunion_id=r.id, alumno_id=e.a1.id, origen="papel", datos={},
                              documento="1", consentimiento_version="v", invitacion_id=inv.id))
    for caso in casos:
        db.add(caso)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    # Y una reunión no puede durar más de 12 horas.
    db.add(ReunionPadres(colegio_id=e.colegio.id, seccion_id=e.sec_a.id, nonce="x", creado_en=datetime.now(UTC),
                         vence_en=datetime.now(UTC) + timedelta(hours=13)))
    with pytest.raises(IntegrityError):
        db.commit()
