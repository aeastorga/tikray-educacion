"""Asistencia: marcaciones crudas, asistencia del día por persona, licencias
del personal, configuración por colegio y la cola de avisos a familias.

- `marcacion` guarda cada lectura tal como llegó (QR, manual o equipo), con su
  `id_cliente` para que un reenvío desde la portería sin internet no duplique.
- `asistencia_alumno` / `asistencia_personal` es el resultado del día: entrada,
  salida y estado. Una fila por persona y fecha.
- `cola_aviso` la llena la marcación y la vacía un proceso en segundo plano
  (paso 3: push). Una fila por alumno, día y tipo: el mismo aviso no sale dos veces.
"""

from datetime import date, datetime

from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index,
                        String, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ConColegio, ahora_utc, creado_en

ORIGENES = ("qr", "manual", "equipo")
RESULTADOS = ("entrada", "salida", "duplicada")
# justificada: una falta cubierta por una justificación aprobada del cuaderno.
ESTADOS_ALUMNO = ("presente", "tarde", "falta", "justificada")
ESTADOS_PERSONAL = ("presente", "tarde", "falta", "licencia")
TIPOS_LICENCIA = ("salud", "personal", "vacaciones", "comision", "maternidad", "otro")
TIPOS_AVISO = ("ingreso", "tarde", "salida", "falta", "cuenta", "cuaderno", "cobro")
# Los que van a un apoderado (y no a los apoderados de un alumno).
AVISOS_A_APODERADO = ("cuenta", "cuaderno", "cobro")
ESTADOS_AVISO = ("pendiente", "enviado", "sin_destinatarios", "descartado", "error")


def _en(columna: str, valores: tuple[str, ...]) -> str:
    return f"{columna} IN ({', '.join(repr(v) for v in valores)})"


def _fk(columna: str, tabla: str, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["colegio_id", columna], [f"{tabla}.colegio_id", f"{tabla}.id"], ondelete=ondelete)


class ConfigAsistencia(Base):
    """Reglas de asistencia que decide el director. Si no hay fila, valen los valores por defecto."""

    __tablename__ = "config_asistencia"
    __table_args__ = (
        CheckConstraint("minutos_duplicado BETWEEN 1 AND 120", name="minutos_duplicado_valido"),
        CheckConstraint("minutos_corte_falta BETWEEN 15 AND 600", name="minutos_corte_falta_valido"),
    )

    colegio_id: Mapped[int] = mapped_column(ForeignKey("colegio.id", ondelete="CASCADE"), primary_key=True)
    # Dos lecturas de la misma persona con menos de estos minutos son una sola (doble marcación).
    minutos_duplicado: Mapped[int] = mapped_column(default=10)
    # Minutos después de la hora de entrada del turno en que se marca falta a quien no llegó.
    minutos_corte_falta: Mapped[int] = mapped_column(default=90)


