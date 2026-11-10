"""Recojo seguro: quién puede recoger a cada alumno y quién lo recogió.

- `autorizado_recojo`: personas que el colegio o el apoderado autorizan de forma permanente (máximo 5 activas
  por alumno). Nada se borra: se desactiva. No tienen cuenta ni acceso al sistema.
- `autorizacion_recojo_dia`: el apoderado autoriza a alguien solo para una fecha (Lima); vence sola.
- `recojo`: quién se llevó al alumno en una salida. Uno por marcación (la portería puede corregirlo).
  Guarda una copia del nombre y documento: el reporte no cambia si después se edita o desactiva al autorizado.

Ley 29733: el DNI y la foto de quien recoge son datos de terceros y se usan solo para esto.
"""

from datetime import date, datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKeyConstraint, Index, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ConColegio, ahora_utc, creado_en
from app.models.padron import _CK_TIPO_DOC

# Quién lo recogió: un apoderado, un autorizado permanente, uno del día u otra persona (fuera de la lista).
TIPOS_RECOJO = ("apoderado", "autorizado", "del_dia", "otro")
ORIGENES = ("colegio", "familia")


def _fk(columna: str, tabla: str, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    if ondelete == "SET NULL":  # solo esa columna: colegio_id no puede quedar vacío
        ondelete = f"SET NULL ({columna})"
    return ForeignKeyConstraint(["colegio_id", columna], [f"{tabla}.colegio_id", f"{tabla}.id"], ondelete=ondelete)


def _en(columna: str, valores: tuple[str, ...]) -> str:
    return f"{columna} IN ({', '.join(repr(v) for v in valores)})"


class AutorizadoRecojo(ConColegio, Base):
    __tablename__ = "autorizado_recojo"
    __table_args__ = (
        _fk("alumno_id", "alumno", "CASCADE"),
        _fk("creado_por_usuario_id", "usuario", "SET NULL"),
        _fk("creado_por_apoderado_id", "apoderado", "SET NULL"),
        UniqueConstraint("colegio_id", "id"),
        CheckConstraint(_CK_TIPO_DOC, name="tipo_documento_valido"),
        CheckConstraint(_en("origen", ORIGENES), name="origen_valido"),
        Index("ix_autorizado_recojo_alumno", "colegio_id", "alumno_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    alumno_id: Mapped[int]
    nombres: Mapped[str] = mapped_column(String(120))
    apellidos: Mapped[str] = mapped_column(String(120))
    tipo_documento: Mapped[str] = mapped_column(String(4), default="DNI")
    numero_documento: Mapped[str] = mapped_column(String(15))
    parentesco: Mapped[str] = mapped_column(String(30))
    celular: Mapped[str | None] = mapped_column(String(9))
    # Clave en el almacenamiento privado (no se sirve directo: la entrega una ruta que revisa la sesión).
    foto_clave: Mapped[str | None] = mapped_column(String(300))
    foto_tipo: Mapped[str | None] = mapped_column(String(20))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    origen: Mapped[str] = mapped_column(String(10))
    creado_por_usuario_id: Mapped[int | None]
    creado_por_apoderado_id: Mapped[int | None]
    creado_en: Mapped[datetime] = creado_en()


class AutorizacionRecojoDia(ConColegio, Base):
    __tablename__ = "autorizacion_recojo_dia"
    __table_args__ = (
        _fk("alumno_id", "alumno", "CASCADE"),
        _fk("apoderado_id", "apoderado", "CASCADE"),
        UniqueConstraint("colegio_id", "id"),
        CheckConstraint(_CK_TIPO_DOC, name="tipo_documento_valido"),
        Index("ix_autorizacion_recojo_dia_fecha", "colegio_id", "fecha"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    alumno_id: Mapped[int]
    apoderado_id: Mapped[int]  # quién la dio
    fecha: Mapped[date] = mapped_column(Date)  # día en Lima
    nombres: Mapped[str] = mapped_column(String(120))
    apellidos: Mapped[str] = mapped_column(String(120))
    tipo_documento: Mapped[str] = mapped_column(String(4), default="DNI")
    numero_documento: Mapped[str] = mapped_column(String(15))
    parentesco: Mapped[str] = mapped_column(String(30))
    creado_en: Mapped[datetime] = creado_en()
    anulada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Recojo(ConColegio, Base):
    __tablename__ = "recojo"
    __table_args__ = (
        _fk("alumno_id", "alumno", "CASCADE"),
        _fk("marcacion_id", "marcacion", "CASCADE"),
        _fk("apoderado_id", "apoderado", "SET NULL"),
        _fk("autorizado_id", "autorizado_recojo", "SET NULL"),
        _fk("autorizacion_dia_id", "autorizacion_recojo_dia", "SET NULL"),
        _fk("registrado_por_id", "usuario", "SET NULL"),
        UniqueConstraint("colegio_id", "marcacion_id"),
        CheckConstraint(_en("tipo", TIPOS_RECOJO), name="tipo_valido"),
        Index("ix_recojo_colegio_fecha", "colegio_id", "fecha"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    marcacion_id: Mapped[int] = mapped_column(BigInteger)
    alumno_id: Mapped[int]
    fecha: Mapped[date] = mapped_column(Date)  # día en Lima de la salida
    momento: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # hora de la salida (UTC)
    tipo: Mapped[str] = mapped_column(String(10))
    # Fuera de la lista: otra persona, o un autorizado que ya no lo estaba (padrón viejo en la portería).
    fuera_de_lista: Mapped[bool] = mapped_column(Boolean, default=False)
    apoderado_id: Mapped[int | None]
    autorizado_id: Mapped[int | None]
    autorizacion_dia_id: Mapped[int | None]
    # Copia de quién fue, tal como se vio en la portería.
    nombre: Mapped[str] = mapped_column(String(250))
    tipo_documento: Mapped[str] = mapped_column(String(4))
    numero_documento: Mapped[str] = mapped_column(String(15))
    parentesco: Mapped[str | None] = mapped_column(String(30))
    registrado_por_id: Mapped[int | None]
    recibido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora_utc)
