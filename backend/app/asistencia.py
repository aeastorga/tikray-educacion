"""Reglas de asistencia, separadas de las rutas para usarlas igual desde la
portería, la marcación manual, los equipos (fase 2) y el proceso de faltas.

- `registrar`: una lectura -> entrada, salida o duplicada; tardanza según el
  turno; deja el aviso a la familia en `cola_aviso`. No envía nada: así la
  marcación responde rápido y el envío ocurre en segundo plano.
- `marcar_faltas`: a quien no llegó cuando ya pasó el corte de su turno, solo en
  días lectivos. El personal con licencia queda como "licencia", no "falta".
"""

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import and_, case, cast, delete, exists, literal, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session

from app import codigos
from app.fechas import LIMA
from app.models import (Alumno, AnioEscolar, AsistenciaAlumno, AsistenciaPersonal, ColaAviso, Colegio,
                        ConfigAsistencia, LicenciaPersonal, Marcacion, Matricula, Seccion, Turno, Usuario)
from app.routers.estructura import es_dia_lectivo

log = logging.getLogger(__name__)

MINUTOS_DUPLICADO = 10
MINUTOS_CORTE_FALTA = 90
# El reloj del celular de portería puede ir un poco adelantado; más que esto es un error.
FUTURO_MAXIMO = timedelta(minutes=5)
# Lo que se acepta de una portería que estuvo sin internet.
PASADO_MAXIMO = timedelta(days=30)
# Una marcación que llega tarde (sincronizada después) ya no avisa: "ingresó a las 7:40" a las 3 p. m. confunde.
AVISO_VIGENTE = timedelta(hours=3)


def config(db: Session, colegio_id: int) -> ConfigAsistencia:
    return db.get(ConfigAsistencia, colegio_id) or ConfigAsistencia(
        colegio_id=colegio_id, minutos_duplicado=MINUTOS_DUPLICADO, minutos_corte_falta=MINUTOS_CORTE_FALTA)


def hora(momento: datetime | None) -> str | None:
    return momento.astimezone(LIMA).strftime("%H:%M") if momento else None


def minutos_tarde(turno: Turno | None, entrada: datetime) -> int:
    """Minutos después de la hora de entrada; 0 si llegó dentro de la tolerancia o no tiene turno."""
    if turno is None:
        return 0
    local = entrada.astimezone(LIMA)
    inicio = datetime.combine(local.date(), turno.hora_entrada, LIMA)
    minutos = int((local - inicio).total_seconds() // 60)
    return minutos if minutos > turno.tolerancia_minutos else 0


@dataclass
class Persona:
    tipo: str  # "alumno" | "personal"
    id: int
    nombre: str
    turno: Turno | None
    seccion_id: int | None = None


def _anio_activo(colegio_id: int):
    return (select(AnioEscolar.id).where(AnioEscolar.colegio_id == colegio_id, AnioEscolar.activo)
            .scalar_subquery())


def buscar_alumno(db: Session, colegio_id: int, *, id_: int | None = None, codigo: str | None = None) -> Persona | None:
    q = (select(Alumno, Matricula.seccion_id, Turno).select_from(Alumno)
         .outerjoin(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id, Matricula.alumno_id == Alumno.id,
                                    Matricula.anio_id == _anio_activo(colegio_id)))
         .outerjoin(Seccion, and_(Seccion.colegio_id == Matricula.colegio_id, Seccion.id == Matricula.seccion_id))
         .outerjoin(Turno, and_(Turno.colegio_id == Seccion.colegio_id, Turno.id == Seccion.turno_id))
         .where(Alumno.colegio_id == colegio_id, Alumno.activo))
    q = q.where(Alumno.id == id_) if id_ is not None else q.where(Alumno.codigo == codigo)
    fila = db.execute(q).first()
    if fila is None:
        return None
    a, seccion_id, turno = fila
    return Persona("alumno", a.id, f"{a.apellidos}, {a.nombres}", turno, seccion_id)


