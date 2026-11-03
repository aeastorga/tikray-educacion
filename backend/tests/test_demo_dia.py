"""La demo muestra un día en curso creíble: marcaciones de hoy hasta la hora de Lima, avisos y cuaderno."""

from datetime import UTC, datetime, time, timedelta

from sqlalchemy import delete, func, select

from app import demo
from app.demo_dia import simular_dia
from app.fechas import LIMA, hoy_lima
from app.models import (AsistenciaAlumno, AsistenciaPersonal, ColaAviso, Colegio, DestinoCuaderno, EntradaCuaderno,
                        EntregaAviso, Marcacion, SuscripcionPush)
from app.routers.estructura import es_dia_lectivo
from tests.conftest import crear_colegio


def _dia_limpio(db, cid):
    """Un día lectivo reciente sin nada registrado (la historia de la demo llega hasta ayer)."""
    dia = hoy_lima()
    while not es_dia_lectivo(db, cid, dia):
        dia -= timedelta(days=1)
    for m in (AsistenciaAlumno, AsistenciaPersonal, Marcacion, ColaAviso):
        db.execute(delete(m).where(m.colegio_id == cid, m.fecha == dia))
    db.execute(delete(EntregaAviso).where(EntregaAviso.colegio_id == cid,
                                          ~EntregaAviso.aviso_id.in_(select(ColaAviso.id))))
    db.commit()
    return dia


def _estados(db, cid, dia):
    return dict(db.execute(select(AsistenciaAlumno.estado, func.count()).where(
        AsistenciaAlumno.colegio_id == cid, AsistenciaAlumno.fecha == dia).group_by(AsistenciaAlumno.estado)).all())


def test_simula_el_dia_hasta_la_hora_actual(db):
    r = demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=8)
    colegio = db.get(Colegio, r.colegio_id)
    cid, dia = colegio.id, _dia_limpio(db, colegio.id)

    # Antes de que llegue nadie, ningún alumno (solo queda anotado quien está de licencia).
    simular_dia(db, colegio, datetime.combine(dia, time(6, 30), LIMA))
    assert _estados(db, cid, dia) == {}
    assert {e for (e,) in db.execute(select(AsistenciaPersonal.estado).where(
        AsistenciaPersonal.colegio_id == cid, AsistenciaPersonal.fecha == dia))} <= {"licencia"}

    # A media mañana: casi todos llegaron, algunos tarde, pocas faltas.
    once = datetime.combine(dia, time(11, 0), LIMA)
    assert simular_dia(db, colegio, once) > 0
    db.commit()
    e = _estados(db, cid, dia)
    manana = e.get("presente", 0) + e.get("tarde", 0) + e.get("falta", 0)
    assert manana > 0
    assert e.get("tarde", 0) > 0 and e.get("falta", 0) > 0
    assert (e["presente"] + e["tarde"]) / manana > 0.85
    assert e["falta"] / manana < 0.1
    # Nadie del turno tarde marcó todavía a las 11:00 ni hay salidas.
    assert db.scalar(select(func.count()).select_from(AsistenciaAlumno).where(
        AsistenciaAlumno.colegio_id == cid, AsistenciaAlumno.fecha == dia, AsistenciaAlumno.salida.is_not(None))) == 0
    for (entrada,) in db.execute(select(AsistenciaAlumno.entrada).where(
            AsistenciaAlumno.colegio_id == cid, AsistenciaAlumno.fecha == dia, AsistenciaAlumno.entrada.is_not(None))):
        assert entrada <= once
    assert db.scalar(select(func.count()).select_from(AsistenciaPersonal).where(
        AsistenciaPersonal.colegio_id == cid, AsistenciaPersonal.fecha == dia)) > 0

    # Repetir a la misma hora no duplica nada; más tarde solo agrega lo nuevo (salidas, turno tarde).
    assert simular_dia(db, colegio, once) == 0
    assert simular_dia(db, colegio, datetime.combine(dia, time(18, 40), LIMA)) > 0
    db.commit()
    assert db.scalar(select(func.count()).select_from(AsistenciaAlumno).where(
        AsistenciaAlumno.colegio_id == cid, AsistenciaAlumno.fecha == dia, AsistenciaAlumno.salida.is_not(None))) > 0


