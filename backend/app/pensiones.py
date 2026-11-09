"""Reglas de pensiones: monto de cada alumno, mora, saldo y estado de una cuota, generación de cuotas,
descuentos, retiro, responsable de pago y avisos de cobro.

Todo en Decimal con dos decimales (nunca float). Las fechas de vencimiento son días de Lima.
La deuda nunca bloquea nada fuera de este módulo (asistencia, avisos, cuaderno, acceso de la familia).
"""

import logging
import math
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import configuracion
from app.fechas import LIMA, hoy_lima
from app.models import (Alumno, AlumnoApoderado, ColaAviso, Colegio, ConceptoCobro, ConfigPensiones,
                        CuotaAlumno, CuotaProgramada, DescuentoAlumno, Grado, Matricula, MontoConcepto, Seccion)

log = logging.getLogger(__name__)

CERO = Decimal("0.00")
CENTIMO = Decimal("0.01")
MOTIVO_RETIRO = "Retiro"
ESTADOS = ("pendiente", "parcial", "pagada", "vencida", "anulada")


def soles(valor) -> Decimal:
    return Decimal(valor).quantize(CENTIMO, rounding=ROUND_HALF_UP)


def texto_soles(valor: Decimal) -> str:
    return f"S/ {soles(valor):,.2f}"


def config(db: Session, colegio_id: int, bloquear: bool = False) -> ConfigPensiones:
    """La fila de configuración (se crea con los valores por defecto la primera vez)."""
    q = select(ConfigPensiones).where(ConfigPensiones.colegio_id == colegio_id)
    cfg = db.scalar(q.with_for_update() if bloquear else q)
    if cfg is None:
        # Dos cobros a la vez en un colegio nuevo: uno la crea y el otro espera y la usa.
        db.execute(insert(ConfigPensiones).values(colegio_id=colegio_id).on_conflict_do_nothing())
        cfg = db.scalar(q.with_for_update() if bloquear else q)
    return cfg


# --- Mora, saldo y estado ---------------------------------------------------------------------

def mora_del_dia(cfg: ConfigPensiones, monto: Decimal, descuento: Decimal, vence: date, hoy: date) -> Decimal:
    """Mora a la fecha: fija por cuota vencida, o % mensual sobre la cuota (sin interés sobre interés).
    Cada mes empezado de atraso cuenta como uno. Con tope por cuota."""
    dias = (hoy - vence).days
    base = monto - descuento
    if cfg.mora_tipo == "ninguna" or dias <= 0 or base <= 0:
        return CERO
    if cfg.mora_tipo == "fijo":
        mora = soles(cfg.mora_valor)
    else:
        mora = soles(base * cfg.mora_valor / 100 * math.ceil(dias / 30))
    if cfg.mora_tope is not None:
        mora = min(mora, soles(cfg.mora_tope))
    return mora


@dataclass
class Situacion:
    mora: Decimal
    saldo: Decimal
    estado: str
    dias_atraso: int


def situacion(c: CuotaAlumno, vence: date, cfg: ConfigPensiones, hoy: date) -> Situacion:
    """Saldo = monto - descuento + mora - pagos válidos. La mora deja de crecer cuando la cuota (sin mora)
    ya está pagada; la que se cargó al cobrar (`c.mora`) no baja."""
    base = c.monto - c.descuento
    mora = c.mora if c.pagado >= base else max(c.mora, mora_del_dia(cfg, c.monto, c.descuento, vence, hoy))
    saldo = max(CERO, base + mora - c.pagado)
    dias = max(0, (hoy - vence).days)
    if c.anulada_en is not None:
        return Situacion(mora, CERO, "anulada", 0)
    if saldo == 0:
        estado = "pagada"
    elif vence < hoy:
        estado = "vencida"
    elif c.pagado > 0:
        estado = "parcial"
    else:
        estado = "pendiente"
    return Situacion(mora, saldo, estado, dias if estado == "vencida" else 0)


# --- Montos y descuentos ----------------------------------------------------------------------

def montos_de(db: Session, colegio_id: int, concepto_ids: list[int]) -> dict[tuple[int, str, int], Decimal]:
    """(concepto, "grado"|"nivel", id) -> monto."""
    if not concepto_ids:
        return {}
    return {(m.concepto_id, "grado" if m.grado_id else "nivel", m.grado_id or m.nivel_id): m.monto
            for m in db.scalars(select(MontoConcepto).where(MontoConcepto.colegio_id == colegio_id,
                                                            MontoConcepto.concepto_id.in_(concepto_ids)))}


