"""Calendario escolar: eventos por año escolar (actuaciones, reuniones, exámenes...) y a quién van.

Los días sin clases no están aquí: son `dia_no_lectivo` (Estructura), que el calendario solo muestra.
Un evento no se borra: se anula con motivo y queda visible como anulado.
"""

from datetime import date, datetime, time

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKeyConstraint, Index, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ConColegio, creado_en

# C1: tipos fijos.
TIPOS_EVENTO = ("actuacion", "reunion_padres", "examen", "feriado", "salida", "otro")
# A quién va: todo el colegio, uno o varios niveles, o una o varias secciones.
ALCANCES = ("colegio", "niveles", "secciones")


def _en(columna: str, valores: tuple[str, ...]) -> str:
    return f"{columna} IN ({', '.join(repr(v) for v in valores)})"


def _fk(columna: str, tabla: str, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    if ondelete == "SET NULL":
        ondelete = f"SET NULL ({columna})"  # solo esa columna, no el colegio_id
    return ForeignKeyConstraint(["colegio_id", columna], [f"{tabla}.colegio_id", f"{tabla}.id"], ondelete=ondelete)


class EventoCalendario(ConColegio, Base):
    __tablename__ = "evento_calendario"
    __table_args__ = (
        UniqueConstraint("colegio_id", "id"),
        _fk("anio_id", "anio_escolar", "CASCADE"),
        _fk("creado_por_id", "usuario", "SET NULL"),
        _fk("anulado_por_id", "usuario", "SET NULL"),
        CheckConstraint("fin >= inicio", name="fechas_validas"),
        CheckConstraint(_en("tipo", TIPOS_EVENTO), name="tipo_valido"),
        CheckConstraint(_en("alcance", ALCANCES), name="alcance_valido"),
        CheckConstraint("(anulado_en IS NULL) = (anulado_motivo IS NULL)", name="anulado_con_motivo"),
        Index("ix_evento_calendario_colegio_fechas", "colegio_id", "inicio", "fin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anio_id: Mapped[int]
    titulo: Mapped[str] = mapped_column(String(120))
    descripcion: Mapped[str | None] = mapped_column(String(1000))
    inicio: Mapped[date] = mapped_column(Date)  # fechas de Lima
    fin: Mapped[date] = mapped_column(Date)
    hora: Mapped[time | None] = mapped_column(Time)  # hora de Lima, opcional
    tipo: Mapped[str] = mapped_column(String(20))
    alcance: Mapped[str] = mapped_column(String(10), default="colegio")
    # C4/C5: aviso al publicar y recordatorio el día anterior, solo si quien lo crea lo marca.
    avisar: Mapped[bool] = mapped_column(default=False)
    # Cuándo se encolaron (para no repetir). El recordatorio se marca también cuando ya no hace falta.
    aviso_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recordatorio_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_por_id: Mapped[int | None]
    creado_en: Mapped[datetime] = creado_en()
    anulado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anulado_motivo: Mapped[str | None] = mapped_column(String(200))
    anulado_por_id: Mapped[int | None]


class DestinoEvento(ConColegio, Base):
    """Un nivel o una sección a la que va el evento (si no es para todo el colegio)."""

    __tablename__ = "destino_evento"
    __table_args__ = (
        _fk("evento_id", "evento_calendario", "CASCADE"),
        # Un nivel o una sección solo se pueden borrar sin grados ni alumnos; si se borran, salen del evento.
        _fk("nivel_id", "nivel", "CASCADE"),
        _fk("seccion_id", "seccion", "CASCADE"),
        CheckConstraint("(nivel_id IS NULL) <> (seccion_id IS NULL)", name="un_destino"),
        UniqueConstraint("colegio_id", "evento_id", "nivel_id"),
        UniqueConstraint("colegio_id", "evento_id", "seccion_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    evento_id: Mapped[int]
    nivel_id: Mapped[int | None]
    seccion_id: Mapped[int | None]
