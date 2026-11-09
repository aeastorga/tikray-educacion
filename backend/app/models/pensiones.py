"""Pensiones y caja: conceptos de cobro, montos, cronograma, cuotas por alumno, descuentos, caja del
cajero, pagos con su recibo interno y gastos.

Reglas de dinero (las cuida también la base):
- Montos en Numeric(10, 2), nunca float, y siempre >= 0.
- Nada de dinero se borra: pagos, cuotas, descuentos y gastos solo se anulan (motivo, quién y cuándo).
- Las llaves hacia alumno, apoderado, pago y cuota son RESTRICT.
- El saldo de una cuota nunca queda negativo: lo pagado no supera monto - descuento + mora.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index,
                        Numeric, String, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ConColegio, ahora_utc, creado_en

TIPOS_CONCEPTO = ("matricula", "pension", "otro")
TIPOS_IGV = ("gravado", "inafecto")
TIPOS_MORA = ("ninguna", "fijo", "porcentaje")
TIPOS_DESCUENTO = ("porcentaje", "monto")
MEDIOS = ("efectivo", "yape", "plin", "transferencia", "tarjeta")
SERIE_RECIBO = "R001"


def _en(columna: str, valores: tuple[str, ...]) -> str:
    return f"{columna} IN ({', '.join(repr(v) for v in valores)})"


def _fk(columna: str, tabla: str, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    """Llave compuesta (colegio_id, <columna>) -> <tabla>(colegio_id, id)."""
    if ondelete == "SET NULL":
        ondelete = f"SET NULL ({columna})"
    return ForeignKeyConstraint(["colegio_id", columna], [f"{tabla}.colegio_id", f"{tabla}.id"], ondelete=ondelete)


def _dinero() -> Mapped[Decimal]:
    return mapped_column(Numeric(10, 2), default=Decimal("0.00"), server_default="0")


class ConfigPensiones(Base):
    """Lo que decide el administrador para cobrar. Si no hay fila, valen los valores por defecto."""

    __tablename__ = "config_pensiones"
    __table_args__ = (
        CheckConstraint(_en("mora_tipo", TIPOS_MORA), name="mora_tipo_valido"),
        CheckConstraint("mora_valor >= 0", name="mora_valor_no_negativo"),
        CheckConstraint("mora_tipo <> 'porcentaje' OR mora_valor <= 100", name="mora_porcentaje_valido"),
        CheckConstraint("mora_tope IS NULL OR mora_tope >= 0", name="mora_tope_no_negativo"),
        CheckConstraint("dias_aviso_previo BETWEEN 0 AND 30", name="dias_aviso_previo_valido"),
        CheckConstraint("correlativo_recibo >= 0", name="correlativo_no_negativo"),
    )

    colegio_id: Mapped[int] = mapped_column(ForeignKey("colegio.id", ondelete="RESTRICT"), primary_key=True)
    # Mora: apagada por defecto. "fijo": un monto por cuota vencida. "porcentaje": % mensual sobre la cuota
    # (monto menos descuento), sin interés sobre interés. El tope es por cuota.
    mora_tipo: Mapped[str] = mapped_column(String(10), default="ninguna", server_default="ninguna")
    mora_valor: Mapped[Decimal] = _dinero()
    mora_tope: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # Aviso de cobro N días antes del vencimiento (0 = solo el del día que vence).
    dias_aviso_previo: Mapped[int] = mapped_column(default=3, server_default="3")
    # Recibo interno: serie fija y correlativo sin saltos (se toma con bloqueo de esta fila).
    serie_recibo: Mapped[str] = mapped_column(String(4), default=SERIE_RECIBO, server_default=SERIE_RECIBO)
    correlativo_recibo: Mapped[int] = mapped_column(default=0, server_default="0")


class ConceptoCobro(ConColegio, Base):
    """Matrícula, pensión u otro cobro de un año escolar."""

    __tablename__ = "concepto_cobro"
    __table_args__ = (
        _fk("anio_id", "anio_escolar"),
        UniqueConstraint("colegio_id", "anio_id", "nombre"),
        UniqueConstraint("colegio_id", "id"),
        CheckConstraint(_en("tipo", TIPOS_CONCEPTO), name="tipo_valido"),
        CheckConstraint(_en("igv", TIPOS_IGV), name="igv_valido"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anio_id: Mapped[int]
    nombre: Mapped[str] = mapped_column(String(80))
    tipo: Mapped[str] = mapped_column(String(10))
    igv: Mapped[str] = mapped_column(String(10), default="inafecto")
    activo: Mapped[bool] = mapped_column(default=True)
    creado_en: Mapped[datetime] = creado_en()


class MontoConcepto(ConColegio, Base):
    """Cuánto cuesta un concepto para un nivel o para un grado. El del grado manda sobre el del nivel."""

    __tablename__ = "monto_concepto"
    __table_args__ = (
        _fk("concepto_id", "concepto_cobro", "CASCADE"),
        _fk("nivel_id", "nivel"),
        _fk("grado_id", "grado"),
        CheckConstraint("(nivel_id IS NULL) <> (grado_id IS NULL)", name="nivel_o_grado"),
        CheckConstraint("monto >= 0", name="monto_no_negativo"),
        UniqueConstraint("colegio_id", "concepto_id", "grado_id"),
        UniqueConstraint("colegio_id", "concepto_id", "nivel_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    concepto_id: Mapped[int]
    nivel_id: Mapped[int | None]
    grado_id: Mapped[int | None]
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2))


class CuotaProgramada(ConColegio, Base):
    """Una línea del cronograma: "Pensión 1 · Marzo · vence el 31/03"."""

    __tablename__ = "cuota_programada"
    __table_args__ = (
        _fk("concepto_id", "concepto_cobro"),
        UniqueConstraint("colegio_id", "concepto_id", "numero"),
        UniqueConstraint("colegio_id", "id"),
        CheckConstraint("numero BETWEEN 1 AND 24", name="numero_valido"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    concepto_id: Mapped[int]
    numero: Mapped[int]
    mes: Mapped[str] = mapped_column(String(20))
    vence: Mapped[date] = mapped_column(Date)  # fecha de Lima


class CuotaAlumno(ConColegio, Base):
    """Lo que debe un alumno por una línea del cronograma. `pagado` es la suma de los pagos válidos
    (se mantiene al cobrar y al anular). `mora` es la mora ya cargada al cobrar; la del día se calcula."""

    __tablename__ = "cuota_alumno"
    __table_args__ = (
        _fk("alumno_id", "alumno"),
        _fk("cuota_programada_id", "cuota_programada"),
        UniqueConstraint("colegio_id", "alumno_id", "cuota_programada_id"),
        UniqueConstraint("colegio_id", "id"),
        CheckConstraint("monto >= 0", name="monto_no_negativo"),
        CheckConstraint("descuento >= 0 AND descuento <= monto", name="descuento_valido"),
        CheckConstraint("mora >= 0", name="mora_no_negativa"),
        CheckConstraint("pagado >= 0", name="pagado_no_negativo"),
        # El saldo nunca queda negativo.
        CheckConstraint("pagado <= monto - descuento + mora", name="saldo_no_negativo"),
        CheckConstraint("(anulada_en IS NULL) = (anulada_motivo IS NULL)", name="anulada_con_motivo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alumno_id: Mapped[int]
    cuota_programada_id: Mapped[int]
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    descuento: Mapped[Decimal] = _dinero()
    mora: Mapped[Decimal] = _dinero()
    pagado: Mapped[Decimal] = _dinero()
    anulada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anulada_motivo: Mapped[str | None] = mapped_column(String(200))
    anulada_por: Mapped[str | None] = mapped_column(String(160))
    # Avisos de cobro ya encolados (para no repetirlos).
    aviso_previo_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aviso_vencido_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = creado_en()


class DescuentoAlumno(ConColegio, Base):
    """Descuento o beca de un alumno, para un concepto o para todos (concepto vacío)."""

    __tablename__ = "descuento_alumno"
    __table_args__ = (
        _fk("anio_id", "anio_escolar"),
        _fk("alumno_id", "alumno"),
        _fk("concepto_id", "concepto_cobro"),
        _fk("dado_por_id", "usuario", "SET NULL"),
        UniqueConstraint("colegio_id", "id"),
        CheckConstraint(_en("tipo", TIPOS_DESCUENTO), name="tipo_valido"),
        CheckConstraint("valor > 0", name="valor_positivo"),
        CheckConstraint("tipo <> 'porcentaje' OR valor <= 100", name="porcentaje_valido"),
        CheckConstraint("(anulado_en IS NULL) = (anulado_motivo IS NULL)", name="anulado_con_motivo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anio_id: Mapped[int]
    alumno_id: Mapped[int]
    concepto_id: Mapped[int | None]
    tipo: Mapped[str] = mapped_column(String(10))
    valor: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    motivo: Mapped[str] = mapped_column(String(200))
    dado_por_id: Mapped[int | None]
    dado_por: Mapped[str] = mapped_column(String(160))
    creado_en: Mapped[datetime] = creado_en()
    anulado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anulado_motivo: Mapped[str | None] = mapped_column(String(200))
    anulado_por: Mapped[str | None] = mapped_column(String(160))


class CajaSesion(ConColegio, Base):
    """La caja del día de un cajero: se abre, se cobra y se cierra con lo que contó."""

    __tablename__ = "caja_sesion"
    __table_args__ = (
        _fk("usuario_id", "usuario"),
        UniqueConstraint("colegio_id", "id"),
        # Un cajero no tiene dos cajas abiertas.
        Index("uq_caja_sesion_abierta", "colegio_id", "usuario_id", unique=True,
              postgresql_where=text("cerrada_en IS NULL")),
        CheckConstraint("contado IS NULL OR contado >= 0", name="contado_no_negativo"),
        CheckConstraint("(cerrada_en IS NULL) = (contado IS NULL)", name="cierre_con_conteo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int]
    cajero: Mapped[str] = mapped_column(String(160))
    fecha: Mapped[date] = mapped_column(Date)  # día de Lima en que se abrió
    abierta_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora_utc)
    cerrada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Efectivo que contó el cajero al cerrar, y los totales por medio en ese momento.
    contado: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    totales: Mapped[dict | None] = mapped_column(JSONB)


class Pago(ConColegio, Base):
    """Un cobro en caja, con su recibo interno (serie y correlativo sin saltos)."""

    __tablename__ = "pago"
    __table_args__ = (
        _fk("alumno_id", "alumno"),
        _fk("caja_id", "caja_sesion"),
        _fk("cajero_id", "usuario"),
        UniqueConstraint("colegio_id", "id"),
        UniqueConstraint("colegio_id", "serie", "correlativo"),
        CheckConstraint(_en("medio", MEDIOS), name="medio_valido"),
        CheckConstraint("total > 0", name="total_positivo"),
        CheckConstraint("medio = 'efectivo' OR numero_operacion IS NOT NULL", name="operacion_obligatoria"),
        CheckConstraint("(anulado_en IS NULL) = (anulado_motivo IS NULL)", name="anulado_con_motivo"),
        # El número de operación no se repite para el mismo medio (entre pagos válidos).
        Index("uq_pago_operacion", "colegio_id", "medio", "numero_operacion", unique=True,
              postgresql_where=text("numero_operacion IS NOT NULL AND anulado_en IS NULL")),
        Index("ix_pago_colegio_fecha", "colegio_id", "fecha"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alumno_id: Mapped[int]
    caja_id: Mapped[int]
    cajero_id: Mapped[int]
    cajero: Mapped[str] = mapped_column(String(160))
    fecha: Mapped[date] = mapped_column(Date)  # día de Lima
    momento: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora_utc)
    medio: Mapped[str] = mapped_column(String(14))
    numero_operacion: Mapped[str | None] = mapped_column(String(40))
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    serie: Mapped[str] = mapped_column(String(4))
    correlativo: Mapped[int]
    anulado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anulado_motivo: Mapped[str | None] = mapped_column(String(200))
    anulado_por: Mapped[str | None] = mapped_column(String(160))


class PagoDetalle(ConColegio, Base):
    """Cuánto de un pago se aplicó a cada cuota."""

    __tablename__ = "pago_detalle"
    __table_args__ = (
        _fk("pago_id", "pago"),
        _fk("cuota_id", "cuota_alumno"),
        UniqueConstraint("colegio_id", "pago_id", "cuota_id"),
        CheckConstraint("monto > 0", name="monto_positivo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pago_id: Mapped[int] = mapped_column(BigInteger)
    cuota_id: Mapped[int] = mapped_column(BigInteger)
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2))


class CategoriaGasto(ConColegio, Base):
    __tablename__ = "categoria_gasto"
    __table_args__ = (UniqueConstraint("colegio_id", "id"), UniqueConstraint("colegio_id", "nombre"))

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60))
    activa: Mapped[bool] = mapped_column(default=True)
    orden: Mapped[int] = mapped_column(default=0)


class Gasto(ConColegio, Base):
    __tablename__ = "gasto"
    __table_args__ = (
        _fk("categoria_id", "categoria_gasto"),
        _fk("registrado_por_id", "usuario", "SET NULL"),
        UniqueConstraint("colegio_id", "id"),
        CheckConstraint(_en("medio", MEDIOS), name="medio_valido"),
        CheckConstraint("monto > 0", name="monto_positivo"),
        CheckConstraint("(anulado_en IS NULL) = (anulado_motivo IS NULL)", name="anulado_con_motivo"),
        Index("ix_gasto_colegio_fecha", "colegio_id", "fecha"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date)
    categoria_id: Mapped[int]
    descripcion: Mapped[str] = mapped_column(String(200))
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    medio: Mapped[str] = mapped_column(String(14))
    comprobante_tipo: Mapped[str | None] = mapped_column(String(30))
    comprobante_numero: Mapped[str | None] = mapped_column(String(30))
    archivo_clave: Mapped[str | None] = mapped_column(String(300))
    archivo_tipo: Mapped[str | None] = mapped_column(String(40))
    registrado_por_id: Mapped[int | None]
    registrado_por: Mapped[str] = mapped_column(String(160))
    creado_en: Mapped[datetime] = creado_en()
    anulado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anulado_motivo: Mapped[str | None] = mapped_column(String(200))
    anulado_por: Mapped[str | None] = mapped_column(String(160))