def monto_para(montos: dict, concepto_id: int, grado_id: int, nivel_id: int) -> Decimal | None:
    """El del grado manda sobre el del nivel. None si no hay ninguno."""
    return montos.get((concepto_id, "grado", grado_id), montos.get((concepto_id, "nivel", nivel_id)))


def descuentos_vigentes(db: Session, colegio_id: int, alumno_ids: list[int], anio_id: int) -> dict[int, list]:
    if not alumno_ids:
        return {}
    salida: dict[int, list] = {}
    for d in db.scalars(select(DescuentoAlumno).where(
            DescuentoAlumno.colegio_id == colegio_id, DescuentoAlumno.anio_id == anio_id,
            DescuentoAlumno.alumno_id.in_(alumno_ids), DescuentoAlumno.anulado_en.is_(None))):
        salida.setdefault(d.alumno_id, []).append(d)
    return salida


def descuento_para(monto: Decimal, concepto_id: int, descuentos: list[DescuentoAlumno]) -> Decimal:
    """Suma de los descuentos del concepto y de "todos". Nunca más que el monto (tope 100 %)."""
    total = CERO
    for d in descuentos:
        if d.concepto_id not in (None, concepto_id):
            continue
        total += soles(monto * d.valor / 100) if d.tipo == "porcentaje" else soles(d.valor)
    return min(monto, total)


def porcentaje_acumulado(db: Session, colegio_id: int, alumno_id: int, anio_id: int,
                         concepto_id: int | None) -> Decimal:
    """Porcentaje que ya tiene el alumno y que alcanzaría a este concepto (para el tope de 100 %)."""
    q = select(func.coalesce(func.sum(DescuentoAlumno.valor), 0)).where(
        DescuentoAlumno.colegio_id == colegio_id, DescuentoAlumno.alumno_id == alumno_id,
        DescuentoAlumno.anio_id == anio_id, DescuentoAlumno.anulado_en.is_(None), DescuentoAlumno.tipo == "porcentaje")
    if concepto_id is not None:  # los de "todos" y los de este concepto
        q = q.where((DescuentoAlumno.concepto_id.is_(None)) | (DescuentoAlumno.concepto_id == concepto_id))
    return Decimal(db.scalar(q))


# --- Generar y recalcular cuotas --------------------------------------------------------------

def _alumnos_del_anio(db: Session, colegio_id: int, anio_id: int, alumno_ids: list[int] | None):
    """(alumno_id, grado_id, nivel_id) de los matriculados y activos del año."""
    q = (select(Matricula.alumno_id, Grado.id, Grado.nivel_id)
         .join(Alumno, and_(Alumno.colegio_id == Matricula.colegio_id, Alumno.id == Matricula.alumno_id))
         .join(Seccion, and_(Seccion.colegio_id == Matricula.colegio_id, Seccion.id == Matricula.seccion_id))
         .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
         .where(Matricula.colegio_id == colegio_id, Matricula.anio_id == anio_id, Alumno.activo))
    if alumno_ids is not None:
        q = q.where(Matricula.alumno_id.in_(alumno_ids))
    return db.execute(q).all()


def _cronograma(db: Session, colegio_id: int, anio_id: int):
    """(cuota_programada, concepto) de los conceptos activos del año."""
    return db.execute(
        select(CuotaProgramada, ConceptoCobro)
        .join(ConceptoCobro, and_(ConceptoCobro.colegio_id == CuotaProgramada.colegio_id,
                                  ConceptoCobro.id == CuotaProgramada.concepto_id))
        .where(CuotaProgramada.colegio_id == colegio_id, ConceptoCobro.anio_id == anio_id, ConceptoCobro.activo)
    ).all()


