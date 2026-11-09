"""Comprobantes electrónicos SUNAT (boleta o factura) de los pagos de caja, listos para conectar a un
proveedor. Sin proveedor (FacturadorNinguno) el colegio sigue solo con el recibo interno.

- La configuración la editan solo el director y Tikray Labs. El token del proveedor se guarda cifrado
  (FACTURACION_CLAVE) y nunca vuelve al navegador ni al historial.
- Nada se borra: un comprobante solo se anula ante el proveedor. Llaves RESTRICT.
- El número es correlativo por serie y colegio, sin saltos (bloqueo de la fila de la serie).
- Se emite en segundo plano desde `cola_comprobante`, como `cola_aviso`.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text,
                        UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ConColegio, ahora_utc, creado_en
from app.models.pensiones import _en, _fk

TIPOS_COMPROBANTE = ("boleta", "factura")
ESTADOS_COMPROBANTE = ("pendiente", "enviado", "aceptado", "rechazado", "anulado")
ACCIONES_COLA = ("emitir", "anular")
ESTADOS_COLA = ("pendiente", "hecho", "error")
SERIE_BOLETA = "B001"
SERIE_FACTURA = "F001"
# Serie SUNAT: B o F más tres letras o dígitos.
PATRON_SERIE_BOLETA = r"^B[0-9A-Z]{3}$"
PATRON_SERIE_FACTURA = r"^F[0-9A-Z]{3}$"


class ConfigFacturacion(Base):
    """Datos para emitir del colegio. Si no hay fila, no emite."""

    __tablename__ = "config_facturacion"
    __table_args__ = (
        CheckConstraint("ruc IS NULL OR ruc ~ '^[0-9]{11}$'", name="ruc_valido"),
        CheckConstraint(f"serie_boleta ~ '{PATRON_SERIE_BOLETA}'", name="serie_boleta_valida"),
        CheckConstraint(f"serie_factura ~ '{PATRON_SERIE_FACTURA}'", name="serie_factura_valida"),
        # Activa solo con RUC y razón social.
        CheckConstraint("NOT emite OR (ruc IS NOT NULL AND razon_social IS NOT NULL)", name="emite_con_datos"),
    )

    colegio_id: Mapped[int] = mapped_column(ForeignKey("colegio.id", ondelete="RESTRICT"), primary_key=True)
    emite: Mapped[bool] = mapped_column(default=False, server_default="false")
    ruc: Mapped[str | None] = mapped_column(String(11))
    razon_social: Mapped[str | None] = mapped_column(String(200))
    serie_boleta: Mapped[str] = mapped_column(String(4), default=SERIE_BOLETA, server_default=SERIE_BOLETA)
    serie_factura: Mapped[str] = mapped_column(String(4), default=SERIE_FACTURA, server_default=SERIE_FACTURA)
    proveedor: Mapped[str] = mapped_column(String(30), default="ninguno", server_default="ninguno")
    # Cifrado con FACTURACION_CLAVE (Fernet). Nunca sale del servidor.
    token_cifrado: Mapped[str | None] = mapped_column(Text)


class SerieComprobante(Base):
    """Último número usado de cada serie. Se toma con bloqueo de fila: sin saltos ni repetidos."""

    __tablename__ = "serie_comprobante"
    __table_args__ = (CheckConstraint("ultimo >= 0", name="ultimo_no_negativo"),)

    colegio_id: Mapped[int] = mapped_column(ForeignKey("colegio.id", ondelete="RESTRICT"), primary_key=True)
    serie: Mapped[str] = mapped_column(String(4), primary_key=True)
    ultimo: Mapped[int] = mapped_column(default=0, server_default="0")


class Comprobante(ConColegio, Base):
    """Boleta o factura de un pago. Los montos siguen el tipo de IGV de cada concepto cobrado."""

    __tablename__ = "comprobante"
    __table_args__ = (
        _fk("pago_id", "pago"),
        UniqueConstraint("colegio_id", "id"),
        UniqueConstraint("colegio_id", "pago_id"),  # un comprobante por pago
        UniqueConstraint("colegio_id", "serie", "numero"),
        CheckConstraint(_en("tipo", TIPOS_COMPROBANTE), name="tipo_valido"),
        CheckConstraint(_en("estado", ESTADOS_COMPROBANTE), name="estado_valido"),
        CheckConstraint("numero > 0", name="numero_positivo"),
        CheckConstraint("gravado >= 0 AND inafecto >= 0 AND igv >= 0", name="montos_no_negativos"),
        CheckConstraint("total = gravado + inafecto + igv", name="total_cuadra"),
        CheckConstraint("intentos >= 0", name="intentos_no_negativos"),
        CheckConstraint("tipo <> 'factura' OR (cliente_tipo_documento = 'RUC' AND cliente_numero_documento ~ '^[0-9]{11}$')",
                        name="factura_con_ruc"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pago_id: Mapped[int] = mapped_column(BigInteger)
    tipo: Mapped[str] = mapped_column(String(10))
    serie: Mapped[str] = mapped_column(String(4))
    numero: Mapped[int]
    cliente_tipo_documento: Mapped[str] = mapped_column(String(4))
    cliente_numero_documento: Mapped[str] = mapped_column(String(20))
    cliente_nombre: Mapped[str] = mapped_column(String(200))
    gravado: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # base imponible, sin IGV
    inafecto: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    igv: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    estado: Mapped[str] = mapped_column(String(10), default="pendiente", server_default="pendiente")
    respuesta: Mapped[str | None] = mapped_column(Text)  # lo último que dijo el proveedor
    enlace_pdf: Mapped[str | None] = mapped_column(String(500))
    enlace_xml: Mapped[str | None] = mapped_column(String(500))
    enlace_cdr: Mapped[str | None] = mapped_column(String(500))
    intentos: Mapped[int] = mapped_column(default=0, server_default="0")
    creado_en: Mapped[datetime] = creado_en()
    anulado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ColaComprobante(ConColegio, Base):
    """Lo que falta hacer ante el proveedor: emitir o anular un comprobante. Si falla, reintenta con espera
    creciente; tras 5 intentos queda en "error" hasta que alguien pulse "Reintentar"."""

    __tablename__ = "cola_comprobante"
    __table_args__ = (
        _fk("comprobante_id", "comprobante"),
        UniqueConstraint("colegio_id", "id"),
        UniqueConstraint("colegio_id", "comprobante_id", "accion"),
        CheckConstraint(_en("accion", ACCIONES_COLA), name="accion_valida"),
        CheckConstraint(_en("estado", ESTADOS_COLA), name="estado_valido"),
        CheckConstraint("(accion = 'anular') = (motivo IS NOT NULL)", name="anular_con_motivo"),
        Index("ix_cola_comprobante_pendientes", "procesar_desde", postgresql_where=text("estado = 'pendiente'")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    comprobante_id: Mapped[int] = mapped_column(BigInteger)
    accion: Mapped[str] = mapped_column(String(10))
    motivo: Mapped[str | None] = mapped_column(String(200))
    estado: Mapped[str] = mapped_column(String(10), default="pendiente", server_default="pendiente")
    intentos: Mapped[int] = mapped_column(default=0, server_default="0")
    procesar_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora_utc)
    procesado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(500))
    # El proveedor recibió la orden pero aún no da el resultado final: se consulta en el siguiente turno.
    datos: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    creado_en: Mapped[datetime] = creado_en()