def buscar_personal(db: Session, colegio_id: int, *, id_: int | None = None,
                    codigo: str | None = None) -> Persona | None:
    q = (select(Usuario, Turno)
         .outerjoin(Turno, and_(Turno.colegio_id == Usuario.colegio_id, Turno.id == Usuario.turno_id))
         .where(Usuario.colegio_id == colegio_id, Usuario.activo))
    q = q.where(Usuario.id == id_) if id_ is not None else q.where(Usuario.codigo == codigo)
    fila = db.execute(q).first()
    if fila is None:
        return None
    u, turno = fila
    return Persona("personal", u.id, f"{u.apellidos}, {u.nombres}", turno)


@dataclass
class Lectura:
    id_cliente: str
    momento: datetime
    origen: str  # qr | manual | equipo
    codigo: str | None = None
    alumno_id: int | None = None
    usuario_id: int | None = None
    equipo: str | None = None


def _persona(db: Session, colegio_id: int, l: Lectura) -> Persona | None:
    if l.alumno_id is not None:
        return buscar_alumno(db, colegio_id, id_=l.alumno_id)
    if l.usuario_id is not None:
        return buscar_personal(db, colegio_id, id_=l.usuario_id)
    leido = codigos.leer_qr(l.codigo or "")
    if leido is None:
        return None
    tipo, codigo = leido
    persona = buscar_alumno(db, colegio_id, codigo=codigo) if tipo in ("alumno", None) else None
    if persona is None and tipo in ("personal", None):
        persona = buscar_personal(db, colegio_id, codigo=codigo)
    return persona


def _respuesta(l: Lectura, persona: Persona, resultado: str, fila) -> dict:
    return {
        "id_cliente": l.id_cliente, "estado": "ok", "resultado": resultado,
        "persona": {"tipo": persona.tipo, "id": persona.id, "nombre": persona.nombre},
        "hora": hora(l.momento), "estado_dia": fila.estado,
        "entrada": hora(fila.entrada), "salida": hora(fila.salida), "minutos_tarde": fila.minutos_tarde,
    }


def registrar(db: Session, colegio_id: int, l: Lectura, registrado_por_id: int | None,
              ahora: datetime | None = None) -> dict:
    """Guarda una lectura y actualiza la asistencia del día. No hace commit."""
    ahora = ahora or datetime.now(UTC)
    if l.momento.tzinfo is None:  # los equipos suelen mandar hora local sin zona
        l.momento = l.momento.replace(tzinfo=LIMA)
    if l.momento > ahora + FUTURO_MAXIMO:
        return {"id_cliente": l.id_cliente, "estado": "rechazada", "mensaje": "La hora del equipo está adelantada"}
    if l.momento < ahora - PASADO_MAXIMO:
        return {"id_cliente": l.id_cliente, "estado": "rechazada", "mensaje": "Marcación demasiado antigua"}
    persona = _persona(db, colegio_id, l)
    if persona is None:
        return {"id_cliente": l.id_cliente, "estado": "desconocido", "mensaje": "Carnet no reconocido"}

    es_alumno = persona.tipo == "alumno"
    Dia = AsistenciaAlumno if es_alumno else AsistenciaPersonal
    col_marca = Marcacion.alumno_id if es_alumno else Marcacion.usuario_id
    col_dia = Dia.alumno_id if es_alumno else Dia.usuario_id
    fecha = l.momento.astimezone(LIMA).date()

    # Una lectura a la vez por persona: dos lectores (o reenvíos) simultáneos no se pisan.
    db.execute(text("SELECT pg_advisory_xact_lock(:c, :p)"),
               {"c": colegio_id, "p": persona.id if es_alumno else -persona.id})

    def dia():
        return db.scalar(select(Dia).where(Dia.colegio_id == colegio_id, col_dia == persona.id, Dia.fecha == fecha))

    previa = db.scalar(select(Marcacion).where(Marcacion.colegio_id == colegio_id,
                                               Marcacion.id_cliente == l.id_cliente))
    if previa is not None:  # reenvío de la misma marcación: misma respuesta, nada nuevo
        return _respuesta(l, persona, previa.resultado, dia())

    validas = db.scalars(select(Marcacion.momento).where(
        Marcacion.colegio_id == colegio_id, col_marca == persona.id, Marcacion.fecha == fecha,
        Marcacion.resultado != "duplicada")).all()
    ventana = timedelta(minutes=config(db, colegio_id).minutos_duplicado)
    if any(abs(m - l.momento) < ventana for m in validas):
        resultado = "duplicada"
    elif not validas or l.momento < min(validas):
        resultado = "entrada"
    else:
        resultado = "salida"

    db.add(Marcacion(
        colegio_id=colegio_id, id_cliente=l.id_cliente, momento=l.momento, fecha=fecha, origen=l.origen,
        equipo=l.equipo, registrado_por_id=registrado_por_id, resultado=resultado,
        **({"alumno_id": persona.id} if es_alumno else {"usuario_id": persona.id}),
    ))

    # La fila del día puede existir ya (otra marcación, o la falta automática).
    valores = {"colegio_id": colegio_id, "fecha": fecha, "estado": "presente", "minutos_tarde": 0,
               **({"alumno_id": persona.id, "seccion_id": persona.seccion_id} if es_alumno
                  else {"usuario_id": persona.id})}
    db.execute(insert(Dia).values(**valores).on_conflict_do_nothing())
    fila = dia()
    if resultado != "duplicada":
        todas = [*validas, l.momento]
        fila.entrada = min(todas)
        fila.salida = max(todas) if len(todas) > 1 else None
        fila.minutos_tarde = minutos_tarde(persona.turno, fila.entrada)
        fila.estado = "tarde" if fila.minutos_tarde else "presente"
        if es_alumno and ahora - l.momento <= AVISO_VIGENTE:
            _encolar(db, colegio_id, persona.id, fecha, resultado, fila)
    db.flush()
    return _respuesta(l, persona, resultado, fila)


