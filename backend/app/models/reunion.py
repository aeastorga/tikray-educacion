"""Modo reunión: el tutor muestra un QR de su aula en la reunión de padres y cada padre llena su
ficha (sus datos, los del otro apoderado y el consentimiento) desde su celular o una tablet.

No es un registro abierto: el QR vale unas horas, solo para alumnos de esa sección (el padre
escribe el documento del hijo), con límite de intentos, y nada entra al padrón hasta que el
tutor aprueba la ficha con el padre delante. Al aprobar puede activar la cuenta en el momento.

El QR no se guarda: es `<id>.<firma>`, con la firma calculada con SECRET_KEY y `nonce` (que
cambia si se genera uno nuevo). Las fichas guardan lo que escribió el padre tal cual (`datos`);
los cambios frente al padrón se calculan al mostrarlas, y solo se aplican al aprobar.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ConColegio, ahora_utc, creado_en

ORIGENES = ("celular", "quiosco", "papel")
ESTADOS = ("pendiente", "aprobada", "rechazada")


def _fk(columna: str, tabla: str, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    if ondelete == "SET NULL":
        ondelete = f"SET NULL ({columna})"  # colegio_id es parte de la llave y no puede quedar en NULL
    return ForeignKeyConstraint(["colegio_id", columna], [f"{tabla}.colegio_id", f"{tabla}.id"], ondelete=ondelete)


def _en(columna: str, valores: tuple[str, ...]) -> str:
    return f"{columna} IN ({', '.join(repr(v) for v in valores)})"


class ReunionPadres(ConColegio, Base):
    __tablename__ = "reunion_padres"
    __table_args__ = (
        _fk("seccion_id", "seccion", "CASCADE"),
        _fk("creado_por_id", "usuario", "SET NULL"),
        UniqueConstraint("colegio_id", "id"),
        CheckConstraint("vence_en > creado_en", name="vence_despues"),
        CheckConstraint("vence_en <= creado_en + interval '12 hours'", name="vigencia_maxima"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    seccion_id: Mapped[int]
    titulo: Mapped[str] = mapped_column(String(120), default="Reunión de padres")
    nonce: Mapped[str] = mapped_column(String(32))
    creado_por_id: Mapped[int | None]
    creado_en: Mapped[datetime] = creado_en()
    vence_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cerrada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Documentos de alumno equivocados con este QR. Al pasar el tope, el QR deja de servir.
    intentos_fallidos: Mapped[int] = mapped_column(default=0, server_default="0")


class FichaReunion(ConColegio, Base):
    __tablename__ = "ficha_reunion"
    __table_args__ = (
        _fk("reunion_id", "reunion_padres", "CASCADE"),
        _fk("alumno_id", "alumno", "CASCADE"),
        _fk("apoderado_id", "apoderado", "SET NULL"),
        _fk("otro_apoderado_id", "apoderado", "SET NULL"),
        _fk("invitacion_id", "invitacion_familia", "SET NULL"),
        _fk("revisado_por_id", "usuario", "SET NULL"),
        _fk("dni_verificado_por_id", "usuario", "SET NULL"),
        CheckConstraint("(dni_verificado_en IS NULL) = (dni_verificado_por IS NULL)", name="verificacion_completa"),
        CheckConstraint(_en("origen", ORIGENES), name="origen_valido"),
        CheckConstraint(_en("estado", ESTADOS), name="estado_valido"),
        CheckConstraint("estado = 'pendiente' OR revisado_en IS NOT NULL", name="revisada_con_fecha"),
        Index("ix_ficha_reunion_reunion", "colegio_id", "reunion_id", "estado"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reunion_id: Mapped[int]
    alumno_id: Mapped[int]
    origen: Mapped[str] = mapped_column(String(10))
    # Lo que escribió el padre: {"apoderado": {...}, "otro": {...} | null}. Documento normalizado.
    datos: Mapped[dict] = mapped_column(JSONB)
    documento: Mapped[str] = mapped_column(String(15))  # del que llena, para reemplazar su ficha si la reenvía
    consentimiento_version: Mapped[str] = mapped_column(String(20))
    ip: Mapped[str | None] = mapped_column(String(45))
    # Hash del código que se queda en el celular del padre: con él ve si lo aprobaron y crea su PIN.
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    estado: Mapped[str] = mapped_column(String(10), default="pendiente")
    apoderado_id: Mapped[int | None]
    otro_apoderado_id: Mapped[int | None]
    invitacion_id: Mapped[int | None]  # al aprobar con "activar la cuenta ahora"
    revisado_por_id: Mapped[int | None]
    revisado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_rechazo: Mapped[str | None] = mapped_column(String(200))
    # "Verifiqué su DNI en persona": obligatorio al aprobar si suma un apoderado o cambia un celular.
    # El nombre se copia para que el registro no dependa de que el usuario siga existiendo.
    dni_verificado_por_id: Mapped[int | None]
    dni_verificado_por: Mapped[str | None] = mapped_column(String(250))
    dni_verificado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = creado_en()
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora_utc)
