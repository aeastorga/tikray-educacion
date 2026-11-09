"""Pensiones: configuración del director (mora, avisos, conceptos, montos y cronograma), generación de
cuotas, cuotas por alumno, descuentos y becas, y el reporte de morosidad.

Ver: permiso "pensiones" ver. Configurar, generar y dar descuentos: "pensiones" editar. Con el módulo
apagado todo responde 403. Todo con el colegio del token.
"""

import calendar
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app import excel, pensiones
from app.comun import guardar, obtener
from app.configuracion import anotar
from app.db import get_db
from app.deps import Sesion, requerir_permiso
from app.fechas import hoy_lima
from app.models import (Alumno, AnioEscolar, ConceptoCobro, CuotaAlumno, CuotaProgramada, DescuentoAlumno, Grado,
                        Matricula, MontoConcepto, Nivel, Pago, PagoDetalle, Seccion)
from app.models.pensiones import TIPOS_CONCEPTO
from app.paginacion import Pagina, contar, pagina, recortar
from app.routers.alumnos import _etiquetas_seccion
from app.routers.estructura import anio_o_activo

router = APIRouter(prefix="/pensiones", tags=["pensiones"])
ver = requerir_permiso("pensiones")
editar = requerir_permiso("pensiones", "editar")

Monto = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Setiembre", "Octubre",
         "Noviembre", "Diciembre")
AVISO_MORA = "Confirma la mora y su tope con tu asesor legal antes de activarla."


def s2(valor) -> str:
    """Montos al navegador como texto con dos decimales (nunca float)."""
    return str(pensiones.soles(valor))


def quien(s: Sesion) -> str:
    return f"{s.usuario.nombres} {s.usuario.apellidos}".strip()


# --- Configuración: mora y avisos de cobro ------------------------------------------------------

class ConfigIn(BaseModel):
    mora_tipo: Literal["ninguna", "fijo", "porcentaje"] = "ninguna"
    mora_valor: Monto = Decimal("0")
    mora_tope: Monto | None = None
    dias_aviso_previo: int = Field(default=3, ge=0, le=30)

    @model_validator(mode="after")
    def _validar(self):
        if self.mora_tipo == "porcentaje" and self.mora_valor > 100:
            raise ValueError("El porcentaje de mora no puede pasar de 100")
        if self.mora_tipo != "ninguna" and self.mora_valor <= 0:
            raise ValueError("Indica el monto o el porcentaje de la mora")
        if self.mora_tipo == "ninguna":
            self.mora_valor, self.mora_tope = Decimal("0"), None
        return self


def _config(cfg) -> dict:
    return {"mora_tipo": cfg.mora_tipo, "mora_valor": s2(cfg.mora_valor),
            "mora_tope": s2(cfg.mora_tope) if cfg.mora_tope is not None else None,
            "dias_aviso_previo": cfg.dias_aviso_previo, "serie_recibo": cfg.serie_recibo, "aviso_mora": AVISO_MORA}


