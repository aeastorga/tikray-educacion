"""Calendario escolar: eventos y a quién van, días sin clases (los de Estructura), qué ve cada familia, aviso al
publicar y recordatorio del día anterior (solo con "avisar", sin repetir, con el horario sin molestar), anular,
PDF del mes, permisos, módulo apagado, aislamiento y migración."""

import os
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select, text

from app import asistencia, avisos, calendario
from app.db import get_engine
from app.fechas import LIMA
from app.models import AsistenciaAlumno, ColaAviso, Colegio, DiaNoLectivo, EventoCalendario, RegistroActividad
from app.models.colegio import INCLUIDOS
from tests.conftest import auth, crear_familia, crear_personal, hoy, token, token_familia
from tests.test_familias import Push, suscribir
from tests.test_pensiones import preparar as preparar_escuela



def preparar(db, sub: str, otra: bool = False):
    """Tres alumnos: a1 (Primaria 1° A) y a2 (Primaria 2° A), hijos de la madre (con cuenta); a3 (Secundaria
    1° A), con `otra`, hijo de otra madre (con cuenta). Calendario contratado (la escuela contrata todo)."""
    e = preparar_escuela(db, sub)
    if otra:
        e.otra = crear_familia(db, e.colegio, "42222222", [e.a3])
    return e


def evento(client, h, titulo="Actuación", inicio: date | None = None, esperado=201, **extra) -> dict:
    datos = {"titulo": titulo, "inicio": (inicio or hoy() + timedelta(days=10)).isoformat(), "tipo": "actuacion",
             **extra}
    r = client.post("/api/calendario/eventos", headers=h, json=datos)
    assert r.status_code == esperado, r.text
    return r.json()


def titulos(r) -> list[str]:
    return [x["titulo"] for x in r.json()["eventos"]]


def mes_de(d: date) -> str:
    return d.strftime("%Y-%m")


def cola(db) -> list[ColaAviso]:
    db.expire_all()
    return list(db.scalars(select(ColaAviso).where(ColaAviso.tipo == "calendario").order_by(ColaAviso.id)))


def enviar(db, ahora: datetime | None = None) -> list[str]:
    push = Push()
    avisos.procesar_cola(db, push, ahora=ahora or datetime.now(UTC) + timedelta(seconds=5))
    return [m["cuerpo"] for _, m in push.enviados]


# --- Eventos -------------------------------------------------------------------------------------------