def generar_cuotas(db: Session, colegio_id: int, anio_id: int, alumno_ids: list[int] | None = None) -> dict:
    """Una cuota por alumno (matriculado y activo) y línea del cronograma. Solo crea las que faltan: volver a
    generar no duplica. Un alumno sin monto para su grado ni su nivel se cuenta en `sin_monto`."""
    cronograma = _cronograma(db, colegio_id, anio_id)
    alumnos = _alumnos_del_anio(db, colegio_id, anio_id, alumno_ids)
    resultado = {"creadas": 0, "sin_monto": 0, "alumnos": len(alumnos)}
    if not cronograma or not alumnos:
        return resultado
    ids = [a for a, _, _ in alumnos]
    existentes = set(db.execute(select(CuotaAlumno.alumno_id, CuotaAlumno.cuota_programada_id).where(
        CuotaAlumno.colegio_id == colegio_id, CuotaAlumno.alumno_id.in_(ids),
        CuotaAlumno.cuota_programada_id.in_([p.id for p, _ in cronograma]))).all())
    montos = montos_de(db, colegio_id, list({c.id for _, c in cronograma}))
    descuentos = descuentos_vigentes(db, colegio_id, ids, anio_id)
    sin_monto: set[int] = set()
    for alumno_id, grado_id, nivel_id in alumnos:
        for prog, concepto in cronograma:
            if (alumno_id, prog.id) in existentes:
                continue
            monto = monto_para(montos, concepto.id, grado_id, nivel_id)
            if monto is None:
                sin_monto.add(alumno_id)
                continue
            db.add(CuotaAlumno(colegio_id=colegio_id, alumno_id=alumno_id, cuota_programada_id=prog.id, monto=monto,
                               descuento=descuento_para(monto, concepto.id, descuentos.get(alumno_id, []))))
            resultado["creadas"] += 1
    resultado["sin_monto"] = len(sin_monto)
    db.flush()
    return resultado


def _cuotas_sin_pagos(db: Session, colegio_id: int, alumno_id: int, anio_id: int):
    """(cuota, concepto) del año que no tienen ningún pago ni están anuladas: las únicas que se recalculan."""
    return db.execute(
        select(CuotaAlumno, ConceptoCobro)
        .join(CuotaProgramada, and_(CuotaProgramada.colegio_id == CuotaAlumno.colegio_id,
                                    CuotaProgramada.id == CuotaAlumno.cuota_programada_id))
        .join(ConceptoCobro, and_(ConceptoCobro.colegio_id == CuotaProgramada.colegio_id,
                                  ConceptoCobro.id == CuotaProgramada.concepto_id))
        .where(CuotaAlumno.colegio_id == colegio_id, CuotaAlumno.alumno_id == alumno_id,
               ConceptoCobro.anio_id == anio_id, CuotaAlumno.pagado == 0, CuotaAlumno.mora == 0,
               CuotaAlumno.anulada_en.is_(None))
        .with_for_update(of=CuotaAlumno)).all()


def recalcular_alumno(db: Session, colegio_id: int, alumno_id: int, anio_id: int) -> int:
    """Cambio de grado o de descuentos: vuelve a calcular monto y descuento solo de las cuotas sin pagos.
    Si el nuevo grado no tiene monto, la cuota queda como estaba. Devuelve cuántas cambiaron."""
    datos = _alumnos_del_anio(db, colegio_id, anio_id, [alumno_id])
    if not datos:
        return 0
    _, grado_id, nivel_id = datos[0]
    filas = _cuotas_sin_pagos(db, colegio_id, alumno_id, anio_id)
    montos = montos_de(db, colegio_id, list({c.id for _, c in filas}))
    descuentos = descuentos_vigentes(db, colegio_id, [alumno_id], anio_id).get(alumno_id, [])
    cambiadas = 0
    for cuota, concepto in filas:
        monto = monto_para(montos, concepto.id, grado_id, nivel_id)
        monto = cuota.monto if monto is None else monto
        descuento = descuento_para(monto, concepto.id, descuentos)
        if (cuota.monto, cuota.descuento) != (monto, descuento):
            cuota.monto, cuota.descuento = monto, descuento
            cambiadas += 1
    db.flush()
    return cambiadas


def al_matricular(db: Session, colegio_id: int, alumno_id: int, anio_id: int) -> None:
    """Matrícula nueva o cambio de sección: genera las cuotas que falten y recalcula las que no tienen pagos.
    No hace nada si el colegio no tiene cronograma para ese año."""
    db.flush()
    if not db.scalar(select(CuotaProgramada.id).join(
            ConceptoCobro, and_(ConceptoCobro.colegio_id == CuotaProgramada.colegio_id,
                                ConceptoCobro.id == CuotaProgramada.concepto_id))
            .where(CuotaProgramada.colegio_id == colegio_id, ConceptoCobro.anio_id == anio_id).limit(1)):
        return
    generar_cuotas(db, colegio_id, anio_id, [alumno_id])
    recalcular_alumno(db, colegio_id, alumno_id, anio_id)