@router.get("/config")
def ver_config(s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    cfg = pensiones.config(db, s.colegio.id)
    db.commit()
    return _config(cfg)


@router.put("/config")
def cambiar_config(d: ConfigIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    cfg = pensiones.config(db, s.colegio.id)
    cfg.mora_tipo, cfg.mora_valor, cfg.mora_tope = d.mora_tipo, d.mora_valor, d.mora_tope
    cfg.dias_aviso_previo = d.dias_aviso_previo
    mora = {"ninguna": "sin mora", "fijo": f"mora fija {pensiones.texto_soles(d.mora_valor)}",
            "porcentaje": f"mora {d.mora_valor}% mensual"}[d.mora_tipo]
    if d.mora_tope is not None:
        mora += f", tope {pensiones.texto_soles(d.mora_tope)}"
    anotar(db, s, "editar", "pensiones", "configuracion", s.colegio.id,
           f"Pensiones: {mora}; aviso {d.dias_aviso_previo} días antes")
    return _config(cfg)


# --- Conceptos, montos y cronograma ---------------------------------------------------------------

class ConceptoIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    tipo: Literal["matricula", "pension", "otro"]
    # Por defecto inafecto en matrícula y pensión (Ley del IGV, art. 2, inciso g); gravado en lo demás.
    igv: Literal["gravado", "inafecto"] | None = None
    activo: bool = True

    @model_validator(mode="after")
    def _igv(self):
        self.nombre = " ".join(self.nombre.split())
        if self.igv is None:
            self.igv = "gravado" if self.tipo == "otro" else "inafecto"
        return self


class MontoIn(BaseModel):
    nivel_id: int | None = None
    grado_id: int | None = None
    monto: Monto

    @model_validator(mode="after")
    def _uno(self):
        if (self.nivel_id is None) == (self.grado_id is None):
            raise ValueError("Cada monto es para un nivel o para un grado")
        return self


class MontosIn(BaseModel):
    montos: list[MontoIn] = Field(max_length=200)


class LineaIn(BaseModel):
    numero: int = Field(ge=1, le=24)
    mes: str = Field(min_length=1, max_length=20)
    vence: date

    _mes = field_validator("mes")(classmethod(lambda cls, v: " ".join(v.split())))


class SerieIn(BaseModel):
    """Arma varias líneas de una vez: una por mes, del mes `desde` al `hasta`, venciendo el día `dia`."""
    desde: int = Field(ge=1, le=12)
    hasta: int = Field(ge=1, le=12)
    dia: int = Field(ge=1, le=31)

    @model_validator(mode="after")
    def _orden(self):
        if self.hasta < self.desde:
            raise ValueError("El mes final va después del inicial")
        return self


def _concepto(c: ConceptoCobro, montos: list[MontoConcepto], lineas: list[CuotaProgramada], generadas: int) -> dict:
    return {"id": c.id, "anio_id": c.anio_id, "nombre": c.nombre, "tipo": c.tipo, "igv": c.igv, "activo": c.activo,
            "montos": [{"id": m.id, "nivel_id": m.nivel_id, "grado_id": m.grado_id, "monto": s2(m.monto)}
                       for m in montos],
            "cronograma": [{"id": x.id, "numero": x.numero, "mes": x.mes, "vence": x.vence.isoformat()}
                           for x in sorted(lineas, key=lambda x: x.numero)],
            "cuotas_generadas": generadas}


def _conceptos(db: Session, cid: int, anio_id: int, solo: int | None = None) -> list[dict]:
    q = select(ConceptoCobro).where(ConceptoCobro.colegio_id == cid, ConceptoCobro.anio_id == anio_id)
    if solo is not None:
        q = q.where(ConceptoCobro.id == solo)
    conceptos = db.scalars(q.order_by(ConceptoCobro.tipo, ConceptoCobro.nombre)).all()
    ids = [c.id for c in conceptos]
    montos: dict[int, list] = {}
    lineas: dict[int, list] = {}
    if ids:
        for m in db.scalars(select(MontoConcepto).where(MontoConcepto.colegio_id == cid,
                                                        MontoConcepto.concepto_id.in_(ids))):
            montos.setdefault(m.concepto_id, []).append(m)
        for x in db.scalars(select(CuotaProgramada).where(CuotaProgramada.colegio_id == cid,
                                                          CuotaProgramada.concepto_id.in_(ids))):
            lineas.setdefault(x.concepto_id, []).append(x)
    generadas = dict(db.execute(
        select(CuotaProgramada.concepto_id, func.count(CuotaAlumno.id))
        .join(CuotaAlumno, and_(CuotaAlumno.colegio_id == CuotaProgramada.colegio_id,
                                CuotaAlumno.cuota_programada_id == CuotaProgramada.id))
        .where(CuotaProgramada.colegio_id == cid, CuotaProgramada.concepto_id.in_(ids))
        .group_by(CuotaProgramada.concepto_id)).all()) if ids else {}
    orden = {t: i for i, t in enumerate(TIPOS_CONCEPTO)}
    salida = [_concepto(c, montos.get(c.id, []), lineas.get(c.id, []), generadas.get(c.id, 0)) for c in conceptos]
    return sorted(salida, key=lambda c: (orden[c["tipo"]], c["nombre"]))


@router.get("/conceptos")
def conceptos(anio_id: int | None = None, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    niveles = db.scalars(select(Nivel).where(Nivel.colegio_id == cid).order_by(Nivel.orden, Nivel.nombre)).all()
    grados = db.scalars(select(Grado).where(Grado.colegio_id == cid).order_by(Grado.orden, Grado.nombre)).all()
    return {"anio": {"id": anio.id, "anio": anio.anio, "inicio": anio.inicio.isoformat(), "fin": anio.fin.isoformat(),
                     "vence_desde": desde_vencimiento(anio.inicio).isoformat()},
            "conceptos": _conceptos(db, cid, anio.id),
            "niveles": [{"id": n.id, "nombre": n.nombre,
                         "grados": [{"id": g.id, "nombre": g.nombre} for g in grados if g.nivel_id == n.id]}
                        for n in niveles]}


@router.post("/conceptos", status_code=201)
def crear_concepto(d: ConceptoIn, anio_id: int | None = None, s: Sesion = Depends(editar),
                   db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    c = ConceptoCobro(colegio_id=cid, anio_id=anio.id, nombre=d.nombre, tipo=d.tipo, igv=d.igv, activo=d.activo)
    db.add(c)
    guardar(db, "Ya hay un concepto con ese nombre en el año", solo_flush=True)
    anotar(db, s, "crear", "pensiones", "concepto", c, f"Concepto «{c.nombre}» ({c.tipo}, {c.igv}) del {anio.anio}")
    return _conceptos(db, cid, anio.id, c.id)[0]


@router.put("/conceptos/{concepto_id}")
def editar_concepto(concepto_id: int, d: ConceptoIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    c = obtener(db, ConceptoCobro, cid, concepto_id, "Concepto")
    c.nombre, c.tipo, c.igv, c.activo = d.nombre, d.tipo, d.igv, d.activo
    anotar(db, s, "editar", "pensiones", "concepto", c,
           f"Concepto «{c.nombre}» ({c.tipo}, {c.igv}{'' if c.activo else ', desactivado'})",
           "Ya hay un concepto con ese nombre en el año")
    return _conceptos(db, cid, c.anio_id, c.id)[0]


def _sin_cuotas(db: Session, cid: int, concepto_id: int | None = None, linea_id: int | None = None) -> None:
    q = (select(CuotaAlumno.id)
         .join(CuotaProgramada, and_(CuotaProgramada.colegio_id == CuotaAlumno.colegio_id,
                                     CuotaProgramada.id == CuotaAlumno.cuota_programada_id))
         .where(CuotaAlumno.colegio_id == cid))
    q = q.where(CuotaProgramada.concepto_id == concepto_id) if concepto_id else q.where(CuotaProgramada.id == linea_id)
    if db.scalar(q.limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Ya se generaron cuotas con esto: no se borra (desactiva el concepto si ya no se cobra)")


@router.delete("/conceptos/{concepto_id}", status_code=204)
def borrar_concepto(concepto_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> None:
    """Solo si todavía no se generaron cuotas con él (las cuotas son dinero: no se borran)."""
    cid = s.colegio.id
    c = obtener(db, ConceptoCobro, cid, concepto_id, "Concepto")
    _sin_cuotas(db, cid, concepto_id=c.id)
    for x in db.scalars(select(CuotaProgramada).where(CuotaProgramada.colegio_id == cid,
                                                      CuotaProgramada.concepto_id == c.id)):
        db.delete(x)
    db.flush()
    anotar(db, s, "anular", "pensiones", "concepto", c.id, f"Borró el concepto «{c.nombre}»")
    db.delete(c)
    guardar(db)


@router.put("/conceptos/{concepto_id}/montos")
def cambiar_montos(concepto_id: int, d: MontosIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Reemplaza los montos del concepto. Las cuotas ya generadas no cambian (solo las nuevas)."""
    cid = s.colegio.id
    c = obtener(db, ConceptoCobro, cid, concepto_id, "Concepto")
    grados = [m.grado_id for m in d.montos if m.grado_id]
    niveles = [m.nivel_id for m in d.montos if m.nivel_id]
    if len(grados) != len(set(grados)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Hay dos montos para el mismo grado")
    if len(niveles) != len(set(niveles)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Hay dos montos para el mismo nivel")
    for g in set(grados):
        obtener(db, Grado, cid, g, "Grado")
    for n in set(niveles):
        obtener(db, Nivel, cid, n, "Nivel")
    for m in db.scalars(select(MontoConcepto).where(MontoConcepto.colegio_id == cid,
                                                    MontoConcepto.concepto_id == c.id)):
        db.delete(m)
    db.flush()
    db.add_all([MontoConcepto(colegio_id=cid, concepto_id=c.id, nivel_id=m.nivel_id, grado_id=m.grado_id,
                              monto=m.monto) for m in d.montos])
    anotar(db, s, "editar", "pensiones", "concepto", c, f"Montos de «{c.nombre}»: {len(d.montos)}",
           "Hay dos montos para el mismo grado o nivel")
    return _conceptos(db, cid, c.anio_id, c.id)[0]


MESES_ANTES = 3  # la matrícula puede vencer hasta 3 meses antes del inicio de clases


def desde_vencimiento(inicio: date) -> date:
    """Inicio del año escolar menos 3 meses de calendario (si el día no existe, el último del mes)."""
    total = inicio.year * 12 + inicio.month - 1 - MESES_ANTES
    anio, mes = divmod(total, 12)
    return date(anio, mes + 1, min(inicio.day, calendar.monthrange(anio, mes + 1)[1]))


def _dentro_del_anio(db: Session, c: ConceptoCobro, vence: date) -> None:
    anio = db.get(AnioEscolar, c.anio_id)
    desde = desde_vencimiento(anio.inicio)
    if not desde <= vence <= anio.fin:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"El vencimiento va del {desde:%d/%m/%Y} (3 meses antes del inicio de clases) al "
                            f"{anio.fin:%d/%m/%Y} (fin del año escolar)")


@router.post("/conceptos/{concepto_id}/cronograma", status_code=201)
def agregar_linea(concepto_id: int, d: LineaIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    c = obtener(db, ConceptoCobro, cid, concepto_id, "Concepto")
    _dentro_del_anio(db, c, d.vence)
    x = CuotaProgramada(colegio_id=cid, concepto_id=c.id, numero=d.numero, mes=d.mes, vence=d.vence)
    db.add(x)
    guardar(db, "Ya hay una cuota con ese número", solo_flush=True)
    anotar(db, s, "crear", "pensiones", "cronograma", x, f"Cronograma «{c.nombre}»: cuota {x.numero} ({x.mes}), "
                                                        f"vence {x.vence:%d/%m/%Y}")
    return _conceptos(db, cid, c.anio_id, c.id)[0]


@router.post("/conceptos/{concepto_id}/cronograma/serie", status_code=201)
def armar_serie(concepto_id: int, d: SerieIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Una línea por mes (p. ej. de marzo a diciembre), con el día de vencimiento (o el último del mes, si
    ese mes no tiene ese día). Sigue la numeración que ya tenga el concepto."""
    cid = s.colegio.id
    c = obtener(db, ConceptoCobro, cid, concepto_id, "Concepto")
    anio = db.get(AnioEscolar, c.anio_id)
    numero = db.scalar(select(func.max(CuotaProgramada.numero)).where(
        CuotaProgramada.colegio_id == cid, CuotaProgramada.concepto_id == c.id)) or 0
    if numero + d.hasta - d.desde + 1 > 24:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Un concepto tiene hasta 24 cuotas")
    for mes in range(d.desde, d.hasta + 1):
        vence = date(anio.anio, mes, min(d.dia, calendar.monthrange(anio.anio, mes)[1]))
        _dentro_del_anio(db, c, vence)
        numero += 1
        db.add(CuotaProgramada(colegio_id=cid, concepto_id=c.id, numero=numero, mes=MESES[mes - 1], vence=vence))
    anotar(db, s, "crear", "pensiones", "cronograma", c.id,
           f"Cronograma «{c.nombre}»: {MESES[d.desde - 1]} a {MESES[d.hasta - 1]}, vence el día {d.dia}",
           "Ya hay una cuota con ese número")
    return _conceptos(db, cid, c.anio_id, c.id)[0]


@router.put("/cronograma/{linea_id}")
def editar_linea(linea_id: int, d: LineaIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Cambiar el vencimiento vale también para las cuotas ya generadas."""
    cid = s.colegio.id
    x = obtener(db, CuotaProgramada, cid, linea_id, "Cuota del cronograma")
    c = db.get(ConceptoCobro, x.concepto_id)
    _dentro_del_anio(db, c, d.vence)
    x.numero, x.mes, x.vence = d.numero, d.mes, d.vence
    anotar(db, s, "editar", "pensiones", "cronograma", x, f"Cronograma «{c.nombre}»: cuota {x.numero} ({x.mes}), "
                                                         f"vence {x.vence:%d/%m/%Y}", "Ya hay una cuota con ese número")
    return _conceptos(db, cid, c.anio_id, c.id)[0]


@router.delete("/cronograma/{linea_id}", status_code=204)
def borrar_linea(linea_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> None:
    cid = s.colegio.id
    x = obtener(db, CuotaProgramada, cid, linea_id, "Cuota del cronograma")
    _sin_cuotas(db, cid, linea_id=x.id)
    c = db.get(ConceptoCobro, x.concepto_id)
    anotar(db, s, "anular", "pensiones", "cronograma", x.id, f"Cronograma «{c.nombre}»: borró la cuota {x.numero}")
    db.delete(x)
    guardar(db)


# --- Generar cuotas ----------------------------------------------------------------------------

@router.post("/generar")
def generar(anio_id: int | None = None, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Crea las cuotas que falten (alumnos matriculados y activos). Repetirlo no duplica."""
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    r = pensiones.generar_cuotas(db, cid, anio.id)
    anotar(db, s, "crear", "pensiones", "cuotas", anio.id,
           f"Generó {r['creadas']} cuotas del {anio.anio}" + (f" ({r['sin_monto']} alumnos sin monto)"
                                                              if r["sin_monto"] else ""))
    return r


# --- Cuotas por alumno ------------------------------------------------------------------------

@router.get("/secciones")
def secciones(anio_id: int | None = None, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> list[dict]:
    """Para filtrar por sección sin necesitar el permiso del padrón."""
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    filas = db.execute(select(Seccion.id).join(Grado, and_(Grado.colegio_id == Seccion.colegio_id,
                                                           Grado.id == Seccion.grado_id))
                       .join(Nivel, and_(Nivel.colegio_id == Grado.colegio_id, Nivel.id == Grado.nivel_id))
                       .where(Seccion.colegio_id == cid, Seccion.anio_id == anio.id)
                       .order_by(Nivel.orden, Grado.orden, Grado.nombre, Seccion.nombre)).scalars().all()
    etiquetas = _etiquetas_seccion(db, cid, set(filas))
    return [{"id": i, "nombre": etiquetas[i]} for i in filas]


def cuotas_de_alumno(db: Session, cid: int, alumno_id: int, anio_id: int | None = None) -> list[dict]:
    """Las cuotas de un alumno (de un año o de todos), con su situación de hoy y lo pagado."""
    cfg = pensiones.config(db, cid)
    hoy = hoy_lima()
    q = (select(CuotaAlumno, CuotaProgramada, ConceptoCobro, AnioEscolar.anio)
         .join(CuotaProgramada, and_(CuotaProgramada.colegio_id == CuotaAlumno.colegio_id,
                                     CuotaProgramada.id == CuotaAlumno.cuota_programada_id))
         .join(ConceptoCobro, and_(ConceptoCobro.colegio_id == CuotaProgramada.colegio_id,
                                   ConceptoCobro.id == CuotaProgramada.concepto_id))
         .join(AnioEscolar, and_(AnioEscolar.colegio_id == ConceptoCobro.colegio_id,
                                 AnioEscolar.id == ConceptoCobro.anio_id))
         .where(CuotaAlumno.colegio_id == cid, CuotaAlumno.alumno_id == alumno_id))
    if anio_id is not None:
        q = q.where(ConceptoCobro.anio_id == anio_id)
    salida = []
    for c, prog, concepto, anio in db.execute(q.order_by(AnioEscolar.anio, CuotaProgramada.vence, ConceptoCobro.tipo,
                                                          CuotaProgramada.numero)):
        sit = pensiones.situacion(c, prog.vence, cfg, hoy)
        salida.append({"id": c.id, "anio": anio, "concepto_id": concepto.id, "concepto": concepto.nombre,
                       "tipo": concepto.tipo, "numero": prog.numero, "mes": prog.mes, "vence": prog.vence.isoformat(),
                       "monto": s2(c.monto), "descuento": s2(c.descuento), "mora": s2(sit.mora),
                       "pagado": s2(c.pagado), "saldo": s2(sit.saldo), "estado": sit.estado,
                       "dias_atraso": sit.dias_atraso, "anulada_motivo": c.anulada_motivo})
    return salida


def pagos_de_alumno(db: Session, cid: int, alumno_id: int) -> list[dict]:
    pagos = db.scalars(select(Pago).where(Pago.colegio_id == cid, Pago.alumno_id == alumno_id)
                       .order_by(Pago.momento.desc())).all()
    detalles: dict[int, list] = {}
    if pagos:
        for d, prog, concepto in db.execute(
                select(PagoDetalle, CuotaProgramada, ConceptoCobro)
                .join(CuotaAlumno, and_(CuotaAlumno.colegio_id == PagoDetalle.colegio_id,
                                        CuotaAlumno.id == PagoDetalle.cuota_id))
                .join(CuotaProgramada, and_(CuotaProgramada.colegio_id == CuotaAlumno.colegio_id,
                                            CuotaProgramada.id == CuotaAlumno.cuota_programada_id))
                .join(ConceptoCobro, and_(ConceptoCobro.colegio_id == CuotaProgramada.colegio_id,
                                          ConceptoCobro.id == CuotaProgramada.concepto_id))
                .where(PagoDetalle.colegio_id == cid, PagoDetalle.pago_id.in_([p.id for p in pagos]))):
            detalles.setdefault(d.pago_id, []).append(f"{concepto.nombre} {prog.mes}")
    return [{"id": p.id, "recibo": f"{p.serie}-{p.correlativo:06d}", "fecha": p.fecha.isoformat(),
             "momento": p.momento.isoformat(), "medio": p.medio, "numero_operacion": p.numero_operacion,
             "total": s2(p.total), "cajero": p.cajero, "anulado": p.anulado_en is not None,
             "anulado_motivo": p.anulado_motivo, "cuotas": detalles.get(p.id, [])} for p in pagos]


def _saldo_sql():
    """Cuotas con saldo (exacto: la mora del día solo crece mientras la cuota sin mora no esté pagada)."""
    return and_(CuotaAlumno.anulada_en.is_(None),
                CuotaAlumno.pagado < CuotaAlumno.monto - CuotaAlumno.descuento + CuotaAlumno.mora)


@router.get("/alumnos")
def alumnos(anio_id: int | None = None, seccion_id: int | None = None, q: str | None = None,
            estado: Literal["con_deuda_vencida", "al_dia"] | None = None, p: Pagina = Depends(pagina),
            s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    """Alumnos del año con el resumen de sus cuotas: total, pagado, saldo y deuda vencida."""
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    hoy = hoy_lima()
    vencida = (select(CuotaAlumno.alumno_id)
               .join(CuotaProgramada, and_(CuotaProgramada.colegio_id == CuotaAlumno.colegio_id,
                                           CuotaProgramada.id == CuotaAlumno.cuota_programada_id))
               .join(ConceptoCobro, and_(ConceptoCobro.colegio_id == CuotaProgramada.colegio_id,
                                         ConceptoCobro.id == CuotaProgramada.concepto_id))
               .where(CuotaAlumno.colegio_id == cid, ConceptoCobro.anio_id == anio.id, CuotaProgramada.vence < hoy,
                      _saldo_sql()))
    consulta = (select(Alumno, Matricula.seccion_id)
                .join(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id, Matricula.alumno_id == Alumno.id,
                                      Matricula.anio_id == anio.id))
                .where(Alumno.colegio_id == cid))
    if seccion_id is not None:
        consulta = consulta.where(Matricula.seccion_id == seccion_id)
    if estado == "con_deuda_vencida":
        consulta = consulta.where(Alumno.id.in_(vencida))
    elif estado == "al_dia":
        consulta = consulta.where(Alumno.id.not_in(vencida))
    if q and q.strip():
        patron = f"%{q.strip()}%"
        consulta = consulta.where(or_(Alumno.apellidos.ilike(patron), Alumno.nombres.ilike(patron),
                                      Alumno.numero_documento.ilike(patron)))
    total = contar(db, consulta)
    filas = db.execute(recortar(consulta.order_by(Alumno.apellidos, Alumno.nombres, Alumno.id), p)).all()
    etiquetas = _etiquetas_seccion(db, cid, {sid for _, sid in filas if sid})
    items = []
    for a, sid in filas:
        cuotas = [c for c in cuotas_de_alumno(db, cid, a.id, anio.id) if c["estado"] != "anulada"]
        deber = sum((Decimal(c["monto"]) - Decimal(c["descuento"]) + Decimal(c["mora"]) for c in cuotas), Decimal(0))
        vencidas = [c for c in cuotas if c["estado"] == "vencida"]
        items.append({"id": a.id, "nombres": a.nombres, "apellidos": a.apellidos, "activo": a.activo,
                      "numero_documento": a.numero_documento, "seccion": etiquetas.get(sid),
                      "cuotas": len(cuotas), "total": s2(deber),
                      "pagado": s2(sum((Decimal(c["pagado"]) for c in cuotas), Decimal(0))),
                      "saldo": s2(sum((Decimal(c["saldo"]) for c in cuotas), Decimal(0))),
                      "vencido": s2(sum((Decimal(c["saldo"]) for c in vencidas), Decimal(0))),
                      "cuotas_vencidas": len(vencidas)})
    return {**p.datos(total), "anio": anio.anio, "items": items}


@router.get("/alumnos/{alumno_id}")
def alumno(alumno_id: int, anio_id: int | None = None, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    a = obtener(db, Alumno, cid, alumno_id, "Alumno")
    nombres = dict(db.execute(select(ConceptoCobro.id, ConceptoCobro.nombre).where(ConceptoCobro.colegio_id == cid)).all())
    return {"id": a.id, "nombres": a.nombres, "apellidos": a.apellidos, "activo": a.activo,
            "numero_documento": a.numero_documento, "cuotas": cuotas_de_alumno(db, cid, a.id, anio_id),
            "pagos": pagos_de_alumno(db, cid, a.id),
            "descuentos": [_descuento(d, None, nombres.get(d.concepto_id)) for d in db.scalars(
                select(DescuentoAlumno).where(DescuentoAlumno.colegio_id == cid, DescuentoAlumno.alumno_id == a.id)
                .order_by(DescuentoAlumno.creado_en.desc()))]}


# --- Descuentos y becas -------------------------------------------------------------------------

class DescuentoIn(BaseModel):
    alumno_id: int
    concepto_id: int | None = None  # vacío: todos los conceptos
    tipo: Literal["porcentaje", "monto"]
    valor: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
    motivo: str = Field(min_length=3, max_length=200)

    @model_validator(mode="after")
    def _validar(self):
        self.motivo = " ".join(self.motivo.split())
        if self.tipo == "porcentaje" and self.valor > 100:
            raise ValueError("El descuento no puede pasar de 100 %")
        return self


class AnularIn(BaseModel):
    motivo: str = Field(min_length=3, max_length=200)

    _motivo = field_validator("motivo")(classmethod(lambda cls, v: " ".join(v.split())))


def _descuento(d: DescuentoAlumno, alumno: Alumno | None, concepto: str | None) -> dict:
    return {"id": d.id, "alumno_id": d.alumno_id,
            "alumno": f"{alumno.apellidos}, {alumno.nombres}" if alumno else None,
            "concepto_id": d.concepto_id, "concepto": concepto, "tipo": d.tipo, "valor": s2(d.valor),
            "motivo": d.motivo, "dado_por": d.dado_por, "creado_en": d.creado_en.isoformat(),
            "anulado": d.anulado_en is not None, "anulado_motivo": d.anulado_motivo}


@router.get("/descuentos")
def descuentos(anio_id: int | None = None, q: str | None = None, p: Pagina = Depends(pagina),
               s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    consulta = (select(DescuentoAlumno, Alumno, ConceptoCobro.nombre)
                .join(Alumno, and_(Alumno.colegio_id == DescuentoAlumno.colegio_id,
                                   Alumno.id == DescuentoAlumno.alumno_id))
                .outerjoin(ConceptoCobro, and_(ConceptoCobro.colegio_id == DescuentoAlumno.colegio_id,
                                               ConceptoCobro.id == DescuentoAlumno.concepto_id))
                .where(DescuentoAlumno.colegio_id == cid, DescuentoAlumno.anio_id == anio.id))
    if q and q.strip():
        patron = f"%{q.strip()}%"
        consulta = consulta.where(or_(Alumno.apellidos.ilike(patron), Alumno.nombres.ilike(patron),
                                      Alumno.numero_documento.ilike(patron)))
    total = contar(db, consulta)
    filas = db.execute(recortar(consulta.order_by(DescuentoAlumno.anulado_en.is_not(None), Alumno.apellidos,
                                                  Alumno.nombres, DescuentoAlumno.id), p)).all()
    return {**p.datos(total), "items": [_descuento(d, a, c) for d, a, c in filas]}


@router.post("/descuentos", status_code=201)
def dar_descuento(d: DescuentoIn, anio_id: int | None = None, s: Sesion = Depends(editar),
                  db: Session = Depends(get_db)) -> dict:
    """Se aplica a las cuotas del año que aún no tienen pagos. Tope: 100 %."""
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    a = obtener(db, Alumno, cid, d.alumno_id, "Alumno")
    concepto = None
    if d.concepto_id is not None:
        concepto = obtener(db, ConceptoCobro, cid, d.concepto_id, "Concepto")
        if concepto.anio_id != anio.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El concepto es de otro año escolar")
    if d.tipo == "porcentaje":
        ya = pensiones.porcentaje_acumulado(db, cid, a.id, anio.id, d.concepto_id)
        if d.concepto_id is None:  # "todos" se suma a cada concepto con descuento propio
            ya = max([ya] + [pensiones.porcentaje_acumulado(db, cid, a.id, anio.id, c) for c in db.scalars(
                select(DescuentoAlumno.concepto_id).where(
                    DescuentoAlumno.colegio_id == cid, DescuentoAlumno.alumno_id == a.id,
                    DescuentoAlumno.anio_id == anio.id, DescuentoAlumno.anulado_en.is_(None),
                    DescuentoAlumno.concepto_id.is_not(None)).distinct())])
        if ya + d.valor > 100:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                f"Con este descuento pasaría de 100 % (ya tiene {ya:g} %)")
    x = DescuentoAlumno(colegio_id=cid, anio_id=anio.id, alumno_id=a.id, concepto_id=d.concepto_id, tipo=d.tipo,
                        valor=d.valor, motivo=d.motivo, dado_por_id=s.usuario.id, dado_por=quien(s))
    db.add(x)
    db.flush()
    cambiadas = pensiones.recalcular_alumno(db, cid, a.id, anio.id)
    valor = f"{d.valor:g} %" if d.tipo == "porcentaje" else pensiones.texto_soles(d.valor)
    anotar(db, s, "crear", "pensiones", "descuento", x,
           f"Descuento {valor} a {a.apellidos}, {a.nombres} en {concepto.nombre if concepto else 'todo'} "
           f"({cambiadas} cuotas)")
    return _descuento(x, a, concepto.nombre if concepto else None) | {"cuotas_actualizadas": cambiadas}


@router.post("/descuentos/{descuento_id}/anular")
def anular_descuento(descuento_id: int, d: AnularIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Deja de aplicarse a las cuotas que aún no tienen pagos; queda en la lista como anulado."""
    cid = s.colegio.id
    x = obtener(db, DescuentoAlumno, cid, descuento_id, "Descuento")
    if x.anulado_en is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese descuento ya está anulado")
    x.anulado_en, x.anulado_motivo, x.anulado_por = datetime.now(UTC), d.motivo, quien(s)
    db.flush()
    cambiadas = pensiones.recalcular_alumno(db, cid, x.alumno_id, x.anio_id)
    a = db.get(Alumno, x.alumno_id)
    anotar(db, s, "anular", "pensiones", "descuento", x, f"Anuló un descuento de {a.apellidos}, {a.nombres} "
                                                        f"({cambiadas} cuotas)")
    return _descuento(x, a, None) | {"cuotas_actualizadas": cambiadas}


# --- Morosidad ---------------------------------------------------------------------------------

def morosidad_filas(db: Session, cid: int, anio: AnioEscolar, seccion_id: int | None = None) -> list[dict]:
    """Alumnos con cuotas vencidas y con saldo, por sección: cuántas, cuánto y días de atraso (la más antigua)."""
    cfg = pensiones.config(db, cid)
    hoy = hoy_lima()
    q = (select(CuotaAlumno, CuotaProgramada.vence, Alumno, Matricula.seccion_id)
         .join(CuotaProgramada, and_(CuotaProgramada.colegio_id == CuotaAlumno.colegio_id,
                                     CuotaProgramada.id == CuotaAlumno.cuota_programada_id))
         .join(ConceptoCobro, and_(ConceptoCobro.colegio_id == CuotaProgramada.colegio_id,
                                   ConceptoCobro.id == CuotaProgramada.concepto_id))
         .join(Alumno, and_(Alumno.colegio_id == CuotaAlumno.colegio_id, Alumno.id == CuotaAlumno.alumno_id))
         .outerjoin(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id, Matricula.alumno_id == Alumno.id,
                                    Matricula.anio_id == anio.id))
         .where(CuotaAlumno.colegio_id == cid, ConceptoCobro.anio_id == anio.id, CuotaProgramada.vence < hoy,
                _saldo_sql()))
    if seccion_id is not None:
        q = q.where(Matricula.seccion_id == seccion_id)
    por_alumno: dict[int, dict] = {}
    for c, vence, a, sid in db.execute(q):
        sit = pensiones.situacion(c, vence, cfg, hoy)
        if sit.saldo <= 0:
            continue
        f = por_alumno.setdefault(a.id, {"alumno_id": a.id, "alumno": f"{a.apellidos}, {a.nombres}",
                                         "activo": a.activo, "seccion_id": sid, "cuotas": 0, "monto": Decimal(0),
                                         "dias": 0})
        f["cuotas"] += 1
        f["monto"] += sit.saldo
        f["dias"] = max(f["dias"], sit.dias_atraso)
    etiquetas = _etiquetas_seccion(db, cid, {f["seccion_id"] for f in por_alumno.values() if f["seccion_id"]})
    filas = [f | {"seccion": etiquetas.get(f["seccion_id"], "Sin sección")} for f in por_alumno.values()]
    return sorted(filas, key=lambda f: (f["seccion"], f["alumno"]))


@router.get("/morosidad")
def morosidad(anio_id: int | None = None, seccion_id: int | None = None, p: Pagina = Depends(pagina),
              s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    filas = morosidad_filas(db, cid, anio, seccion_id)
    total_monto = sum((f["monto"] for f in filas), Decimal(0))
    pagina_filas = filas[p.desde:p.desde + p.por_pagina]
    return {**p.datos(len(filas)), "anio": anio.anio, "monto_total": s2(total_monto),
            "items": [f | {"monto": s2(f["monto"])} for f in pagina_filas]}


@router.get("/morosidad.xlsx")
def morosidad_excel(anio_id: int | None = None, seccion_id: int | None = None, s: Sesion = Depends(ver),
                    db: Session = Depends(get_db)) -> Response:
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    if seccion_id is not None:
        obtener(db, Seccion, cid, seccion_id, "Sección")
    filas = morosidad_filas(db, cid, anio, seccion_id)
    return excel.tabla(f"Morosidad {anio.anio} · {s.colegio.nombre}",
                       ["Sección", "Alumno", "Cuotas vencidas", "Monto (S/)", "Días de atraso"],
                       [[f["seccion"], f["alumno"] + ("" if f["activo"] else " (retirado)"), f["cuotas"],
                         pensiones.soles(f["monto"]), f["dias"]] for f in filas],
                       f"morosidad-{anio.anio}.xlsx", s.colegio.color_primario, soles=(3,))
