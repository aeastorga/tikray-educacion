"""Caja: la caja del día de cada cajero, cobros con recibo interno, anulaciones, cierre, gastos y reportes
de ingresos y gastos.

Ver: permiso "caja" ver. Abrir, cobrar, cerrar y registrar gastos: "caja" editar. Anular pide además
"caja" editar y:
- un pago con la caja abierta: el cajero que cobró, el director o un rol con "puede anular" (casilla del rol);
- un pago con la caja cerrada: solo el director o un rol con "puede anular";
- un gasto del día (Lima): quien lo registró, el director o un rol con "puede anular";
- un gasto de un día anterior: solo el director o un rol con "puede anular".
Con el módulo apagado todo responde 403. Nada de dinero se borra: solo se anula.

Comprobantes electrónicos (si el colegio emite con un proveedor): el cobro crea la boleta (al responsable
de pago) o la factura (si el cajero la pide con RUC y razón social) en "pendiente" y responde sin esperar
al proveedor. Anular el pago encola la anulación del comprobante. El recibo interno se entrega siempre.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app import excel, facturacion, pdf, pensiones
from app.almacenamiento import get_almacenamiento_privado
from app.comun import guardar, obtener
from app.configuracion import anotar
from app.db import get_db
from app.deps import Sesion, requerir_permiso
from app.fechas import hoy_lima
from app.models import (Alumno, AnioEscolar, CajaSesion, CategoriaGasto, ColaComprobante, Comprobante,
                        ConceptoCobro, CuotaAlumno, CuotaProgramada, Gasto, Matricula, Pago, PagoDetalle)
from app.models.pensiones import MEDIOS
from app.paginacion import Pagina, contar, pagina, recortar
from app.routers.alumnos import _etiquetas_seccion
from app.routers.importacion import imagen_pdf
from app.routers.pensiones import AnularIn, cuotas_de_alumno, pagos_de_alumno, quien, s2

router = APIRouter(prefix="/caja", tags=["caja"])
ver = requerir_permiso("caja")
editar = requerir_permiso("caja", "editar")

Medio = Literal["efectivo", "yape", "plin", "transferencia", "tarjeta"]
NOMBRE_MEDIO = {"efectivo": "Efectivo", "yape": "Yape", "plin": "Plin", "transferencia": "Transferencia",
                "tarjeta": "Tarjeta"}
MAX_ARCHIVO = 5 * 1024 * 1024
TIPOS_ARCHIVO = {"application/pdf": b"%PDF", "image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n",
                 "image/webp": b"RIFF"}


SOLO_AUTORIZADOS = "solo lo anulan el director o un rol con permiso para anular"


def anula_todo(s: Sesion) -> bool:
    """Director o rol con la casilla "Puede anular pagos de caja cerrada y gastos de días anteriores"."""
    return s.usuario.rol.es_director or s.usuario.rol.puede_anular_caja


def numero_recibo(p: Pago) -> str:
    return f"{p.serie}-{p.correlativo:06d}"


# --- Caja del día ----------------------------------------------------------------------------

def _totales(db: Session, cid: int, caja_id: int) -> dict[str, Decimal]:
    filas = dict(db.execute(select(Pago.medio, func.sum(Pago.total)).where(
        Pago.colegio_id == cid, Pago.caja_id == caja_id, Pago.anulado_en.is_(None)).group_by(Pago.medio)).all())
    return {m: pensiones.soles(filas.get(m, 0)) for m in MEDIOS}


def _caja(db: Session, c: CajaSesion) -> dict:
    totales = _totales(db, c.colegio_id, c.id) if c.cerrada_en is None else {
        m: Decimal(v) for m, v in (c.totales or {}).items()}
    pagos = db.scalar(select(func.count()).select_from(Pago).where(
        Pago.colegio_id == c.colegio_id, Pago.caja_id == c.id, Pago.anulado_en.is_(None))) or 0
    efectivo = totales.get("efectivo", Decimal(0))
    return {"id": c.id, "usuario_id": c.usuario_id, "cajero": c.cajero, "fecha": c.fecha.isoformat(),
            "abierta_en": c.abierta_en.isoformat(), "cerrada_en": c.cerrada_en.isoformat() if c.cerrada_en else None,
            "abierta": c.cerrada_en is None, "pagos": pagos,
            "totales": {m: s2(v) for m, v in totales.items()},
            "total": s2(sum(totales.values(), Decimal(0))),
            "contado": s2(c.contado) if c.contado is not None else None,
            "diferencia": s2(c.contado - efectivo) if c.contado is not None else None}


def _caja_abierta(db: Session, s: Sesion, bloquear: bool = False) -> CajaSesion | None:
    q = select(CajaSesion).where(CajaSesion.colegio_id == s.colegio.id, CajaSesion.usuario_id == s.usuario.id,
                                 CajaSesion.cerrada_en.is_(None))
    return db.scalar(q.with_for_update() if bloquear else q)


@router.get("/mi-caja")
def mi_caja(s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    c = _caja_abierta(db, s)
    return {"caja": _caja(db, c) if c else None, "hoy": hoy_lima().isoformat(),
            "comprobantes": facturacion.activa(db, s.colegio.id) is not None}


@router.post("/abrir", status_code=201)
def abrir(s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    if _caja_abierta(db, s):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya tienes una caja abierta")
    c = CajaSesion(colegio_id=s.colegio.id, usuario_id=s.usuario.id, cajero=quien(s), fecha=hoy_lima())
    db.add(c)
    guardar(db, "Ya tienes una caja abierta", solo_flush=True)
    anotar(db, s, "crear", "caja", "caja", c, f"Abrió su caja del {c.fecha:%d/%m/%Y}", "Ya tienes una caja abierta")
    return _caja(db, c)


class CierreIn(BaseModel):
    contado: Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]


@router.post("/cerrar")
def cerrar(d: CierreIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Guarda los totales por medio, el efectivo que contó el cajero y la diferencia. Cerrada, no admite
    pagos nuevos ni anulaciones del cajero."""
    c = _caja_abierta(db, s, bloquear=True)
    if c is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No tienes una caja abierta")
    totales = _totales(db, s.colegio.id, c.id)
    c.totales = {m: str(v) for m, v in totales.items()}
    c.contado, c.cerrada_en = d.contado, datetime.now(UTC)
    diferencia = d.contado - totales["efectivo"]
    anotar(db, s, "editar", "caja", "caja", c,
           f"Cerró su caja del {c.fecha:%d/%m/%Y}: total {pensiones.texto_soles(sum(totales.values(), Decimal(0)))}, "
           f"efectivo contado {pensiones.texto_soles(d.contado)} (diferencia {pensiones.texto_soles(diferencia)})")
    return _caja(db, c)