def _encolar(db: Session, colegio_id: int, alumno_id: int, fecha: date, resultado: str,
             fila: AsistenciaAlumno) -> None:
    if resultado == "entrada":
        tipo, momento = ("tarde" if fila.minutos_tarde else "ingreso"), fila.entrada
        # Llegó: la falta automática que aún no salió ya no corresponde.
        db.execute(delete(ColaAviso).where(ColaAviso.colegio_id == colegio_id, ColaAviso.alumno_id == alumno_id,
                                           ColaAviso.fecha == fecha, ColaAviso.tipo == "falta",
                                           ColaAviso.estado == "pendiente"))
    else:
        tipo, momento = "salida", fila.salida
    datos = {"hora": hora(momento), "minutos_tarde": fila.minutos_tarde}
    q = insert(ColaAviso).values(colegio_id=colegio_id, alumno_id=alumno_id, fecha=fecha, tipo=tipo,
                                 momento=momento, datos=datos, procesar_desde=datetime.now(UTC))
    if tipo == "salida":
        # Si vuelve a marcar salida, el aviso pendiente se queda con la última hora.
        q = q.on_conflict_do_update(
            index_elements=["colegio_id", "alumno_id", "fecha", "tipo"],
            set_={"momento": q.excluded.momento, "datos": q.excluded.datos},
            where=ColaAviso.estado == "pendiente")
    else:
        q = q.on_conflict_do_nothing()
    db.execute(q)


# --- Faltas automáticas --------------------------------------------------------

def corte(turno: Turno, minutos: int) -> time:
    fin = datetime.combine(date.min, turno.hora_entrada) + timedelta(minutes=minutos)
    return fin.time() if fin.date() == date.min else time(23, 59)


