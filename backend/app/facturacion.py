"""Comprobantes electrónicos SUNAT, listos para conectar a un proveedor.

Igual que `Almacenamiento`: una interfaz (`Facturador`) y sus implementaciones. Hoy hay dos:
- `FacturadorNinguno` (por defecto): no emite nada; el colegio sigue solo con el recibo interno.
- `FacturadorPrueba`: solo para las pruebas; acepta, rechaza o falla según se le pida.
El proveedor real se agrega después como otra clase en `PROVEEDORES`, sin tocar el resto.

El cobro solo crea el comprobante en `pendiente` y una fila en `cola_comprobante`; el hilo de fondo la
procesa (`bucle_comprobantes`). Si el proveedor falla, se reintenta con espera creciente hasta 5 veces y
después queda en la lista "Comprobantes con error" hasta que alguien pulse "Reintentar".

El token del proveedor se guarda cifrado con FACTURACION_CLAVE y solo se descifra aquí, para el proveedor.
"""

import base64
import hashlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (Alumno, Apoderado, ColaComprobante, Comprobante, ConceptoCobro, ConfigFacturacion,
                        CuotaAlumno, CuotaProgramada, Pago, PagoDetalle, SerieComprobante)

log = logging.getLogger(__name__)

IGV = Decimal("0.18")
MAX_INTENTOS = 5
CENTIMO = Decimal("0.01")


# --- Interfaz del proveedor ---------------------------------------------------------------------

@dataclass
class Resultado:
    """Lo que responde el proveedor. `estado`: "enviado" (aún sin respuesta final), "aceptado",
    "rechazado" o "anulado"."""

    estado: str
    respuesta: str | None = None
    enlace_pdf: str | None = None
    enlace_xml: str | None = None
    enlace_cdr: str | None = None


class FalloProveedor(Exception):
    """El proveedor no respondió o respondió con un error temporal: se reintenta."""


class Facturador(Protocol):
    def emitir(self, comprobante: Comprobante) -> Resultado: ...

    def anular(self, comprobante: Comprobante, motivo: str) -> Resultado: ...

    def consultar(self, comprobante: Comprobante) -> Resultado: ...


class FacturadorNinguno:
    """Sin proveedor: no se crean comprobantes (ver `activa`). Si igual le llega uno, no lo emite."""

    emite = False

    def __init__(self, token: str | None = None):
        pass

    def emitir(self, comprobante: Comprobante) -> Resultado:
        raise FalloProveedor("Sin proveedor de comprobantes")

    def anular(self, comprobante: Comprobante, motivo: str) -> Resultado:
        raise FalloProveedor("Sin proveedor de comprobantes")

    def consultar(self, comprobante: Comprobante) -> Resultado:
        raise FalloProveedor("Sin proveedor de comprobantes")


class FacturadorPrueba:
    """Solo para las pruebas. `respuestas` es la lista de lo que hará en cada llamada, en orden:
    "aceptar", "rechazar", "enviar" (queda en enviado), "anular" o "fallar". Si se acaba, acepta (o anula,
    si se le pide anular). `llamadas` guarda (método, número) de cada llamada y el token que recibió."""

    emite = True
    respuestas: list[str] = []
    llamadas: list[tuple[str, str]] = []
    tokens: list[str | None] = []

    def __init__(self, token: str | None = None):
        FacturadorPrueba.tokens.append(token)

    @classmethod
    def reiniciar(cls, *respuestas: str) -> None:
        cls.respuestas, cls.llamadas, cls.tokens = list(respuestas), [], []

    def _responder(self, metodo: str, c: Comprobante, por_defecto: str) -> Resultado:
        FacturadorPrueba.llamadas.append((metodo, f"{c.serie}-{c.numero}"))
        r = FacturadorPrueba.respuestas.pop(0) if FacturadorPrueba.respuestas else por_defecto
        if r == "fallar":
            raise FalloProveedor("El proveedor no responde")
        estado = {"aceptar": "aceptado", "rechazar": "rechazado", "enviar": "enviado", "anular": "anulado"}[r]
        enlace = f"https://prueba.test/{c.serie}-{c.numero}"
        return Resultado(estado, "Rechazado por SUNAT: dato inválido" if estado == "rechazado" else "OK",
                         *((f"{enlace}.pdf", f"{enlace}.xml", f"{enlace}.cdr") if estado == "aceptado" else ()))

    def emitir(self, comprobante: Comprobante) -> Resultado:
        return self._responder("emitir", comprobante, "aceptar")

    def anular(self, comprobante: Comprobante, motivo: str) -> Resultado:
        return self._responder("anular", comprobante, "anular")

    def consultar(self, comprobante: Comprobante) -> Resultado:
        return self._responder("consultar", comprobante, "aceptar")