@router.get("/cajas")
def cajas(desde: date | None = None, hasta: date | None = None, usuario_id: int | None = None,
          p: Pagina = Depends(pagina), s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    q = select(CajaSesion).where(CajaSesion.colegio_id == cid)
    if desde:
        q = q.where(CajaSesion.fecha >= desde)
    if hasta:
        q = q.where(CajaSesion.fecha <= hasta)
    if usuario_id is not None:
        q = q.where(CajaSesion.usuario_id == usuario_id)
    total = contar(db, q)
    filas = db.scalars(recortar(q.order_by(CajaSesion.abierta_en.desc(), CajaSesion.id.desc()), p)).all()
    return {**p.datos(total), "items": [_caja(db, c) for c in filas]}


# --- Cobrar ---------------------------------------------------------------------------------

@router.get("/alumnos")
def buscar_alumnos(q: str = Query(min_length=2, max_length=60), s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> list[dict]:
    """Para elegir a quién cobrar: por apellidos, nombres o documento (hasta 10)."""
    cid = s.colegio.id
    patron = f"%{q.strip()}%"
    anio = select(AnioEscolar.id).where(AnioEscolar.colegio_id == cid, AnioEscolar.activo).scalar_subquery()
    filas = db.execute(
        select(Alumno, Matricula.seccion_id)
        .outerjoin(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id, Matricula.alumno_id == Alumno.id,
                                   Matricula.anio_id == anio))
        .where(Alumno.colegio_id == cid, or_(Alumno.apellidos.ilike(patron), Alumno.nombres.ilike(patron),
                                             Alumno.numero_documento.ilike(patron)))
        .order_by(Alumno.apellidos, Alumno.nombres).limit(10)).all()
    etiquetas = _etiquetas_seccion(db, cid, {sid for _, sid in filas if sid})
    return [{"id": a.id, "nombres": a.nombres, "apellidos": a.apellidos, "numero_documento": a.numero_documento,
             "activo": a.activo, "seccion": etiquetas.get(sid)} for a, sid in filas]


@router.get("/alumnos/{alumno_id}")
def alumno(alumno_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    """Las cuotas del alumno (de todos los años: una deuda antigua también se cobra) y sus pagos."""
    cid = s.colegio.id
    a = obtener(db, Alumno, cid, alumno_id, "Alumno")
    return {"id": a.id, "nombres": a.nombres, "apellidos": a.apellidos, "numero_documento": a.numero_documento,
            "activo": a.activo, "cuotas": cuotas_de_alumno(db, cid, a.id), "pagos": pagos_de_alumno(db, cid, a.id)}


class DetalleIn(BaseModel):
    cuota_id: int
    monto: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]


class FacturaIn(BaseModel):
    """E1: factura solo si el cajero la elige y escribe RUC y razón social."""

    ruc: str = Field(max_length=20)
    razon_social: str = Field(min_length=1, max_length=200)

    _ruc = field_validator("ruc")(classmethod(lambda cls, v: v.strip()))

    _razon = field_validator("razon_social")(classmethod(lambda cls, v: " ".join(v.split())))


class PagoIn(BaseModel):
    alumno_id: int
    medio: Medio
    numero_operacion: str | None = Field(default=None, max_length=40)
    detalles: list[DetalleIn] = Field(min_length=1, max_length=60)
    factura: FacturaIn | None = None

    @model_validator(mode="after")
    def _validar(self):
        op = " ".join((self.numero_operacion or "").split()).upper()
        if self.medio == "efectivo":
            self.numero_operacion = None
        elif not op:
            raise ValueError("Escribe el número de operación")
        else:
            self.numero_operacion = op
        ids = [d.cuota_id for d in self.detalles]
        if len(ids) != len(set(ids)):
            raise ValueError("Una cuota aparece dos veces")
        return self


def _pago(db: Session, p: Pago) -> dict:
    a = db.get(Alumno, p.alumno_id)
    detalles = db.execute(
        select(PagoDetalle, CuotaProgramada, ConceptoCobro)
        .join(CuotaAlumno, and_(CuotaAlumno.colegio_id == PagoDetalle.colegio_id, CuotaAlumno.id == PagoDetalle.cuota_id))
        .join(CuotaProgramada, and_(CuotaProgramada.colegio_id == CuotaAlumno.colegio_id,
                                    CuotaProgramada.id == CuotaAlumno.cuota_programada_id))
        .join(ConceptoCobro, and_(ConceptoCobro.colegio_id == CuotaProgramada.colegio_id,
                                  ConceptoCobro.id == CuotaProgramada.concepto_id))
        .where(PagoDetalle.colegio_id == p.colegio_id, PagoDetalle.pago_id == p.id)
        .order_by(CuotaProgramada.vence, PagoDetalle.id)).all()
    caja = db.get(CajaSesion, p.caja_id)
    comprobante = db.scalar(select(Comprobante).where(Comprobante.colegio_id == p.colegio_id,
                                                      Comprobante.pago_id == p.id))
    return {"id": p.id, "recibo": numero_recibo(p), "comprobante": facturacion.comprobante_de(comprobante), "alumno_id": a.id, "alumno": f"{a.apellidos}, {a.nombres}",
            "fecha": p.fecha.isoformat(), "momento": p.momento.isoformat(), "medio": p.medio,
            "numero_operacion": p.numero_operacion, "total": s2(p.total), "cajero": p.cajero,
            "cajero_id": p.cajero_id, "caja_id": p.caja_id, "caja_abierta": caja.cerrada_en is None,
            "anulado": p.anulado_en is not None, "anulado_motivo": p.anulado_motivo, "anulado_por": p.anulado_por,
            "anulado_en": p.anulado_en.isoformat() if p.anulado_en else None,
            "detalles": [{"cuota_id": d.cuota_id, "concepto": c.nombre, "mes": x.mes, "numero": x.numero,
                          "monto": s2(d.monto)} for d, x, c in detalles]}


@router.post("/pagos", status_code=201)
def cobrar(d: PagoIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Cobra una o varias cuotas (pago parcial permitido) con la caja del día abierta. El monto de cada cuota
    no supera su saldo (no hay saldo a favor). El recibo toma el siguiente correlativo con bloqueo de fila:
    dos cobros a la vez no repiten número ni dejan saltos."""
    cid = s.colegio.id
    caja = _caja_abierta(db, s, bloquear=True)
    if caja is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Abre tu caja para cobrar")
    hoy = hoy_lima()
    if caja.fecha != hoy:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Tu caja abierta es del {caja.fecha:%d/%m/%Y}: ciérrala y abre la de hoy")
    a = obtener(db, Alumno, cid, d.alumno_id, "Alumno")
    emisor = facturacion.activa(db, cid)
    if d.factura and emisor is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El colegio no emite comprobantes electrónicos")
    if d.factura and not facturacion.ruc_valido(d.factura.ruc):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, facturacion.RUC_INVALIDO)
    filas = {c.id: (c, vence) for c, vence in db.execute(
        select(CuotaAlumno, CuotaProgramada.vence)
        .join(CuotaProgramada, and_(CuotaProgramada.colegio_id == CuotaAlumno.colegio_id,
                                    CuotaProgramada.id == CuotaAlumno.cuota_programada_id))
        .where(CuotaAlumno.colegio_id == cid, CuotaAlumno.alumno_id == a.id,
               CuotaAlumno.id.in_([x.cuota_id for x in d.detalles]))
        .order_by(CuotaAlumno.id).with_for_update(of=CuotaAlumno))}
    cfg = pensiones.config(db, cid, bloquear=True)  # también bloquea el correlativo hasta el commit
    for x in d.detalles:
        if x.cuota_id not in filas:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuota no encontrada")
        cuota, vence = filas[x.cuota_id]
        sit = pensiones.situacion(cuota, vence, cfg, hoy)
        if sit.estado == "anulada":
            raise HTTPException(status.HTTP_409_CONFLICT, "Esa cuota está anulada")
        if x.monto > sit.saldo:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                f"El monto supera el saldo de la cuota ({pensiones.texto_soles(sit.saldo)})")
        cuota.mora = sit.mora  # la mora del día queda cargada en la cuota
        cuota.pagado += x.monto
    cfg.correlativo_recibo += 1
    p = Pago(colegio_id=cid, alumno_id=a.id, caja_id=caja.id, cajero_id=s.usuario.id, cajero=quien(s), fecha=hoy,
             medio=d.medio, numero_operacion=d.numero_operacion, total=sum((x.monto for x in d.detalles), Decimal(0)),
             serie=cfg.serie_recibo, correlativo=cfg.correlativo_recibo)
    db.add(p)
    repetido = "Ese número de operación ya se registró para este medio de pago"
    guardar(db, repetido, solo_flush=True)
    db.add_all([PagoDetalle(colegio_id=cid, pago_id=p.id, cuota_id=x.cuota_id, monto=x.monto) for x in d.detalles])
    comprobante = ""
    if emisor is not None:  # en "pendiente": lo emite la cola, el cobro no espera al proveedor
        db.flush()
        if d.factura:
            c = facturacion.crear(db, emisor, p, facturacion.Cliente("RUC", d.factura.ruc, d.factura.razon_social),
                                  "factura")
        else:
            c = facturacion.crear(db, emisor, p, facturacion.cliente_boleta(db, cid, a), "boleta")
        comprobante = f" · {c.tipo} {facturacion.numero(c)}"
    anotar(db, s, "crear", "caja", "pago", p,
           f"Recibo {numero_recibo(p)}: {pensiones.texto_soles(p.total)} de {a.apellidos}, {a.nombres} "
           f"({NOMBRE_MEDIO[p.medio]}, {len(d.detalles)} cuotas){comprobante}", repetido)
    return _pago(db, p)


@router.get("/pagos")
def pagos(desde: date | None = None, hasta: date | None = None, medio: Medio | None = None,
          cajero_id: int | None = None, caja_id: int | None = None, q: str | None = None,
          estado: Literal["valido", "anulado"] | None = None, p: Pagina = Depends(pagina),
          s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    consulta = (select(Pago, Alumno)
                .join(Alumno, and_(Alumno.colegio_id == Pago.colegio_id, Alumno.id == Pago.alumno_id))
                .where(Pago.colegio_id == cid))
    if desde:
        consulta = consulta.where(Pago.fecha >= desde)
    if hasta:
        consulta = consulta.where(Pago.fecha <= hasta)
    if medio:
        consulta = consulta.where(Pago.medio == medio)
    if cajero_id is not None:
        consulta = consulta.where(Pago.cajero_id == cajero_id)
    if caja_id is not None:
        consulta = consulta.where(Pago.caja_id == caja_id)
    if estado == "valido":
        consulta = consulta.where(Pago.anulado_en.is_(None))
    elif estado == "anulado":
        consulta = consulta.where(Pago.anulado_en.is_not(None))
    if q and q.strip():
        patron = f"%{q.strip()}%"
        consulta = consulta.where(or_(Alumno.apellidos.ilike(patron), Alumno.nombres.ilike(patron),
                                      Alumno.numero_documento.ilike(patron), Pago.numero_operacion.ilike(patron)))
    total = contar(db, consulta)
    suma = db.scalar(select(func.coalesce(func.sum(Pago.total), 0)).where(
        Pago.id.in_(consulta.where(Pago.anulado_en.is_(None)).with_only_columns(Pago.id))))
    filas = db.execute(recortar(consulta.order_by(Pago.momento.desc(), Pago.id.desc()), p)).all()
    cajeros = db.execute(select(Pago.cajero_id, Pago.cajero).where(Pago.colegio_id == cid).distinct()
                         .order_by(Pago.cajero)).all()
    comprobantes = {c.pago_id: c for c in db.scalars(select(Comprobante).where(
        Comprobante.colegio_id == cid, Comprobante.pago_id.in_([x.id for x, _ in filas])))} if filas else {}
    return {**p.datos(total), "suma": s2(suma or 0),
            "cajeros": [{"id": i, "nombre": n} for i, n in cajeros],
            "items": [{"id": x.id, "recibo": numero_recibo(x), "alumno_id": a.id, "alumno": f"{a.apellidos}, {a.nombres}",
                       "fecha": x.fecha.isoformat(), "momento": x.momento.isoformat(), "medio": x.medio,
                       "numero_operacion": x.numero_operacion, "total": s2(x.total), "cajero": x.cajero,
                       "anulado": x.anulado_en is not None,
                       "comprobante": facturacion.comprobante_de(comprobantes.get(x.id))} for x, a in filas]}


@router.get("/pagos/{pago_id}")
def pago(pago_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    return _pago(db, obtener(db, Pago, s.colegio.id, pago_id, "Pago"))


def recibo_pdf(db: Session, colegio, p: Pago) -> Response:
    datos = _pago(db, p)
    a = db.get(Alumno, p.alumno_id)
    contenido = pdf.recibo(imagen_pdf(colegio), pdf.Recibo(
        numero=datos["recibo"], fecha=p.momento, alumno=f"{a.apellidos}, {a.nombres}", documento=a.numero_documento,
        medio=NOMBRE_MEDIO[p.medio], operacion=p.numero_operacion, cajero=p.cajero,
        lineas=[(f"{x['concepto']} · {x['mes']}", x["monto"]) for x in datos["detalles"]], total=datos["total"],
        anulado=p.anulado_motivo if p.anulado_en else None))
    return Response(contenido, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="recibo-{datos["recibo"]}.pdf"'})


@router.get("/pagos/{pago_id}/recibo.pdf")
def recibo(pago_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> Response:
    return recibo_pdf(db, s.colegio, obtener(db, Pago, s.colegio.id, pago_id, "Pago"))


@router.post("/pagos/{pago_id}/anular")
def anular_pago(pago_id: int, d: AnularIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Queda visible como anulado y cada cuota recupera su saldo. Con la caja abierta lo anulan su cajero, el
    director o un rol con permiso para anular; con la caja cerrada, solo estos dos últimos."""
    cid = s.colegio.id
    p = db.scalar(select(Pago).where(Pago.colegio_id == cid, Pago.id == pago_id).with_for_update())
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pago no encontrado")
    if p.anulado_en is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese pago ya está anulado")
    caja = db.get(CajaSesion, p.caja_id)
    if not anula_todo(s):
        if caja.cerrada_en is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"La caja ya se cerró: {SOLO_AUTORIZADOS}")
        if caja.usuario_id != s.usuario.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Solo lo anulan el cajero que cobró, el director o un rol con permiso para anular")
    detalles = db.scalars(select(PagoDetalle).where(PagoDetalle.colegio_id == cid, PagoDetalle.pago_id == p.id)).all()
    cuotas = {c.id: c for c in db.scalars(select(CuotaAlumno).where(
        CuotaAlumno.colegio_id == cid, CuotaAlumno.id.in_([x.cuota_id for x in detalles]))
        .order_by(CuotaAlumno.id).with_for_update())}
    for x in detalles:
        cuotas[x.cuota_id].pagado -= x.monto
    p.anulado_en, p.anulado_motivo, p.anulado_por = datetime.now(UTC), d.motivo, quien(s)
    c = facturacion.encolar_anulacion(db, p, d.motivo)
    a = db.get(Alumno, p.alumno_id)
    anotar(db, s, "anular", "caja", "pago", p, f"Anuló el recibo {numero_recibo(p)} "
                                              f"({pensiones.texto_soles(p.total)}) de {a.apellidos}, {a.nombres}"
                                              + (f"; se pide anular la {c.tipo} {facturacion.numero(c)}" if c else ""))
    return _pago(db, p)


# --- Comprobantes con error -----------------------------------------------------------------

@router.get("/comprobantes/errores")
def comprobantes_con_error(p: Pagina = Depends(pagina), s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    """Los que el proveedor rechazó y las órdenes (emitir o anular) que fallaron 5 veces (E2)."""
    cid = s.colegio.id
    q = (select(Comprobante, ColaComprobante, Pago, Alumno)
         .join(Pago, and_(Pago.colegio_id == Comprobante.colegio_id, Pago.id == Comprobante.pago_id))
         .join(Alumno, and_(Alumno.colegio_id == Pago.colegio_id, Alumno.id == Pago.alumno_id))
         .outerjoin(ColaComprobante, and_(ColaComprobante.colegio_id == Comprobante.colegio_id,
                                          ColaComprobante.comprobante_id == Comprobante.id,
                                          ColaComprobante.estado == "error"))
         .where(Comprobante.colegio_id == cid,
                or_(ColaComprobante.id.is_not(None), Comprobante.estado == "rechazado")))
    total = contar(db, q)
    filas = db.execute(recortar(q.order_by(Comprobante.id.desc(), ColaComprobante.id), p)).all()
    return {**p.datos(total), "items": [
        {**facturacion.comprobante_de(c), "pago_id": x.id, "recibo": numero_recibo(x),
         "alumno": f"{a.apellidos}, {a.nombres}", "fecha": x.fecha.isoformat(),
         "tarea_id": t.id if t else None, "accion": t.accion if t else None, "intentos": t.intentos if t else c.intentos,
         "error": t.error if t else c.respuesta} for c, t, x, a in filas]}


@router.post("/comprobantes/tareas/{tarea_id}/reintentar")
def reintentar_comprobante(tarea_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """E2: vuelve a poner en la cola una orden que falló 5 veces."""
    t = db.scalar(select(ColaComprobante).where(ColaComprobante.colegio_id == s.colegio.id,
                                                ColaComprobante.id == tarea_id).with_for_update())
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comprobante no encontrado")
    if t.estado != "error":
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese comprobante no está en error")
    facturacion.reintentar(t)
    c = db.get(Comprobante, t.comprobante_id)
    anotar(db, s, "editar", "caja", "comprobante", c,
           f"Reintentó {'emitir' if t.accion == 'emitir' else 'anular'} la {c.tipo} {facturacion.numero(c)}")
    return facturacion.comprobante_de(c)


# --- Gastos ---------------------------------------------------------------------------------

class CategoriaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    activa: bool = True

    _nombre = field_validator("nombre")(classmethod(lambda cls, v: " ".join(v.split())))


@router.get("/categorias")
def categorias(s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> list[dict]:
    cid = s.colegio.id
    usos = dict(db.execute(select(Gasto.categoria_id, func.count()).where(Gasto.colegio_id == cid)
                           .group_by(Gasto.categoria_id)).all())
    return [{"id": c.id, "nombre": c.nombre, "activa": c.activa, "usos": usos.get(c.id, 0)}
            for c in db.scalars(select(CategoriaGasto).where(CategoriaGasto.colegio_id == cid)
                                .order_by(CategoriaGasto.orden, CategoriaGasto.nombre))]


@router.post("/categorias", status_code=201)
def crear_categoria(d: CategoriaIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    orden = db.scalar(select(func.max(CategoriaGasto.orden)).where(CategoriaGasto.colegio_id == cid)) or 0
    c = CategoriaGasto(colegio_id=cid, nombre=d.nombre, activa=d.activa, orden=orden + 1)
    db.add(c)
    guardar(db, "Ya hay una categoría con ese nombre", solo_flush=True)
    anotar(db, s, "crear", "caja", "categoria_gasto", c, f"Categoría de gasto «{c.nombre}»")
    return {"id": c.id, "nombre": c.nombre, "activa": c.activa, "usos": 0}


@router.put("/categorias/{categoria_id}")
def editar_categoria(categoria_id: int, d: CategoriaIn, s: Sesion = Depends(editar),
                     db: Session = Depends(get_db)) -> dict:
    c = obtener(db, CategoriaGasto, s.colegio.id, categoria_id, "Categoría")
    c.nombre, c.activa = d.nombre, d.activa
    anotar(db, s, "editar", "caja", "categoria_gasto", c,
           f"Categoría de gasto «{c.nombre}»{'' if c.activa else ' (desactivada)'}", "Ya hay una categoría con ese nombre")
    return {"id": c.id, "nombre": c.nombre, "activa": c.activa}


class GastoIn(BaseModel):
    fecha: date
    categoria_id: int
    descripcion: str = Field(min_length=2, max_length=200)
    monto: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
    medio: Medio
    comprobante_tipo: str | None = Field(default=None, max_length=30)
    comprobante_numero: str | None = Field(default=None, max_length=30)

    @field_validator("descripcion", "comprobante_tipo", "comprobante_numero")
    @classmethod
    def _limpiar(cls, v):
        return (" ".join(v.split()) or None) if isinstance(v, str) else v


def _gasto(g: Gasto, categoria: str) -> dict:
    return {"id": g.id, "fecha": g.fecha.isoformat(), "categoria_id": g.categoria_id, "categoria": categoria,
            "descripcion": g.descripcion, "monto": s2(g.monto), "medio": g.medio,
            "comprobante_tipo": g.comprobante_tipo, "comprobante_numero": g.comprobante_numero,
            "archivo": g.archivo_clave is not None, "registrado_por": g.registrado_por,
            "creado_en": g.creado_en.isoformat(), "anulado": g.anulado_en is not None,
            "anulado_motivo": g.anulado_motivo, "anulado_por": g.anulado_por}


async def _leer_archivo(archivo: UploadFile | None) -> tuple[str, bytes] | None:
    """Foto o PDF del comprobante: máximo 5 MB y se revisa el tipo real (no el que dice el navegador)."""
    if archivo is None or not archivo.filename:
        return None
    contenido = await archivo.read(MAX_ARCHIVO + 1)
    if len(contenido) > MAX_ARCHIVO:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El archivo pesa más de 5 MB")
    for tipo, firma in TIPOS_ARCHIVO.items():
        if contenido.startswith(firma) and (tipo != "image/webp" or contenido[8:12] == b"WEBP"):
            return tipo, contenido
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Solo se acepta una imagen (JPG, PNG, WEBP) o un PDF")


@router.post("/gastos", status_code=201)
async def registrar_gasto(datos: str = Form(...), archivo: UploadFile | None = File(None),
                          s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    try:
        d = GastoIn.model_validate_json(datos)
    except ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, e.errors(include_url=False,
                                                                            include_context=False)) from None
    cid = s.colegio.id
    c = obtener(db, CategoriaGasto, cid, d.categoria_id, "Categoría")
    if not c.activa:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Esa categoría está desactivada")
    leido = await _leer_archivo(archivo)
    g = Gasto(colegio_id=cid, registrado_por_id=s.usuario.id, registrado_por=quien(s), **d.model_dump())
    clave = None
    if leido:
        clave = f"gastos/{cid}/{uuid.uuid4().hex}"
        get_almacenamiento_privado().guardar(clave, leido[1], leido[0])
        g.archivo_clave, g.archivo_tipo = clave, leido[0]
    db.add(g)
    try:
        anotar(db, s, "crear", "caja", "gasto", g,
               f"Gasto {pensiones.texto_soles(g.monto)} en {c.nombre}: {g.descripcion}")
    except Exception:
        if clave:
            get_almacenamiento_privado().borrar(clave)
        raise
    return _gasto(g, c.nombre)


@router.get("/gastos")
def gastos(desde: date | None = None, hasta: date | None = None, categoria_id: int | None = None,
           q: str | None = None, estado: Literal["valido", "anulado"] | None = None, p: Pagina = Depends(pagina),
           s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    consulta = (select(Gasto, CategoriaGasto.nombre)
                .join(CategoriaGasto, and_(CategoriaGasto.colegio_id == Gasto.colegio_id,
                                           CategoriaGasto.id == Gasto.categoria_id))
                .where(Gasto.colegio_id == cid))
    if desde:
        consulta = consulta.where(Gasto.fecha >= desde)
    if hasta:
        consulta = consulta.where(Gasto.fecha <= hasta)
    if categoria_id is not None:
        consulta = consulta.where(Gasto.categoria_id == categoria_id)
    if estado == "valido":
        consulta = consulta.where(Gasto.anulado_en.is_(None))
    elif estado == "anulado":
        consulta = consulta.where(Gasto.anulado_en.is_not(None))
    if q and q.strip():
        patron = f"%{q.strip()}%"
        consulta = consulta.where(or_(Gasto.descripcion.ilike(patron), Gasto.comprobante_numero.ilike(patron)))
    total = contar(db, consulta)
    suma = db.scalar(select(func.coalesce(func.sum(Gasto.monto), 0)).where(
        Gasto.id.in_(consulta.where(Gasto.anulado_en.is_(None)).with_only_columns(Gasto.id))))
    filas = db.execute(recortar(consulta.order_by(Gasto.fecha.desc(), Gasto.id.desc()), p)).all()
    return {**p.datos(total), "suma": s2(suma or 0), "items": [_gasto(g, n) for g, n in filas]}


@router.get("/gastos/{gasto_id}/archivo")
def archivo_gasto(gasto_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> Response:
    g = obtener(db, Gasto, s.colegio.id, gasto_id, "Gasto")
    contenido = get_almacenamiento_privado().leer(g.archivo_clave) if g.archivo_clave else None
    if contenido is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El gasto no tiene archivo")
    extension = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    nombre = quote(f"gasto-{g.id}.{extension.get(g.archivo_tipo, 'bin')}")
    return Response(contenido, media_type=g.archivo_tipo, headers={
        "Content-Disposition": f"inline; filename*=UTF-8''{nombre}", "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store"})


@router.post("/gastos/{gasto_id}/anular")
def anular_gasto(gasto_id: int, d: AnularIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    g = obtener(db, Gasto, s.colegio.id, gasto_id, "Gasto")
    if g.anulado_en is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese gasto ya está anulado")
    if not anula_todo(s):
        if g.fecha != hoy_lima():
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"El gasto es de un día anterior: {SOLO_AUTORIZADOS}")
        if g.registrado_por_id != s.usuario.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Solo lo anulan quien lo registró, el director o un rol con permiso para anular")
    g.anulado_en, g.anulado_motivo, g.anulado_por = datetime.now(UTC), d.motivo, quien(s)
    c = db.get(CategoriaGasto, g.categoria_id)
    anotar(db, s, "anular", "caja", "gasto", g, f"Anuló el gasto {pensiones.texto_soles(g.monto)} en {c.nombre}")
    return _gasto(g, c.nombre)


# --- Reportes -------------------------------------------------------------------------------

AGRUPAR = {"dia": "Día", "concepto": "Concepto", "medio": "Medio de pago", "cajero": "Cajero"}


def ingresos_filas(db: Session, cid: int, desde: date, hasta: date, agrupar: str) -> list[tuple[str, int, Decimal]]:
    """(grupo, pagos, total) de los pagos válidos entre dos días de Lima. Por concepto se reparte cada pago
    según sus cuotas; los demás cuentan el pago entero."""
    valido = (Pago.colegio_id == cid, Pago.fecha.between(desde, hasta), Pago.anulado_en.is_(None))
    if agrupar == "concepto":
        filas = db.execute(
            select(ConceptoCobro.nombre, func.count(PagoDetalle.pago_id.distinct()), func.sum(PagoDetalle.monto))
            .select_from(PagoDetalle)
            .join(Pago, and_(Pago.colegio_id == PagoDetalle.colegio_id, Pago.id == PagoDetalle.pago_id))
            .join(CuotaAlumno, and_(CuotaAlumno.colegio_id == PagoDetalle.colegio_id,
                                    CuotaAlumno.id == PagoDetalle.cuota_id))
            .join(CuotaProgramada, and_(CuotaProgramada.colegio_id == CuotaAlumno.colegio_id,
                                        CuotaProgramada.id == CuotaAlumno.cuota_programada_id))
            .join(ConceptoCobro, and_(ConceptoCobro.colegio_id == CuotaProgramada.colegio_id,
                                      ConceptoCobro.id == CuotaProgramada.concepto_id))
            .where(*valido).group_by(ConceptoCobro.nombre).order_by(ConceptoCobro.nombre)).all()
    else:
        columna = {"dia": Pago.fecha, "medio": Pago.medio, "cajero": Pago.cajero}[agrupar]
        filas = db.execute(select(columna, func.count(), func.sum(Pago.total)).where(*valido)
                           .group_by(columna).order_by(columna)).all()
    salida = []
    for grupo, n, total in filas:
        if agrupar == "dia":
            grupo = grupo.strftime("%d/%m/%Y")
        elif agrupar == "medio":
            grupo = NOMBRE_MEDIO[grupo]
        salida.append((grupo, n, pensiones.soles(total or 0)))
    return salida


def _rango(desde: date | None, hasta: date | None) -> tuple[date, date]:
    hoy = hoy_lima()
    desde, hasta = desde or hoy.replace(day=1), hasta or hoy
    if hasta < desde:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "La fecha final va después de la inicial")
    if (hasta - desde).days > 400:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Elige un rango de hasta 400 días")
    return desde, hasta


@router.get("/reportes/ingresos")
def ingresos(desde: date | None = None, hasta: date | None = None,
             agrupar: Literal["dia", "concepto", "medio", "cajero"] = "dia", s: Sesion = Depends(ver),
             db: Session = Depends(get_db)) -> dict:
    desde, hasta = _rango(desde, hasta)
    filas = ingresos_filas(db, s.colegio.id, desde, hasta, agrupar)
    total = db.scalar(select(func.coalesce(func.sum(Pago.total), 0)).where(
        Pago.colegio_id == s.colegio.id, Pago.fecha.between(desde, hasta), Pago.anulado_en.is_(None)))
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "agrupar": agrupar, "total": s2(total),
            "items": [{"grupo": g, "pagos": n, "total": s2(t)} for g, n, t in filas]}


@router.get("/reportes/ingresos.xlsx")
def ingresos_excel(desde: date | None = None, hasta: date | None = None,
                   agrupar: Literal["dia", "concepto", "medio", "cajero"] = "dia", s: Sesion = Depends(ver),
                   db: Session = Depends(get_db)) -> Response:
    desde, hasta = _rango(desde, hasta)
    filas = ingresos_filas(db, s.colegio.id, desde, hasta, agrupar)
    filas.append(("Total", None, sum((t for _, _, t in filas), Decimal(0))))
    return excel.tabla(f"Ingresos por {AGRUPAR[agrupar].lower()} · {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}",
                       [AGRUPAR[agrupar], "Pagos", "Total (S/)"], [list(f) for f in filas],
                       f"ingresos-{agrupar}-{desde}-{hasta}.xlsx", s.colegio.color_primario, soles=(2,))


def gastos_filas(db: Session, cid: int, desde: date, hasta: date) -> list[tuple[str, int, Decimal]]:
    return [(n, c, pensiones.soles(t or 0)) for n, c, t in db.execute(
        select(CategoriaGasto.nombre, func.count(), func.sum(Gasto.monto))
        .join(CategoriaGasto, and_(CategoriaGasto.colegio_id == Gasto.colegio_id, CategoriaGasto.id == Gasto.categoria_id))
        .where(Gasto.colegio_id == cid, Gasto.fecha.between(desde, hasta), Gasto.anulado_en.is_(None))
        .group_by(CategoriaGasto.nombre).order_by(func.sum(Gasto.monto).desc()))]


@router.get("/reportes/gastos")
def gastos_por_categoria(desde: date | None = None, hasta: date | None = None, s: Sesion = Depends(ver),
                         db: Session = Depends(get_db)) -> dict:
    desde, hasta = _rango(desde, hasta)
    filas = gastos_filas(db, s.colegio.id, desde, hasta)
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(),
            "total": s2(sum((t for _, _, t in filas), Decimal(0))),
            "items": [{"grupo": g, "gastos": n, "total": s2(t)} for g, n, t in filas]}


@router.get("/reportes/gastos.xlsx")
def gastos_excel(desde: date | None = None, hasta: date | None = None, s: Sesion = Depends(ver),
                 db: Session = Depends(get_db)) -> Response:
    desde, hasta = _rango(desde, hasta)
    filas = gastos_filas(db, s.colegio.id, desde, hasta)
    filas.append(("Total", None, sum((t for _, _, t in filas), Decimal(0))))
    return excel.tabla(f"Gastos por categoría · {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}",
                       ["Categoría", "Gastos", "Total (S/)"], [list(f) for f in filas],
                       f"gastos-{desde}-{hasta}.xlsx", s.colegio.color_primario, soles=(2,))