def test_avisos_simulados_sin_suscripciones_falsas(db):
    r = demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=8)
    colegio = db.get(Colegio, r.colegio_id)
    cid, dia = colegio.id, _dia_limpio(db, colegio.id)
    simular_dia(db, colegio, datetime.combine(dia, time(11, 0), LIMA))
    db.commit()

    avisos = dict(db.execute(select(ColaAviso.estado, func.count()).where(
        ColaAviso.colegio_id == cid, ColaAviso.fecha == dia).group_by(ColaAviso.estado)).all())
    assert "pendiente" not in avisos  # nada queda en cola para enviarse de verdad
    assert avisos.get("enviado", 0) > 0
    entregas = dict(db.execute(select(EntregaAviso.estado, func.count()).join(
        ColaAviso, ColaAviso.id == EntregaAviso.aviso_id).where(
        EntregaAviso.colegio_id == cid, ColaAviso.fecha == dia).group_by(EntregaAviso.estado)).all())
    assert entregas.get("enviado", 0) > entregas.get("sin_notificaciones", 0) > 0
    assert db.scalar(select(func.count()).select_from(SuscripcionPush).where(SuscripcionPush.colegio_id == cid)) == 0


def test_no_simula_en_un_colegio_real(db):
    real = crear_colegio(db, "real")
    assert simular_dia(db, real, datetime.now(UTC)) == 0


def test_cuaderno_de_la_demo_en_horario_escolar(db):
    r = demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=3)
    cid, ahora = r.colegio_id, datetime.now(UTC)
    for (creado,) in db.execute(select(EntradaCuaderno.creado_en).where(EntradaCuaderno.colegio_id == cid)):
        assert creado.tzinfo is not None and creado <= ahora
        assert time(7, 30) <= creado.astimezone(LIMA).time() <= time(16, 30)
    for visto, firmado in db.execute(select(DestinoCuaderno.visto_en, DestinoCuaderno.firmado_en).where(
            DestinoCuaderno.colegio_id == cid, DestinoCuaderno.visto_en.is_not(None))):
        assert visto <= ahora
        assert time(6, 0) <= visto.astimezone(LIMA).time() < time(22, 0)
        assert firmado is None or firmado == visto


# --- Proceso de fondo: la demo nunca frena las faltas reales ----------------------------------

def test_si_la_demo_falla_las_faltas_reales_igual_se_marcan(db, monkeypatch, caplog):
    from app import asistencia, demo_dia
    from app.db import get_sessionmaker
    from tests.test_asistencia import HOY, en, preparar

    e = preparar(db, "real", alumnos=2, dias_semana="1234567")
    monkeypatch.setattr(asistencia.log, "disabled", False)  # la config de Alembic de las pruebas lo apaga

    def falla(*a, **k):
        raise RuntimeError("la demo se rompió")
    monkeypatch.setattr(demo_dia, "simular_demos", falla)
    llamadas = []
    original = asistencia.marcar_faltas
    monkeypatch.setattr(asistencia, "marcar_faltas", lambda *a, **k: llamadas.append(a) or original(*a, **k))

    ahora = en(HOY, 10, 0)  # pasó el corte de 9:15
    assert asistencia.vuelta_faltas(None, ahora, get_sessionmaker()) == ahora  # las faltas se dan por hechas
    assert llamadas
    assert "Día simulado de la demo" in caplog.text
    db.expire_all()
    assert _estados(db, e.colegio.id, HOY) == {"falta": 2}


def test_la_demo_corrige_faltas_automaticas_de_quien_si_llego(db):
    from app import asistencia

    r = demo.crear_o_reiniciar(db, "demo", alumnos_por_seccion=8)
    colegio = db.get(Colegio, r.colegio_id)
    cid, dia = colegio.id, _dia_limpio(db, colegio.id)
    once = datetime.combine(dia, time(11, 0), LIMA)
    # El servidor arrancó a las 11: las faltas automáticas corren primero y marcan a todo el turno mañana.
    asistencia.marcar_faltas(db, dia, time(11, 0), cid)
    db.commit()
    antes = _estados(db, cid, dia)
    assert antes.get("falta", 0) > 0 and "presente" not in antes
    simular_dia(db, colegio, once)
    db.commit()
    e = _estados(db, cid, dia)
    total = sum(e.values())
    assert e["falta"] / total < 0.1 and e["presente"] > 0
    assert db.scalar(select(func.count()).select_from(ColaAviso).where(
        ColaAviso.colegio_id == cid, ColaAviso.fecha == dia, ColaAviso.tipo == "falta")) == e["falta"]