def test_crear_editar_y_ver_en_el_mes_con_a_quien_va(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    dia = hoy() + timedelta(days=10)
    a = evento(client, h, "Aniversario", dia, hora="10:00", descripcion="  En el patio.\nTraer uniforme.  ")
    assert (a["para"], a["hora"], a["descripcion"], a["fin"], a["tipo_nombre"], a["anulado"]) == (
        "Todo el colegio", "10:00", "En el patio.\nTraer uniforme.", dia.isoformat(), "Actuación", False)
    b = evento(client, h, "Exámenes", dia, fin=(dia + timedelta(days=3)).isoformat(), tipo="examen",
               alcance="niveles", niveles=[e.primaria.id, e.secundaria.id])
    assert b["para"] == "Primaria, Secundaria"
    c = evento(client, h, "Paseo", dia, tipo="salida", alcance="secciones", secciones=[e.s1.id])
    assert c["para"] == "Primaria · 1° A"
    r = client.get(f"/api/calendario/mes?mes={mes_de(dia)}", headers=h)
    assert set(titulos(r)) >= {"Aniversario", "Exámenes", "Paseo"}

    r = client.put(f"/api/calendario/eventos/{c['id']}", headers=h, json={
        "titulo": "Paseo al zoológico", "inicio": dia.isoformat(), "tipo": "salida", "alcance": "secciones",
        "secciones": [e.s1.id, e.s2.id]})
    assert r.status_code == 200, r.text
    assert r.json()["para"] == "Primaria · 1° A, Primaria · 2° A"
    # Cada cambio queda en el historial.
    resumenes = [x.resumen for x in db.scalars(select(RegistroActividad).where(RegistroActividad.modulo == "calendario"))]
    assert len(resumenes) == 4 and "Salida o paseo «Paseo al zoológico»" in resumenes[-1]

    # Reglas.
    evento(client, h, "x", dia, fin=(dia - timedelta(days=1)).isoformat(), esperado=422)
    evento(client, h, "x", dia, alcance="niveles", esperado=422)
    evento(client, h, "   ", dia, esperado=422)
    evento(client, h, "x", dia, tipo="cumpleaños", esperado=422)


def test_anular_queda_visible_y_no_se_edita(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    dia = hoy() + timedelta(days=5)
    x = evento(client, h, "Feria", dia)
    assert client.post(f"/api/calendario/eventos/{x['id']}/anular", headers=h, json={"motivo": " "}).status_code == 422
    r = client.post(f"/api/calendario/eventos/{x['id']}/anular", headers=h, json={"motivo": "Lluvia"})
    assert r.status_code == 200 and r.json()["anulado"] and r.json()["anulado_motivo"] == "Lluvia"
    assert client.post(f"/api/calendario/eventos/{x['id']}/anular", headers=h, json={"motivo": "x"}).status_code == 409
    assert client.put(f"/api/calendario/eventos/{x['id']}", headers=h, json={
        "titulo": "Feria", "inicio": dia.isoformat(), "tipo": "otro"}).status_code == 409
    mes = client.get(f"/api/calendario/mes?mes={mes_de(dia)}", headers=h).json()["eventos"]
    assert [(m["titulo"], m["anulado"], m["anulado_motivo"]) for m in mes] == [("Feria", True, "Lluvia")]
    # En la lista de próximos ya no está; la familia lo ve anulado en el mes.
    assert client.get("/api/calendario/proximos", headers=h).json()["eventos"] == []
    hf = auth("alfa", token_familia(client, "alfa"))
    fam = client.get(f"/api/familia/calendario/mes?mes={mes_de(dia)}", headers=hf).json()["eventos"]
    assert [(m["titulo"], m["anulado"]) for m in fam] == [("Feria", True)]
    assert db.scalar(select(RegistroActividad.resumen).where(RegistroActividad.accion == "anular")).endswith(": Lluvia")
    assert e


def test_secciones_de_otro_anio_o_colegio_no_se_aceptan(client, db):
    e = preparar(db, "alfa")
    otro = preparar(db, "beta")
    h = auth("alfa", token(client, "alfa"))
    evento(client, h, alcance="secciones", secciones=[otro.s1.id], esperado=422)
    evento(client, h, alcance="niveles", niveles=[otro.primaria.id], esperado=422)
    assert e


# --- Días sin clases ---------------------------------------------------------------------------------------

def test_dias_no_lectivos_en_el_calendario_y_siguen_evitando_faltas(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    feriado = hoy() + timedelta(days=3)
    r = client.post("/api/padron/dias-no-lectivos", headers=h, json={"desde": feriado.isoformat(),
                                                                       "motivo": "Feriado regional"})
    assert r.status_code in (200, 201), r.text
    mes = client.get(f"/api/calendario/mes?mes={mes_de(feriado)}", headers=h).json()
    assert {"fecha": feriado.isoformat(), "motivo": "Feriado regional"} in mes["sin_clases"]
    assert db.scalar(select(EventoCalendario.id)) is None  # no se crea otro registro
    hf = auth("alfa", token_familia(client, "alfa"))
    fam = client.get(f"/api/familia/calendario/mes?mes={mes_de(feriado)}", headers=hf).json()
    assert {"fecha": feriado.isoformat(), "motivo": "Feriado regional"} in fam["sin_clases"]
    assert feriado.isoformat() in [d["fecha"] for d in client.get("/api/familia/calendario/proximos",
                                                                    headers=hf).json()["sin_clases"]]
    # Un evento "feriado" del calendario no cambia la asistencia: solo los días no lectivos evitan faltas.
    evento(client, h, "Feriado", feriado + timedelta(days=1), tipo="feriado")
    asistencia.marcar_faltas(db, feriado, colegio_id=e.colegio.id)
    asistencia.marcar_faltas(db, feriado + timedelta(days=1), colegio_id=e.colegio.id)
    db.commit()
    fechas = set(db.scalars(select(AsistenciaAlumno.fecha).where(AsistenciaAlumno.colegio_id == e.colegio.id)))
    assert feriado not in fechas and feriado + timedelta(days=1) in fechas


# --- Familia ------------------------------------------------------------------------------------------------

def test_la_familia_solo_ve_lo_del_colegio_su_nivel_o_su_seccion(client, db):
    e = preparar(db, "alfa", otra=True)
    h = auth("alfa", token(client, "alfa"))
    dia = hoy() + timedelta(days=7)
    evento(client, h, "Todos", dia)
    evento(client, h, "Primaria", dia, alcance="niveles", niveles=[e.primaria.id])
    evento(client, h, "Secundaria", dia, alcance="niveles", niveles=[e.secundaria.id])
    evento(client, h, "Solo 2° A", dia, alcance="secciones", secciones=[e.s2.id])
    evento(client, h, "Solo 1° A secundaria", dia, alcance="secciones", secciones=[e.ss.id])

    madre = auth("alfa", token_familia(client, "alfa"))  # a1 (1° A) y a2 (2° A) de primaria
    r = client.get(f"/api/familia/calendario/mes?mes={mes_de(dia)}", headers=madre)
    assert r.status_code == 200
    ev = {x["titulo"]: x for x in r.json()["eventos"]}
    assert set(ev) == {"Todos", "Primaria", "Solo 2° A"}
    assert ev["Todos"]["hijos"] == ["Niño0", "Niño1"] and ev["Solo 2° A"]["hijos"] == ["Niño1"]
    assert "avisar" not in ev["Todos"] and "secciones" not in ev["Todos"]  # lo interno del colegio no sale
    assert set(titulos(client.get("/api/familia/calendario/proximos", headers=madre))) == set(ev)

    otra = auth("alfa", token_familia(client, "alfa", dni="42222222"))  # a3, secundaria
    assert set(titulos(client.get(f"/api/familia/calendario/mes?mes={mes_de(dia)}", headers=otra))) == {
        "Todos", "Secundaria", "Solo 1° A secundaria"}


# --- Avisos --------------------------------------------------------------------------------------------------

def test_aviso_al_publicar_solo_con_avisar_y_a_quien_va(client, db):
    e = preparar(db, "alfa", otra=True)
    h = auth("alfa", token(client, "alfa"))
    suscribir(client, "alfa")
    suscribir(client, "alfa", dni="42222222", endpoint="https://push.example/2")
    dia = date(hoy().year + 1, 3, 13) if hoy().month > 2 else hoy() + timedelta(days=20)
    evento(client, h, "Sin aviso", dia)
    assert cola(db) == []
    x = evento(client, h, "Paseo", dia, hora="08:30", tipo="salida", alcance="secciones", secciones=[e.s2.id],
               avisar=True)
    assert x["avisos"] == 1 and x["avisado"] is True
    [aviso] = cola(db)
    assert aviso.apoderado_id == e.madre.id and aviso.datos["url"] == "/familia/calendario"
    esperado = f"Calendario: Paseo, {calendario.fecha_texto(dia, dia)} a las 08:30."
    assert enviar(db) == [esperado]
    # Editarlo no repite el aviso.
    r = client.put(f"/api/calendario/eventos/{x['id']}", headers=h, json={
        "titulo": "Paseo al zoológico", "inicio": dia.isoformat(), "tipo": "salida", "alcance": "secciones",
        "secciones": [e.s2.id], "avisar": True})
    assert r.json()["avisos"] == 0 and len(cola(db)) == 1
    # Marcar "avisar" después de crearlo: avisa una vez.
    y = evento(client, h, "Reunión", dia, tipo="reunion_padres")
    r = client.put(f"/api/calendario/eventos/{y['id']}", headers=h, json={
        "titulo": "Reunión", "inicio": dia.isoformat(), "tipo": "reunion_padres", "avisar": True})
    assert r.json()["avisos"] == 2 and len(cola(db)) == 3
    assert calendario.fecha_texto(date(2026, 11, 14), date(2026, 11, 14)) == "el sábado 14 de noviembre"
    assert calendario.fecha_texto(date(2026, 11, 28), date(2026, 12, 2)) == "del 28 de noviembre al 2 de diciembre"


def test_aviso_respeta_el_horario_sin_molestar_y_se_apaga_en_configuracion(client, db):
    e = preparar(db, "alfa")
    e.colegio.silencio_desde, e.colegio.silencio_hasta = time(21, 0), time(6, 0)
    db.commit()
    h = auth("alfa", token(client, "alfa"))
    suscribir(client, "alfa")
    evento(client, h, "Actuación", avisar=True)
    noche = datetime.combine(hoy(), time(23, 0), LIMA).astimezone(UTC)
    # El aviso se encola con la hora real: si la prueba corre después de las 23:00, aún no le tocaría a las 23:00.
    [aviso] = cola(db)
    aviso.procesar_desde = noche - timedelta(minutes=1)
    db.commit()
    assert enviar(db, noche) == []
    [aviso] = cola(db)
    assert aviso.estado == "pendiente"
    assert aviso.procesar_desde == datetime.combine(hoy() + timedelta(days=1), time(6, 0), LIMA).astimezone(UTC)
    assert enviar(db, aviso.procesar_desde + timedelta(minutes=1)) != []
    # Apagado en Configuración › Avisos: no sale (ni al publicar ni el recordatorio).
    r = client.put("/api/configuracion/avisos", headers=h, json={"tipos": {"calendario": False}, "silencio_desde": "21:00", "silencio_hasta": "06:00"})
    assert r.status_code == 200, r.text
    evento(client, h, "Otro", avisar=True)
    assert len(cola(db)) == 1
    db.expire_all()
    manana = evento(client, h, "Mañana", hoy() + timedelta(days=5), avisar=True)
    assert calendario.revisar_recordatorios(db, hoy() + timedelta(days=4)) == 0
    assert len(cola(db)) == 1 and manana


def test_recordatorio_del_dia_anterior_solo_con_avisar_y_sin_repetir(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    suscribir(client, "alfa")
    dia = hoy() + timedelta(days=6)
    con = evento(client, h, "Actuación", dia, hora="09:00", avisar=True)
    evento(client, h, "Sin avisar", dia)
    enviar(db)  # sale el aviso de publicación
    vispera = dia - timedelta(days=1)
    assert calendario.revisar_recordatorios(db, vispera - timedelta(days=1)) == 0  # aún no es la víspera
    assert calendario.revisar_recordatorios(db, vispera) == 1
    assert calendario.revisar_recordatorios(db, vispera) == 0  # sin repetir
    assert enviar(db) == ["Mañana: Actuación a las 09:00."]
    assert [a.datos["que"] for a in cola(db)] == ["publicado", "recordatorio"]
    # Cambiar la fecha vuelve a programar el recordatorio (una vez).
    nuevo = dia + timedelta(days=7)
    client.put(f"/api/calendario/eventos/{con['id']}", headers=h, json={
        "titulo": "Actuación", "inicio": nuevo.isoformat(), "hora": "09:00", "tipo": "actuacion", "avisar": True})
    assert calendario.revisar_recordatorios(db, nuevo - timedelta(days=1)) == 1
    assert len(cola(db)) == 3
    assert e


def test_evento_de_hoy_o_manana_solo_lleva_el_aviso_de_publicacion(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    suscribir(client, "alfa")
    evento(client, h, "Mañana", hoy() + timedelta(days=1), avisar=True)
    evento(client, h, "Pasó", hoy() - timedelta(days=3), avisar=True)  # ya terminó: sin aviso
    assert calendario.revisar_recordatorios(db, hoy()) == 0
    assert [a.datos["que"] for a in cola(db)] == ["publicado"]
    assert e


def test_anular_no_manda_recordatorio_y_descarta_lo_pendiente(client, db):
    e = preparar(db, "alfa")
    e.colegio.silencio_desde, e.colegio.silencio_hasta = time(0, 0), time(23, 59)  # todo espera
    db.commit()
    h = auth("alfa", token(client, "alfa"))
    suscribir(client, "alfa")
    dia = hoy() + timedelta(days=4)
    x = evento(client, h, "Paseo", dia, avisar=True)
    [aviso] = cola(db)
    assert aviso.estado == "pendiente"
    client.post(f"/api/calendario/eventos/{x['id']}/anular", headers=h, json={"motivo": "Paro de transportes"})
    [aviso] = cola(db)
    assert aviso.estado == "descartado" and aviso.datos["motivo"] == "evento anulado"
    assert calendario.revisar_recordatorios(db, dia - timedelta(days=1)) == 0
    assert len(cola(db)) == 1


def test_recordatorio_no_sale_con_el_modulo_apagado(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    dia = hoy() + timedelta(days=5)
    evento(client, h, "Actuación", dia, avisar=True)
    e.colegio.modulos_apagados = ["calendario"]
    db.commit()
    assert calendario.revisar_recordatorios(db, dia - timedelta(days=1)) == 0


# --- PDF ------------------------------------------------------------------------------------------------------

def test_pdf_del_mes(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    dia = hoy() + timedelta(days=2)
    evento(client, h, "Aniversario del colegio con un título bastante largo para recortar", dia, hora="10:00")
    db.add(DiaNoLectivo(colegio_id=e.colegio.id, anio_id=e.anio.id, fecha=dia + timedelta(days=1), motivo="Feriado"))
    db.commit()
    r = client.get(f"/api/calendario/mes.pdf?mes={mes_de(dia)}", headers=h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["content-type"] == "application/pdf"
    assert f"calendario-{mes_de(dia)}.pdf" in r.headers["content-disposition"]
    vacio = client.get("/api/calendario/mes.pdf?mes=2001-01", headers=h)
    assert vacio.status_code == 200 and vacio.content.startswith(b"%PDF")
    assert client.get("/api/calendario/mes.pdf?mes=2026-13", headers=h).status_code == 422


# --- Permisos, módulo y aislamiento ----------------------------------------------------------------------------

def test_permisos_ver_y_editar(client, db):
    e = preparar(db, "alfa")
    crear_personal(db, e.colegio, "20000001", {"calendario": "ver"})
    crear_personal(db, e.colegio, "20000002", {"padron": "editar"})
    db.commit()
    lector = auth("alfa", token(client, "alfa", usuario="20000001"))
    nadie = auth("alfa", token(client, "alfa", usuario="20000002"))
    assert client.get("/api/calendario/mes", headers=lector).status_code == 200
    assert client.get("/api/calendario/mes.pdf", headers=lector).status_code == 200
    evento(client, lector, esperado=403)
    for url in ("/api/calendario/mes", "/api/calendario/proximos", "/api/calendario/opciones",
                "/api/calendario/mes.pdf"):
        assert client.get(url, headers=nadie).status_code == 403, url
    evento(client, nadie, esperado=403)
    x = evento(client, auth("alfa", token(client, "alfa")))
    assert client.post(f"/api/calendario/eventos/{x['id']}/anular", headers=lector,
                       json={"motivo": "x"}).status_code == 403


def test_modulo_apagado_403_y_sin_pestana_en_la_familia(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    hf = auth("alfa", token_familia(client, "alfa"))
    x = evento(client, h)
    assert client.get("/api/familia/yo", headers=hf).json()["modulos"]["calendario"] is True
    assert client.get("/api/auth/yo", headers=h).json()["permisos"]["calendario"] == "editar"
    for contratados, apagados in (([*INCLUIDOS], []), ([*INCLUIDOS, "calendario"], ["calendario"])):
        e.colegio.modulos_contratados, e.colegio.modulos_apagados = contratados, apagados
        db.commit()
        assert client.get("/api/calendario/mes", headers=h).status_code == 403
        assert client.get("/api/calendario/proximos", headers=h).status_code == 403
        evento(client, h, esperado=403)
        assert client.post(f"/api/calendario/eventos/{x['id']}/anular", headers=h,
                           json={"motivo": "x"}).status_code == 403
        assert client.get("/api/familia/calendario/mes", headers=hf).status_code == 403
        assert client.get("/api/familia/calendario/proximos", headers=hf).status_code == 403
        assert client.get("/api/familia/yo", headers=hf).json()["modulos"]["calendario"] is False
        assert "calendario" not in client.get("/api/auth/yo", headers=h).json()["permisos"]  # sin menú


def test_colegio_nuevo_sin_el_modulo_y_la_demo_con_el(client, db):
    from app import demo
    from tests.conftest import crear_colegio

    nuevo = crear_colegio(db, "nuevo")
    db.commit()
    assert not nuevo.modulo_activo("calendario")
    assert nuevo.avisos_tipos["calendario"] is True
    demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=2)
    colegio = db.scalar(select(Colegio).where(Colegio.subdominio == "demo"))
    assert colegio.modulo_activo("calendario")
    eventos = db.scalars(select(EventoCalendario).where(EventoCalendario.colegio_id == colegio.id)).all()
    assert len(eventos) >= 5 and any(x.anulado_en for x in eventos) and not any(x.avisar for x in eventos)
    demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=2)  # se reinicia sin chocar
    assert len(db.scalars(select(EventoCalendario).where(EventoCalendario.colegio_id == colegio.id)).all()) == len(eventos)


def test_aislamiento_entre_colegios(client, db):
    a = preparar(db, "alfa")
    b = preparar(db, "beta")
    ha = auth("alfa", token(client, "alfa"))
    hb = auth("beta", token(client, "beta"))
    dia = hoy() + timedelta(days=8)
    x = evento(client, ha, "Solo de alfa", dia, avisar=True)
    suscribir(client, "beta")
    # Beta no lo ve en el mes, ni en próximos, ni en el PDF, ni con el id adivinado.
    assert titulos(client.get(f"/api/calendario/mes?mes={mes_de(dia)}", headers=hb)) == []
    assert titulos(client.get("/api/calendario/proximos", headers=hb)) == []
    assert client.put(f"/api/calendario/eventos/{x['id']}", headers=hb, json={
        "titulo": "Hackeado", "inicio": dia.isoformat(), "tipo": "otro"}).status_code == 404
    assert client.post(f"/api/calendario/eventos/{x['id']}/anular", headers=hb, json={"motivo": "x"}).status_code == 404
    hfb = auth("beta", token_familia(client, "beta"))  # la misma madre (mismo DNI) también está en beta
    assert titulos(client.get(f"/api/familia/calendario/mes?mes={mes_de(dia)}", headers=hfb)) == []
    # El token de alfa no sirve en beta.
    assert client.get("/api/calendario/mes", headers={**hb, "Authorization": ha["Authorization"]}).status_code in (401, 403)
    # El aviso solo va a familias de alfa.
    assert {c.colegio_id for c in cola(db)} == {a.colegio.id}
    db.expire_all()
    assert db.get(EventoCalendario, x["id"]).titulo == "Solo de alfa" and b


def test_migracion_sube_y_baja(client, db):
    from alembic import command
    from alembic.config import Config

    db.close()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    tablas = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    try:
        command.downgrade(cfg, "c3d8e1f4a2b7")
        with get_engine().begin() as conn:
            assert not {"evento_calendario", "destino_evento"} & set(conn.execute(text(tablas)).scalars())
            for i, (sub, demo) in enumerate((("alfa", False), ("demo", True)), 1):
                conn.execute(text(
                    "INSERT INTO colegio (id, nombre, subdominio, color_primario, color_secundario, estado, es_demo, "
                    f"creado_en) VALUES ({i}, 'C', '{sub}', '#111111', '#222222', 'activo', {demo}, now())"))
        command.upgrade(cfg, "head")
        with get_engine().begin() as conn:
            assert {"evento_calendario", "destino_evento"} <= set(conn.execute(text(tablas)).scalars())
            filas = {s: (m, a) for s, m, a in conn.execute(text(
                "SELECT subdominio, modulos_contratados, avisos_tipos FROM colegio"))}
            assert "calendario" not in filas["alfa"][0] and "calendario" in filas["demo"][0]
            assert filas["alfa"][1]["calendario"] is True
        command.downgrade(cfg, "c3d8e1f4a2b7")
        with get_engine().begin() as conn:
            assert not {"evento_calendario", "destino_evento"} & set(conn.execute(text(tablas)).scalars())
            filas = {s: (m, a) for s, m, a in conn.execute(text(
                "SELECT subdominio, modulos_contratados, avisos_tipos FROM colegio"))}
            assert "calendario" not in filas["demo"][0] and "calendario" not in filas["demo"][1]
    finally:
        command.upgrade(cfg, "head")


def test_inicio_del_panel_muestra_los_tres_proximos(client, db):
    e = preparar(db, "alfa")
    h = auth("alfa", token(client, "alfa"))
    for i, titulo in enumerate(["Uno", "Dos", "Tres", "Cuatro"], 1):
        evento(client, h, titulo, hoy() + timedelta(days=i))
    x = evento(client, h, "Anulado", hoy())
    client.post(f"/api/calendario/eventos/{x['id']}/anular", headers=h, json={"motivo": "x"})
    evento(client, h, "Pasado", hoy() - timedelta(days=2))
    assert [x["titulo"] for x in client.get("/api/panel/resumen", headers=h).json()["calendario"]] == [
        "Uno", "Dos", "Tres"]
    crear_personal(db, e.colegio, "20000003", {"asistencia": "ver"})
    db.commit()
    sin = auth("alfa", token(client, "alfa", usuario="20000003"))
    assert "calendario" not in client.get("/api/panel/resumen", headers=sin).json()