def al_retirar(db: Session, colegio_id: int, alumno_id: int, quien: str, hoy: date | None = None) -> int:
    """El alumno pasó a inactivo: se anulan sus cuotas que vencen después de hoy y que no tienen pagos
    (motivo "Retiro"). Las vencidas y no pagadas siguen como deuda. Devuelve cuántas anuló."""
    hoy = hoy or hoy_lima()
    ahora = datetime.now(UTC)
    cuotas = db.scalars(
        select(CuotaAlumno)
        .join(CuotaProgramada, and_(CuotaProgramada.colegio_id == CuotaAlumno.colegio_id,
                                    CuotaProgramada.id == CuotaAlumno.cuota_programada_id))
        .where(CuotaAlumno.colegio_id == colegio_id, CuotaAlumno.alumno_id == alumno_id,
               CuotaProgramada.vence > hoy, CuotaAlumno.anulada_en.is_(None), CuotaAlumno.pagado == 0)
        .with_for_update(of=CuotaAlumno)).all()
    for c in cuotas:
        c.anulada_en, c.anulada_motivo, c.anulada_por = ahora, MOTIVO_RETIRO, quien[:160]
    db.flush()
    return len(cuotas)


# --- Responsable de pago ----------------------------------------------------------------------

def responsables(db: Session, colegio_id: int, alumno_ids: list[int]) -> dict[int, int]:
    """alumno -> apoderado responsable de pago. Si nadie está marcado, el primero (el de id menor)."""
    if not alumno_ids:
        return {}
    salida: dict[int, int] = {}
    for alumno_id, apoderado_id, marcado in db.execute(
            select(AlumnoApoderado.alumno_id, AlumnoApoderado.apoderado_id, AlumnoApoderado.responsable_pago)
            .where(AlumnoApoderado.colegio_id == colegio_id, AlumnoApoderado.alumno_id.in_(alumno_ids))
            .order_by(AlumnoApoderado.alumno_id, AlumnoApoderado.responsable_pago.desc(),
                      AlumnoApoderado.apoderado_id)):
        salida.setdefault(alumno_id, apoderado_id)
    return salida


def es_responsable(db: Session, colegio_id: int, alumno_id: int, apoderado_id: int) -> bool:
    return responsables(db, colegio_id, [alumno_id]).get(alumno_id) == apoderado_id


def marcar_responsable(db: Session, colegio_id: int, alumno_id: int, apoderado_id: int) -> None:
    """Deja a este apoderado como el único responsable de pago del alumno."""
    for v in db.scalars(select(AlumnoApoderado).where(AlumnoApoderado.colegio_id == colegio_id,
                                                      AlumnoApoderado.alumno_id == alumno_id)):
        if v.responsable_pago and v.apoderado_id != apoderado_id:
            v.responsable_pago = False
    db.flush()
    for v in db.scalars(select(AlumnoApoderado).where(AlumnoApoderado.colegio_id == colegio_id,
                                                      AlumnoApoderado.alumno_id == alumno_id,
                                                      AlumnoApoderado.apoderado_id == apoderado_id)):
        v.responsable_pago = True
    db.flush()


# --- Avisos de cobro --------------------------------------------------------------------------

def _primer_nombre(a: Alumno) -> str:
    return a.nombres.split()[0] if a.nombres else a.apellidos