# El proveedor real se agrega aquí. "prueba" lo registran solo las pruebas.
PROVEEDORES: dict[str, type] = {"ninguno": FacturadorNinguno}
NOMBRE_PROVEEDOR = {"ninguno": "Ninguno (solo recibo interno)"}


# --- Token cifrado ------------------------------------------------------------------------------

class SinClave(Exception):
    """Falta FACTURACION_CLAVE en el .env."""


def _fernet() -> Fernet:
    clave = get_settings().facturacion_clave
    if not clave:
        raise SinClave
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(clave.encode()).digest()))


def hay_clave() -> bool:
    return bool(get_settings().facturacion_clave)


def cifrar(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def descifrar(cifrado: str | None) -> str | None:
    if not cifrado:
        return None
    try:
        return _fernet().decrypt(cifrado.encode()).decode()
    except (SinClave, InvalidToken):
        return None


# --- RUC ----------------------------------------------------------------------------------------

RUC_INVALIDO = "El RUC no es válido (11 dígitos con su dígito verificador)"


def ruc_valido(ruc: str) -> bool:
    """11 dígitos y dígito verificador (módulo 11 con pesos 5 4 3 2 7 6 5 4 3 2)."""
    if len(ruc) != 11 or not ruc.isdigit():
        return False
    suma = sum(int(d) * p for d, p in zip(ruc[:10], (5, 4, 3, 2, 7, 6, 5, 4, 3, 2), strict=True))
    resto = 11 - suma % 11
    return {10: 0, 11: 1}.get(resto, resto) == int(ruc[10])


# --- Configuración ------------------------------------------------------------------------------

def config(db: Session, colegio_id: int) -> ConfigFacturacion:
    """La fila de configuración (sin guardar si aún no existe)."""
    return db.get(ConfigFacturacion, colegio_id) or ConfigFacturacion(colegio_id=colegio_id, emite=False,
                                                                       serie_boleta="B001", serie_factura="F001",
                                                                       proveedor="ninguno")


def config_de(cfg: ConfigFacturacion) -> dict:
    """Para el navegador: el token solo como "configurado"."""
    return {"emite": cfg.emite, "ruc": cfg.ruc, "razon_social": cfg.razon_social,
            "serie_boleta": cfg.serie_boleta, "serie_factura": cfg.serie_factura, "proveedor": cfg.proveedor,
            "token_configurado": bool(cfg.token_cifrado), "clave_configurada": hay_clave(),
            "proveedores": [{"clave": k, "nombre": NOMBRE_PROVEEDOR.get(k, k)} for k in PROVEEDORES]}


def facturador(cfg: ConfigFacturacion) -> Facturador:
    return PROVEEDORES.get(cfg.proveedor, FacturadorNinguno)(descifrar(cfg.token_cifrado))


def activa(db: Session, colegio_id: int) -> ConfigFacturacion | None:
    """La configuración si el colegio emite con un proveedor que emite; si no, None (todo sigue como hoy)."""
    cfg = db.get(ConfigFacturacion, colegio_id)
    if cfg is None or not cfg.emite or not getattr(PROVEEDORES.get(cfg.proveedor), "emite", False):
        return None
    return cfg


# --- Montos --------------------------------------------------------------------------------------

def _c(v: Decimal) -> Decimal:
    return v.quantize(CENTIMO, rounding=ROUND_HALF_UP)


def montos(db: Session, p: Pago) -> tuple[Decimal, Decimal, Decimal]:
    """(gravado sin IGV, inafecto, IGV) del pago, según el tipo de IGV de cada concepto. Lo cobrado de un
    concepto gravado ya incluye el IGV: la base es lo cobrado / 1.18 y el IGV, la diferencia."""
    con_igv, inafecto = Decimal(0), Decimal(0)
    for monto, igv in db.execute(
            select(PagoDetalle.monto, ConceptoCobro.igv)
            .join(CuotaAlumno, and_(CuotaAlumno.colegio_id == PagoDetalle.colegio_id, CuotaAlumno.id == PagoDetalle.cuota_id))
            .join(CuotaProgramada, and_(CuotaProgramada.colegio_id == CuotaAlumno.colegio_id,
                                        CuotaProgramada.id == CuotaAlumno.cuota_programada_id))
            .join(ConceptoCobro, and_(ConceptoCobro.colegio_id == CuotaProgramada.colegio_id,
                                      ConceptoCobro.id == CuotaProgramada.concepto_id))
            .where(PagoDetalle.colegio_id == p.colegio_id, PagoDetalle.pago_id == p.id)):
        if igv == "gravado":
            con_igv += monto
        else:
            inafecto += monto
    base = _c(con_igv / (1 + IGV))
    return base, _c(inafecto), _c(con_igv) - base


# --- Crear y anular (dentro del cobro o de la anulación, sin hablar con el proveedor) -------------

@dataclass
class Cliente:
    tipo_documento: str
    numero_documento: str
    nombre: str


def cliente_boleta(db: Session, colegio_id: int, alumno: Alumno) -> Cliente:
    """E1: la boleta va a nombre del responsable de pago (D2). Sin apoderados, a nombre del alumno."""
    from app.pensiones import responsables

    apoderado_id = responsables(db, colegio_id, [alumno.id]).get(alumno.id)
    if apoderado_id:
        ap = db.get(Apoderado, apoderado_id)
        return Cliente(ap.tipo_documento, ap.numero_documento, f"{ap.apellidos}, {ap.nombres}")
    return Cliente(alumno.tipo_documento, alumno.numero_documento, f"{alumno.apellidos}, {alumno.nombres}")


def _siguiente_numero(db: Session, colegio_id: int, serie: str) -> int:
    """Correlativo de la serie con bloqueo de fila hasta el commit: sin saltos ni repetidos."""
    db.execute(insert(SerieComprobante).values(colegio_id=colegio_id, serie=serie).on_conflict_do_nothing())
    fila = db.scalar(select(SerieComprobante).where(SerieComprobante.colegio_id == colegio_id,
                                                    SerieComprobante.serie == serie).with_for_update())
    fila.ultimo += 1
    return fila.ultimo


def crear(db: Session, cfg: ConfigFacturacion, p: Pago, cliente: Cliente, tipo: str) -> Comprobante:
    """Comprobante en `pendiente` y su orden de emitir en la cola. No hace commit."""
    serie = cfg.serie_factura if tipo == "factura" else cfg.serie_boleta
    gravado, inafecto, igv = montos(db, p)
    c = Comprobante(colegio_id=p.colegio_id, pago_id=p.id, tipo=tipo, serie=serie,
                    numero=_siguiente_numero(db, p.colegio_id, serie),
                    cliente_tipo_documento=cliente.tipo_documento, cliente_numero_documento=cliente.numero_documento,
                    cliente_nombre=cliente.nombre[:200], gravado=gravado, inafecto=inafecto, igv=igv,
                    total=gravado + inafecto + igv, estado="pendiente")
    db.add(c)
    db.flush()
    db.add(ColaComprobante(colegio_id=p.colegio_id, comprobante_id=c.id, accion="emitir"))
    return c


def encolar_anulacion(db: Session, p: Pago, motivo: str) -> Comprobante | None:
    """Al anular un pago con comprobante: orden de anularlo ante el proveedor. No hace commit."""
    c = db.scalar(select(Comprobante).where(Comprobante.colegio_id == p.colegio_id, Comprobante.pago_id == p.id))
    if c is not None and c.estado != "anulado":
        db.add(ColaComprobante(colegio_id=p.colegio_id, comprobante_id=c.id, accion="anular", motivo=motivo))
    return c


def numero(c: Comprobante) -> str:
    return f"{c.serie}-{c.numero:08d}"


def comprobante_de(c: Comprobante | None) -> dict | None:
    if c is None:
        return None
    return {"id": c.id, "tipo": c.tipo, "numero": numero(c), "estado": c.estado,
            "cliente": c.cliente_nombre, "cliente_documento": f"{c.cliente_tipo_documento} {c.cliente_numero_documento}",
            "gravado": str(c.gravado), "inafecto": str(c.inafecto), "igv": str(c.igv), "total": str(c.total),
            "enlace_pdf": c.enlace_pdf, "enlace_xml": c.enlace_xml, "enlace_cdr": c.enlace_cdr}


# --- Cola: hablar con el proveedor ---------------------------------------------------------------

def _aplicar(c: Comprobante, r: Resultado) -> None:
    c.estado, c.respuesta = r.estado, (r.respuesta or None) and r.respuesta[:2000]
    c.enlace_pdf = r.enlace_pdf or c.enlace_pdf
    c.enlace_xml = r.enlace_xml or c.enlace_xml
    c.enlace_cdr = r.enlace_cdr or c.enlace_cdr


def _procesar(db: Session, tarea: ColaComprobante, ahora: datetime) -> None:
    c = db.get(Comprobante, tarea.comprobante_id)
    if tarea.accion == "anular":
        # Primero tiene que terminar la emisión.
        emitir = db.scalar(select(ColaComprobante).where(ColaComprobante.colegio_id == tarea.colegio_id,
                                                         ColaComprobante.comprobante_id == c.id,
                                                         ColaComprobante.accion == "emitir"))
        if emitir is not None and emitir.estado != "hecho":
            tarea.procesar_desde = ahora + timedelta(minutes=1)
            return
        if c.estado in ("rechazado", "anulado"):  # nunca fue válido o ya está anulado: nada que pedir
            c.estado, c.anulado_en = "anulado", c.anulado_en or ahora
            tarea.estado, tarea.procesado_en, tarea.error = "hecho", ahora, None
            return
    cfg = db.get(ConfigFacturacion, tarea.colegio_id)
    proveedor = facturador(cfg) if cfg else FacturadorNinguno()
    tarea.intentos += 1
    c.intentos += 1
    try:
        if tarea.datos.get("enviado"):
            r = proveedor.consultar(c)
        elif tarea.accion == "emitir":
            r = proveedor.emitir(c)
        else:
            r = proveedor.anular(c, tarea.motivo)
    except FalloProveedor as e:
        _fallo(tarea, str(e), ahora)
        return
    except Exception:
        log.exception("Comprobante %s", c.id)
        _fallo(tarea, "Error inesperado al hablar con el proveedor", ahora)
        return
    if tarea.accion == "emitir":
        _aplicar(c, r)
        if r.estado == "enviado":
            tarea.datos = {**tarea.datos, "enviado": True}
            _fallo(tarea, "El proveedor aún no da el resultado", ahora)
            return
        tarea.estado, tarea.procesado_en, tarea.error = "hecho", ahora, None
        return
    # Anular
    if r.estado == "anulado":
        _aplicar(c, r)
        c.anulado_en = ahora
        tarea.estado, tarea.procesado_en, tarea.error = "hecho", ahora, None
    elif r.estado == "enviado":
        tarea.datos = {**tarea.datos, "enviado": True}
        _fallo(tarea, "El proveedor aún no confirma la anulación", ahora)
    else:
        c.respuesta = (r.respuesta or "")[:2000] or c.respuesta
        tarea.estado, tarea.procesado_en = "error", ahora
        tarea.error = (r.respuesta or "El proveedor no aceptó la anulación")[:500]


def _fallo(tarea: ColaComprobante, motivo: str, ahora: datetime) -> None:
    """E2: espera creciente (2, 4, 8, 16 min) y, tras 5 intentos, a la lista de error."""
    tarea.error = motivo[:500]
    if tarea.intentos >= MAX_INTENTOS:
        tarea.estado, tarea.procesado_en = "error", ahora
    else:
        tarea.procesar_desde = ahora + timedelta(minutes=2 ** tarea.intentos)


def procesar_cola(db: Session, ahora: datetime | None = None, limite: int = 50) -> int:
    """Procesa hasta `limite` tareas pendientes y hace commit. Devuelve cuántas tomó."""
    ahora = ahora or datetime.now(UTC)
    tareas = db.scalars(select(ColaComprobante)
                        .where(ColaComprobante.estado == "pendiente", ColaComprobante.procesar_desde <= ahora)
                        .order_by(ColaComprobante.procesar_desde, ColaComprobante.id).limit(limite)
                        .with_for_update(skip_locked=True)).all()
    for t in tareas:
        _procesar(db, t, ahora)
        db.flush()
    db.commit()
    return len(tareas)


def reintentar(tarea: ColaComprobante, ahora: datetime | None = None) -> None:
    """E2: el botón "Reintentar" vuelve a poner la tarea en la cola con 5 intentos nuevos."""
    tarea.estado, tarea.intentos, tarea.procesado_en = "pendiente", 0, None
    tarea.procesar_desde = ahora or datetime.now(UTC)


def bucle_comprobantes(parar: threading.Event, cada: float = 5,
                       procesar: Callable[[Session], int] = procesar_cola) -> None:
    from app.db import get_sessionmaker

    while not parar.wait(cada):
        try:
            with get_sessionmaker()() as db:
                while procesar(db) == 50:  # si hay más, seguir sin esperar
                    pass
        except Exception:
            log.exception("Envío de comprobantes")