class Marcacion(ConColegio, Base):
    __tablename__ = "marcacion"
    __table_args__ = (
        UniqueConstraint("colegio_id", "id_cliente"),
        _fk("alumno_id", "alumno", "CASCADE"),
        _fk("usuario_id", "usuario", "CASCADE"),
        _fk("registrado_por_id", "usuario", "SET NULL"),
        CheckConstraint("(alumno_id IS NULL) <> (usuario_id IS NULL)", name="una_persona"),
        CheckConstraint(_en("origen", ORIGENES), name="origen_valido"),
        CheckConstraint(_en("resultado", RESULTADOS), name="resultado_valido"),
        Index("ix_marcacion_colegio_fecha", "colegio_id", "fecha"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Lo genera el dispositivo: si reenvía la misma marcación (sin internet, reintento), no se duplica.
    id_cliente: Mapped[str] = mapped_column(String(64))
    alumno_id: Mapped[int | None]
    usuario_id: Mapped[int | None]
    momento: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # UTC, la hora en que se leyó
    fecha: Mapped[date] = mapped_column(Date)  # día en Lima
    origen: Mapped[str] = mapped_column(String(10))
    equipo: Mapped[str | None] = mapped_column(String(60))
    registrado_por_id: Mapped[int | None]
    resultado: Mapped[str] = mapped_column(String(10))
    recibido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora_utc)


class AsistenciaAlumno(ConColegio, Base):
    __tablename__ = "asistencia_alumno"
    __table_args__ = (
        UniqueConstraint("colegio_id", "alumno_id", "fecha"),
        _fk("alumno_id", "alumno", "CASCADE"),
        _fk("seccion_id", "seccion", "SET NULL"),
        ForeignKeyConstraint(["colegio_id", "justificacion_id"], ["entrada_cuaderno.colegio_id", "entrada_cuaderno.id"],
                             ondelete="SET NULL (justificacion_id)"),
        CheckConstraint(_en("estado", ESTADOS_ALUMNO), name="estado_valido"),
        Index("ix_asistencia_alumno_colegio_fecha", "colegio_id", "fecha"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alumno_id: Mapped[int]
    fecha: Mapped[date] = mapped_column(Date)
    # Sección de ese día: los reportes no cambian si después el alumno cambia de sección.
    seccion_id: Mapped[int | None]
    estado: Mapped[str] = mapped_column(String(12))
    entrada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    salida: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    minutos_tarde: Mapped[int] = mapped_column(default=0)
    # La justificación que convirtió la falta en "justificada" (para revertirla si se anula).
    justificacion_id: Mapped[int | None] = mapped_column(BigInteger)


class AsistenciaPersonal(ConColegio, Base):
    __tablename__ = "asistencia_personal"
    __table_args__ = (
        UniqueConstraint("colegio_id", "usuario_id", "fecha"),
        _fk("usuario_id", "usuario", "CASCADE"),
        CheckConstraint(_en("estado", ESTADOS_PERSONAL), name="estado_valido"),
        Index("ix_asistencia_personal_colegio_fecha", "colegio_id", "fecha"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int]
    fecha: Mapped[date] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(10))
    entrada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    salida: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    minutos_tarde: Mapped[int] = mapped_column(default=0)


class LicenciaPersonal(ConColegio, Base):
    __tablename__ = "licencia_personal"
    __table_args__ = (
        _fk("usuario_id", "usuario", "CASCADE"),
        _fk("registrado_por_id", "usuario", "SET NULL"),
        CheckConstraint("hasta >= desde", name="fechas_validas"),
        CheckConstraint(_en("tipo", TIPOS_LICENCIA), name="tipo_valido"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int]
    tipo: Mapped[str] = mapped_column(String(12))
    desde: Mapped[date] = mapped_column(Date)
    hasta: Mapped[date] = mapped_column(Date)
    motivo: Mapped[str | None] = mapped_column(String(200))
    registrado_por_id: Mapped[int | None]
    creado_en: Mapped[datetime] = creado_en()


class ColaAviso(ConColegio, Base):
    """Avisos a familias. De un alumno (ingreso, tarde, salida, falta) o a un apoderado:
    "cuenta" (p. ej. cambió su celular en el colegio) o "cuaderno" (una novedad en el cuaderno)."""

    __tablename__ = "cola_aviso"
    __table_args__ = (
        _fk("alumno_id", "alumno", "CASCADE"),
        _fk("apoderado_id", "apoderado", "CASCADE"),
        UniqueConstraint("colegio_id", "alumno_id", "fecha", "tipo"),
        UniqueConstraint("colegio_id", "id"),
        CheckConstraint("(alumno_id IS NULL) <> (apoderado_id IS NULL)", name="un_destino"),
        CheckConstraint(f"({_en('tipo', AVISOS_A_APODERADO)}) = (apoderado_id IS NOT NULL)",
                        name="tipo_segun_destino"),
        CheckConstraint(_en("tipo", TIPOS_AVISO), name="tipo_valido"),
        CheckConstraint(_en("estado", ESTADOS_AVISO), name="estado_valido"),
        # Lo que busca el proceso de envío: pendientes cuyo turno ya llegó.
        Index("ix_cola_aviso_pendientes", "procesar_desde", postgresql_where=text("estado = 'pendiente'")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(10))
    alumno_id: Mapped[int | None]
    apoderado_id: Mapped[int | None]
    fecha: Mapped[date] = mapped_column(Date)
    momento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    datos: Mapped[dict] = mapped_column(JSONB, default=dict)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")
    intentos: Mapped[int] = mapped_column(default=0)
    procesar_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora_utc)
    procesado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = creado_en()