def revisar_cobros(db: Session, hoy: date | None = None, ahora: datetime | None = None) -> int:
    """Una vez al día: encola un aviso por apoderado responsable con sus cuotas que vencen en N días
    (aviso previo) o hoy y siguen con saldo (aviso del día). Marca cada cuota para no repetir. El horario
    sin molestar lo respeta la cola. Devuelve cuántos avisos encoló."""
    hoy = hoy or hoy_lima()
    ahora = ahora or datetime.now(UTC)
    encolados = 0
    for colegio in db.scalars(select(Colegio)):
        if not colegio.disponible(hoy) or not configuracion.aviso_permitido(colegio, "cobro"):
            continue
        cfg = config(db, colegio.id)
        previo = hoy + timedelta(days=cfg.dias_aviso_previo)
        filas = db.execute(
            select(CuotaAlumno, CuotaProgramada.vence, ConceptoCobro.nombre, CuotaProgramada.mes)
            .join(CuotaProgramada, and_(CuotaProgramada.colegio_id == CuotaAlumno.colegio_id,
                                        CuotaProgramada.id == CuotaAlumno.cuota_programada_id))
            .join(ConceptoCobro, and_(ConceptoCobro.colegio_id == CuotaProgramada.colegio_id,
                                      ConceptoCobro.id == CuotaProgramada.concepto_id))
            .join(Alumno, and_(Alumno.colegio_id == CuotaAlumno.colegio_id, Alumno.id == CuotaAlumno.alumno_id))
            .where(CuotaAlumno.colegio_id == colegio.id, CuotaAlumno.anulada_en.is_(None), Alumno.activo,
                   ((CuotaProgramada.vence == hoy) & CuotaAlumno.aviso_vencido_en.is_(None))
                   | ((CuotaProgramada.vence == previo) & CuotaAlumno.aviso_previo_en.is_(None)
                      & (CuotaProgramada.vence > hoy)))
            .with_for_update(of=CuotaAlumno, skip_locked=True)).all()
        por_apoderado: dict[int, list] = {}
        resp = responsables(db, colegio.id, list({c.alumno_id for c, *_ in filas}))
        for c, vence, concepto, mes in filas:
            if situacion(c, vence, cfg, hoy).saldo <= 0:
                continue
            if vence == hoy:
                c.aviso_vencido_en = ahora
            else:
                c.aviso_previo_en = ahora
            if c.alumno_id in resp:
                por_apoderado.setdefault(resp[c.alumno_id], []).append((c, vence, concepto, mes))
        nombres = dict(db.execute(select(Alumno.id, Alumno.nombres).where(
            Alumno.colegio_id == colegio.id, Alumno.id.in_({c.alumno_id for c, *_ in filas}))).all()) if filas else {}
        for apoderado_id, cuotas in por_apoderado.items():
            db.add(ColaAviso(colegio_id=colegio.id, tipo="cobro", apoderado_id=apoderado_id, fecha=hoy,
                             procesar_desde=ahora, datos={"mensaje": _mensaje_cobro(cuotas, nombres, hoy),
                                                          "url": "/familia/pagos",
                                                          "cuotas": [c.id for c, *_ in cuotas]}))
            encolados += 1
        db.flush()
    db.commit()
    return encolados


def _mensaje_cobro(cuotas: list, nombres: dict[int, str], hoy: date) -> str:
    partes = []
    for c, vence, concepto, mes in sorted(cuotas, key=lambda x: (x[1], x[0].alumno_id)):
        nombre = (nombres.get(c.alumno_id) or "").split(" ")[0]
        cuando = "vence hoy" if vence == hoy else f"vence el {vence.strftime('%d/%m')}"
        partes.append(f"{concepto} {mes} de {nombre} {cuando}")
    if len(partes) == 1:
        return f"Recordatorio: {partes[0]}."
    return f"Recordatorio: tienes {len(partes)} cuotas por pagar. " + "; ".join(partes[:3]) + (
        "…" if len(partes) > 3 else ".")


def bucle_cobros(parar: threading.Event, cada: float = 600) -> None:
    """Hilo del servidor: revisa los avisos de cobro una vez por día de Lima. Si el servidor se reinicia,
    las marcas de cada cuota evitan que se repitan."""
    from app.db import get_sessionmaker

    ultimo: date | None = None
    while True:
        hoy = datetime.now(UTC).astimezone(LIMA).date()
        if hoy != ultimo:
            try:
                with get_sessionmaker()() as db:
                    revisar_cobros(db, hoy)
                ultimo = hoy
            except Exception:
                log.exception("Avisos de cobro")
        if parar.wait(cada):
            return


# --- Para el Inicio del administrador ---------------------------------------------------------------

def deuda_vencida(db: Session, colegio_id: int, hoy: date | None = None) -> tuple[Decimal, int]:
    """Saldo de todas las cuotas vencidas (de cualquier año) y cuántos alumnos las deben."""
    hoy = hoy or hoy_lima()
    cfg = config(db, colegio_id)
    total, alumnos = CERO, set()
    for c, vence in db.execute(
            select(CuotaAlumno, CuotaProgramada.vence)
            .join(CuotaProgramada, and_(CuotaProgramada.colegio_id == CuotaAlumno.colegio_id,
                                        CuotaProgramada.id == CuotaAlumno.cuota_programada_id))
            .where(CuotaAlumno.colegio_id == colegio_id, CuotaProgramada.vence < hoy,
                   CuotaAlumno.anulada_en.is_(None),
                   CuotaAlumno.pagado < CuotaAlumno.monto - CuotaAlumno.descuento + CuotaAlumno.mora)):
        saldo = situacion(c, vence, cfg, hoy).saldo
        if saldo > 0:
            total += saldo
            alumnos.add(c.alumno_id)
    return total, len(alumnos)
