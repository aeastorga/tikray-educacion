"""Autorizaciones: el colegio pide permiso a las familias para algo puntual (un paseo, el uso de fotos...) y cada
apoderado responde "Autorizo" o "No autorizo" por cada hijo.

- Nada se borra: una autorización se anula con motivo y queda visible como anulada.
- Los alumnos a los que va se fijan al publicar (`alumno_autorizacion`), con su sección de ese momento.
- Cada respuesta es una fila nueva (Ley 29733: fecha, hora y quién respondió); la vigente es la última (A2, A3).
"""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ConColegio, ahora_utc, creado_en

ALCANCES = ("colegio", "niveles", "secciones", "alumnos")
# "cerrada" se guarda solo al cerrarla a mano; al pasar la fecha límite se muestra cerrada sin cambiar la fila.
ESTADOS = ("borrador", "publicada", "cerrada", "anulada")


def _en(columna: str, valores: tuple[str, ...]) -> str:
    return f"{columna} IN ({', '.join(repr(v) for v in valores)})"


def _fk(columna: str, tabla: str, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    if ondelete == "SET NULL":
        ondelete = f"SET NULL ({columna})"  # solo esa columna, no el colegio_id
    return ForeignKeyConstraint(["colegio_id", columna], [f"{tabla}.colegio_id", f"{tabla}.id"], ondelete=ondelete)


class Autorizacion(ConColegio, Base):
    __tablename__ = "autorizacion"
    __table_args__ = (
        UniqueConstraint("colegio_id", "id"),
        _fk("anio_id", "anio_escolar", "CASCADE"),
        _fk("creado_por_id", "usuario", "SET NULL"),
        _fk("anulado_por_id", "usuario", "SET NULL"),
        CheckConstraint(_en("alcance", ALCANCES), name="alcance_valido"),
        CheckConstraint(_en("estado", ESTADOS), name="estado_valido"),
        CheckConstraint("(estado = 'anulada') = (anulado_motivo IS NOT NULL)", name="anulada_con_motivo"),
        CheckConstraint("estado <> 'borrador' OR publicada_en IS NULL", name="borrador_sin_publicar"),
        CheckConstraint("estado NOT IN ('publicada', 'cerrada') OR publicada_en IS NOT NULL",
                        name="publicada_con_fecha"),
        CheckConstraint("(adjunto_clave IS NULL) = (adjunto_nombre IS NULL)", name="adjunto_completo"),
        Index("ix_autorizacion_colegio_limite", "colegio_id", "fecha_limite"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anio_id: Mapped[int]
    titulo: Mapped[str] = mapped_column(String(120))
    descripcion: Mapped[str | None] = mapped_column(String(2000))
    fecha_actividad: Mapped[date | None] = mapped_column(Date)  # fechas de Lima
    fecha_limite: Mapped[date] = mapped_column(Date)  # se responde hasta el final de ese día
    alcance: Mapped[str] = mapped_column(String(10), default="colegio")
    estado: Mapped[str] = mapped_column(String(10), default="borrador")
    # Adjunto opcional (PDF o imagen) en el almacenamiento privado.
    adjunto_clave: Mapped[str | None] = mapped_column(String(200))
    adjunto_nombre: Mapped[str | None] = mapped_column(String(200))
    adjunto_tipo: Mapped[str | None] = mapped_column(String(100))
    adjunto_tamano: Mapped[int | None]
    creado_por_id: Mapped[int | None]
    creado_en: Mapped[datetime] = creado_en()
    publicada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cerrada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Recordatorio automático del día anterior a la fecha límite (una vez) y el último "Recordar" a mano.
    recordatorio_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recordado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anulado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anulado_motivo: Mapped[str | None] = mapped_column(String(200))
    anulado_por_id: Mapped[int | None]


class DestinoAutorizacion(ConColegio, Base):
    """Un nivel, una sección o un alumno al que va (si no es para todo el colegio). Lo elegido en el formulario;
    al publicar se fijan los alumnos en `alumno_autorizacion`."""

    __tablename__ = "destino_autorizacion"
    __table_args__ = (
        _fk("autorizacion_id", "autorizacion", "CASCADE"),
        _fk("nivel_id", "nivel", "CASCADE"),
        _fk("seccion_id", "seccion", "CASCADE"),
        _fk("alumno_id", "alumno", "CASCADE"),
        CheckConstraint("num_nonnulls(nivel_id, seccion_id, alumno_id) = 1", name="un_destino"),
        UniqueConstraint("colegio_id", "autorizacion_id", "nivel_id"),
        UniqueConstraint("colegio_id", "autorizacion_id", "seccion_id"),
        UniqueConstraint("colegio_id", "autorizacion_id", "alumno_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    autorizacion_id: Mapped[int]
    nivel_id: Mapped[int | None]
    seccion_id: Mapped[int | None]
    alumno_id: Mapped[int | None]


class AlumnoAutorizacion(ConColegio, Base):
    """Cada alumno al que va, fijado al publicar, con su sección de ese momento (para la lista por sección)."""

    __tablename__ = "alumno_autorizacion"
    __table_args__ = (
        _fk("autorizacion_id", "autorizacion", "CASCADE"),
        _fk("alumno_id", "alumno", "CASCADE"),
        _fk("seccion_id", "seccion", "SET NULL"),
        UniqueConstraint("colegio_id", "autorizacion_id", "alumno_id"),
        Index("ix_alumno_autorizacion_alumno", "colegio_id", "alumno_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    autorizacion_id: Mapped[int]
    alumno_id: Mapped[int]
    seccion_id: Mapped[int | None]


class RespuestaAutorizacion(ConColegio, Base):
    """Una respuesta de un apoderado por un hijo. No se edita ni se borra: cambiarla agrega otra fila."""

    __tablename__ = "respuesta_autorizacion"
    __table_args__ = (
        _fk("autorizacion_id", "autorizacion", "CASCADE"),
        _fk("alumno_id", "alumno", "CASCADE"),
        # Si se borra el apoderado, la respuesta queda con su nombre y documento de ese momento.
        _fk("apoderado_id", "apoderado", "SET NULL"),
        Index("ix_respuesta_autorizacion_alumno", "colegio_id", "autorizacion_id", "alumno_id", "respondido_en"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    autorizacion_id: Mapped[int]
    alumno_id: Mapped[int]
    apoderado_id: Mapped[int | None]
    apoderado_nombre: Mapped[str] = mapped_column(String(160))
    apoderado_documento: Mapped[str] = mapped_column(String(20))
    autoriza: Mapped[bool]
    comentario: Mapped[str | None] = mapped_column(String(300))
    respondido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora_utc)