def marcar_faltas(db: Session, fecha: date, hasta: time | None = None, colegio_id: int | None = None,
                  avisar: bool = True) -> int:
    """Pone falta a quien no tiene asistencia en `fecha`, en los turnos cuyo corte ya pasó a la
    hora `hasta` (Lima). Sin `hasta`, el día está cerrado: todos los turnos. Solo días lectivos.
    Se puede correr cuantas veces se quiera: lo ya marcado no se toca. No hace commit."""
    total = 0
    consulta = select(Colegio)
    if colegio_id is not None:
        consulta = consulta.where(Colegio.id == colegio_id)
    for c in db.scalars(consulta).all():
        if not c.disponible(fecha) or not es_dia_lectivo(db, c.id, fecha):
            continue
        minutos = config(db, c.id).minutos_corte_falta
        turnos = [t.id for t in db.scalars(select(Turno).where(Turno.colegio_id == c.id))
                  if hasta is None or corte(t, minutos) <= hasta]
        if not turnos:
            continue

        alumnos = (
            select(literal(c.id), Matricula.alumno_id, literal(fecha), Matricula.seccion_id, literal("falta"),
                   literal(0))
            .join(Seccion, and_(Seccion.colegio_id == Matricula.colegio_id, Seccion.id == Matricula.seccion_id))
            .join(Alumno, and_(Alumno.colegio_id == Matricula.colegio_id, Alumno.id == Matricula.alumno_id))
            .where(Matricula.colegio_id == c.id, Matricula.anio_id == _anio_activo(c.id),
                   Seccion.turno_id.in_(turnos), Alumno.activo))
        total += len(db.execute(insert(AsistenciaAlumno).from_select(
            ["colegio_id", "alumno_id", "fecha", "seccion_id", "estado", "minutos_tarde"], alumnos,
        ).on_conflict_do_nothing().returning(AsistenciaAlumno.id)).all())

        con_licencia = exists().where(
            LicenciaPersonal.colegio_id == c.id, LicenciaPersonal.usuario_id == Usuario.id,
            LicenciaPersonal.desde <= fecha, LicenciaPersonal.hasta >= fecha)
        personal = (
            select(literal(c.id), Usuario.id, literal(fecha), case((con_licencia, "licencia"), else_="falta"),
                   literal(0))
            .where(Usuario.colegio_id == c.id, Usuario.activo, Usuario.turno_id.in_(turnos)))
        total += len(db.execute(insert(AsistenciaPersonal).from_select(
            ["colegio_id", "usuario_id", "fecha", "estado", "minutos_tarde"], personal,
        ).on_conflict_do_nothing().returning(AsistenciaPersonal.id)).all())

        if avisar:
            ahora = datetime.now(UTC)
            faltas = (select(literal(c.id), AsistenciaAlumno.alumno_id, literal(fecha), literal("falta"),
                             cast(literal("{}"), JSONB), literal(ahora), literal(ahora))
                      .where(AsistenciaAlumno.colegio_id == c.id, AsistenciaAlumno.fecha == fecha,
                             AsistenciaAlumno.estado == "falta"))
            db.execute(insert(ColaAviso).from_select(
                ["colegio_id", "alumno_id", "fecha", "tipo", "datos", "procesar_desde", "creado_en"], faltas,
            ).on_conflict_do_nothing())
    return total


def aplicar_licencia(db: Session, lic: LicenciaPersonal, quitar: bool = False) -> None:
    """Una licencia registrada después de la falta automática la corrige (y al borrarla, vuelve a falta)."""
    antes, despues = ("licencia", "falta") if quitar else ("falta", "licencia")
    for fila in db.scalars(select(AsistenciaPersonal).where(
            AsistenciaPersonal.colegio_id == lic.colegio_id, AsistenciaPersonal.usuario_id == lic.usuario_id,
            AsistenciaPersonal.fecha.between(lic.desde, lic.hasta), AsistenciaPersonal.estado == antes,
            AsistenciaPersonal.entrada.is_(None))):
        fila.estado = despues


def bucle_faltas(parar: threading.Event, cada: int = 60) -> None:
    """Proceso en segundo plano del servidor. Varias instancias a la vez no duplican nada (ON CONFLICT)."""
    from app.db import get_sessionmaker

    while not parar.wait(cada):
        try:
            ahora = datetime.now(LIMA)
            with get_sessionmaker()() as db:
                marcar_faltas(db, ahora.date(), ahora.time().replace(tzinfo=None))
                db.commit()
        except Exception:
            log.exception("Faltas automáticas")

