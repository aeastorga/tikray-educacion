"""Padrón: año escolar, estructura (niveles, grados, turnos, secciones),
calendario de días no lectivos, alumnos, matrículas y apoderados.

Toda relación entre tablas del padrón usa llave compuesta con `colegio_id`,
así la base rechaza, por ejemplo, matricular en una sección de otro colegio.
"""

from datetime import date, datetime, time

from sqlalchemy import (CheckConstraint, ForeignKeyConstraint, Index, String, UniqueConstraint,
                        text)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ConColegio, creado_en
from app.validacion import TIPOS_DOCUMENTO

_CK_TIPO_DOC = f"tipo_documento IN ({', '.join(repr(t) for t in TIPOS_DOCUMENTO)})"


def _fk(columna: str, tabla: str, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    """Llave compuesta (colegio_id, <columna>) -> <tabla>(colegio_id, id)."""
    return ForeignKeyConstraint(
        ["colegio_id", columna], [f"{tabla}.colegio_id", f"{tabla}.id"], ondelete=ondelete,
    )


class AnioEscolar(ConColegio, Base):
    __tablename__ = "anio_escolar"
    __table_args__ = (
        UniqueConstraint("colegio_id", "anio"),
        UniqueConstraint("colegio_id", "id"),
        CheckConstraint("fin > inicio", name="fechas_validas"),
        CheckConstraint("dias_semana ~ '^1?2?3?4?5?6?7?$' AND dias_semana <> ''", name="dias_semana_validos"),
        # Un solo año activo por colegio.
        Index("uq_anio_escolar_activo", "colegio_id", unique=True, postgresql_where=text("activo")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anio: Mapped[int]
    inicio: Mapped[date]
    fin: Mapped[date]
    # Días de clase de la semana, ISO (1 = lunes ... 7 = domingo). "123456" si hay clases los sábados.
    dias_semana: Mapped[str] = mapped_column(String(7), default="12345")
    activo: Mapped[bool] = mapped_column(default=False)
    creado_en: Mapped[datetime] = creado_en()


class Nivel(ConColegio, Base):
    __tablename__ = "nivel"
    __table_args__ = (UniqueConstraint("colegio_id", "nombre"), UniqueConstraint("colegio_id", "id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60))
    orden: Mapped[int] = mapped_column(default=0)


class Grado(ConColegio, Base):
    __tablename__ = "grado"
    __table_args__ = (
        _fk("nivel_id", "nivel"),
        UniqueConstraint("colegio_id", "nivel_id", "nombre"),
        UniqueConstraint("colegio_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nivel_id: Mapped[int]
    nombre: Mapped[str] = mapped_column(String(60))
    orden: Mapped[int] = mapped_column(default=0)


class Turno(ConColegio, Base):
    """Horario de entrada y salida; la tardanza se calcula con la tolerancia."""

    __tablename__ = "turno"
    __table_args__ = (
        UniqueConstraint("colegio_id", "nombre"),
        UniqueConstraint("colegio_id", "id"),
        CheckConstraint("hora_salida > hora_entrada", name="horas_validas"),
        CheckConstraint("tolerancia_minutos BETWEEN 0 AND 120", name="tolerancia_valida"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60))
    # Horas de reloj en Lima (no son instantes, no llevan zona).
    hora_entrada: Mapped[time]
    tolerancia_minutos: Mapped[int] = mapped_column(default=0)
    hora_salida: Mapped[time]


class Seccion(ConColegio, Base):
    __tablename__ = "seccion"
    __table_args__ = (
        _fk("anio_id", "anio_escolar"),
        _fk("grado_id", "grado"),
        _fk("turno_id", "turno"),
        UniqueConstraint("colegio_id", "anio_id", "grado_id", "nombre"),
        UniqueConstraint("colegio_id", "id"),
        # Destino de matricula: la sección debe ser del mismo año que la matrícula.
        UniqueConstraint("colegio_id", "anio_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anio_id: Mapped[int]
    grado_id: Mapped[int]
    turno_id: Mapped[int]
    nombre: Mapped[str] = mapped_column(String(20))


class DiaNoLectivo(ConColegio, Base):
    __tablename__ = "dia_no_lectivo"
    __table_args__ = (_fk("anio_id", "anio_escolar", "CASCADE"), UniqueConstraint("colegio_id", "fecha"))

    id: Mapped[int] = mapped_column(primary_key=True)
    anio_id: Mapped[int]
    fecha: Mapped[date]
    motivo: Mapped[str] = mapped_column(String(120))


class Alumno(ConColegio, Base):
    __tablename__ = "alumno"
    __table_args__ = (
        UniqueConstraint("colegio_id", "tipo_documento", "numero_documento"),
        # Lo que lleva el QR del carnet. No es el DNI, para no exponerlo.
        UniqueConstraint("colegio_id", "codigo"),
        UniqueConstraint("colegio_id", "id"),
        CheckConstraint(_CK_TIPO_DOC, name="tipo_documento_valido"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo_documento: Mapped[str] = mapped_column(String(4), default="DNI")
    numero_documento: Mapped[str] = mapped_column(String(15))
    nombres: Mapped[str] = mapped_column(String(120))
    apellidos: Mapped[str] = mapped_column(String(120))
    fecha_nacimiento: Mapped[date | None]
    codigo: Mapped[str] = mapped_column(String(12))
    activo: Mapped[bool] = mapped_column(default=True)
    creado_en: Mapped[datetime] = creado_en()


class Matricula(ConColegio, Base):
    __tablename__ = "matricula"
    __table_args__ = (
        _fk("alumno_id", "alumno", "CASCADE"),
        _fk("anio_id", "anio_escolar"),
        ForeignKeyConstraint(
            ["colegio_id", "anio_id", "seccion_id"],
            ["seccion.colegio_id", "seccion.anio_id", "seccion.id"], ondelete="RESTRICT",
        ),
        UniqueConstraint("colegio_id", "anio_id", "alumno_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anio_id: Mapped[int]
    alumno_id: Mapped[int]
    seccion_id: Mapped[int]


class Apoderado(ConColegio, Base):
    __tablename__ = "apoderado"
    __table_args__ = (
        UniqueConstraint("colegio_id", "tipo_documento", "numero_documento"),
        UniqueConstraint("colegio_id", "id"),
        CheckConstraint(_CK_TIPO_DOC, name="tipo_documento_valido"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo_documento: Mapped[str] = mapped_column(String(4), default="DNI")
    numero_documento: Mapped[str] = mapped_column(String(15))
    nombres: Mapped[str] = mapped_column(String(120))
    apellidos: Mapped[str] = mapped_column(String(120))
    # Solo dígitos, sin +51 (9 dígitos que empiezan con 9).
    celular: Mapped[str | None] = mapped_column(String(9))
    correo: Mapped[str | None] = mapped_column(String(254))
    creado_en: Mapped[datetime] = creado_en()


class AlumnoApoderado(ConColegio, Base):
    """Apoderado ↔ alumno es N a N (un hijo con dos apoderados, hermanos con el mismo)."""

    __tablename__ = "alumno_apoderado"
    __table_args__ = (
        _fk("alumno_id", "alumno", "CASCADE"),
        _fk("apoderado_id", "apoderado", "CASCADE"),
    )

    alumno_id: Mapped[int] = mapped_column(primary_key=True)
    apoderado_id: Mapped[int] = mapped_column(primary_key=True)
    parentesco: Mapped[str] = mapped_column(String(30))
    recibe_avisos: Mapped[bool] = mapped_column(default=True)
