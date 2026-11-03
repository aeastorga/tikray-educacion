"""Cuaderno de control: todo lo que el colegio y la familia se dicen por escrito.

Una sola tabla de entradas (`entrada_cuaderno`) con un `tipo`:

- comunicado: del colegio a todo el colegio, un nivel, un grado, una sección o un alumno.
- incidencia: del colegio sobre un alumno.
- citacion: del colegio a los apoderados de un alumno, con fecha, hora y lugar.
- justificacion: del padre (o registrada por el colegio) por faltas de unas fechas; el colegio la aprueba.
- permiso_salida: el padre pide (o el colegio registra) que el alumno salga antes; la portería lo ve.

`destino_cuaderno` guarda, al crear la entrada, a quién le llega: una fila por alumno y
apoderado. Ahí queda cuándo la vio y cuándo firmó (comunicado e incidencia: "enterado";
citación: "asistiré"). Así el colegio ve quién leyó y quién no, aunque después cambie el padrón.

`mensaje_cuaderno` es el hilo de respuestas de cada entrada. Los adjuntos van al
almacenamiento privado de archivos (no a la base ni a /archivos): `adjunto_cuaderno`
solo guarda la clave, el nombre y el tamaño.
"""

from datetime import date, datetime, time

from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, ForeignKeyConstraint, Index, String, Text, Time,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ConColegio, creado_en

TIPOS = ("comunicado", "incidencia", "citacion", "justificacion", "permiso_salida")
ALCANCES = ("colegio", "nivel", "grado", "seccion", "alumno")
# Solo justificación y permiso de salida. anulada: estaba aprobada y el colegio la anuló.
ESTADOS = ("pendiente", "aprobada", "rechazada", "anulada")
# Los que siempre son de un alumno.
DE_UN_ALUMNO = ("incidencia", "citacion", "justificacion", "permiso_salida")
CON_RESOLUCION = ("justificacion", "permiso_salida")


def _en(columna: str, valores: tuple[str, ...]) -> str:
    return f"{columna} IN ({', '.join(repr(v) for v in valores)})"


def _fk(columna: str, tabla: str, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    # SET NULL solo de la columna (PostgreSQL 15+): colegio_id es parte de la llave y no puede quedar en NULL.
    if ondelete == "SET NULL":
        ondelete = f"SET NULL ({columna})"
    return ForeignKeyConstraint(["colegio_id", columna], [f"{tabla}.colegio_id", f"{tabla}.id"], ondelete=ondelete)


class SeccionDocente(ConColegio, Base):
    """Secciones a cargo de cada persona del personal (tutor, docente). Un rol con
    `solo_sus_secciones` solo ve en el cuaderno lo de estas secciones."""

    __tablename__ = "seccion_docente"
    __table_args__ = (_fk("seccion_id", "seccion", "CASCADE"), _fk("usuario_id", "usuario", "CASCADE"))

    seccion_id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(primary_key=True)


class EntradaCuaderno(ConColegio, Base):
    __tablename__ = "entrada_cuaderno"
    __table_args__ = (
        UniqueConstraint("colegio_id", "id"),
        _fk("nivel_id", "nivel"),
        _fk("grado_id", "grado"),
        _fk("seccion_id", "seccion", "SET NULL"),
        _fk("alumno_id", "alumno", "CASCADE"),
        _fk("creado_por_id", "usuario", "SET NULL"),
        _fk("apoderado_autor_id", "apoderado", "SET NULL"),
        _fk("resuelto_por_id", "usuario", "SET NULL"),
        _fk("anulada_por_id", "usuario", "SET NULL"),
        CheckConstraint(_en("tipo", TIPOS), name="tipo_valido"),
        CheckConstraint(_en("alcance", ALCANCES), name="alcance_valido"),
        CheckConstraint(f"tipo = 'comunicado' OR alcance = 'alumno'", name="de_un_alumno"),
        # El destino que corresponde al alcance (la sección de un alumno es solo para filtrar).
        CheckConstraint("(alcance = 'nivel') = (nivel_id IS NOT NULL)", name="destino_nivel"),
        CheckConstraint("(alcance = 'grado') = (grado_id IS NOT NULL)", name="destino_grado"),
        CheckConstraint("alcance <> 'seccion' OR seccion_id IS NOT NULL", name="destino_seccion"),
        CheckConstraint("alcance NOT IN ('colegio', 'nivel', 'grado') OR seccion_id IS NULL", name="sin_seccion"),
        CheckConstraint("(alcance = 'alumno') = (alumno_id IS NOT NULL)", name="destino_alumno"),
        CheckConstraint(f"(tipo IN {CON_RESOLUCION!r}) = (estado IS NOT NULL)", name="estado_segun_tipo"),
        CheckConstraint(f"estado IS NULL OR {_en('estado', ESTADOS)}", name="estado_valido"),
        CheckConstraint("tipo <> 'citacion' OR cita_en IS NOT NULL", name="citacion_con_fecha"),
        CheckConstraint("tipo <> 'justificacion' OR (desde IS NOT NULL AND hasta >= desde)", name="justificacion_fechas"),
        CheckConstraint("tipo <> 'permiso_salida' OR (desde IS NOT NULL AND hora_salida IS NOT NULL)",
                        name="permiso_con_hora"),
        CheckConstraint("creado_por_id IS NULL OR apoderado_autor_id IS NULL", name="un_autor"),
        _fk("categoria_id", "categoria_incidencia", "SET NULL"),
        CheckConstraint("categoria_id IS NULL OR tipo = 'incidencia'", name="categoria_solo_incidencia"),
        CheckConstraint("programado_para IS NULL OR tipo = 'comunicado'", name="programado_solo_comunicado"),
        Index("ix_entrada_cuaderno_colegio_creado", "colegio_id", "creado_en"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(16))
    alcance: Mapped[str] = mapped_column(String(10))
    nivel_id: Mapped[int | None]
    grado_id: Mapped[int | None]
    # Alcance sección: la sección. Alcance alumno: su sección al crearla (para que el docente la vea).
    seccion_id: Mapped[int | None]
    alumno_id: Mapped[int | None]
    titulo: Mapped[str] = mapped_column(String(200))
    cuerpo: Mapped[str] = mapped_column(Text, default="")
    # Comunicado: el colegio pide que cada apoderado firme que lo leyó.
    pide_firma: Mapped[bool] = mapped_column(default=False)
    # Citación.
    cita_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lugar: Mapped[str | None] = mapped_column(String(120))
    # Justificación: días que justifica. Permiso de salida: `desde` es el día.
    desde: Mapped[date | None] = mapped_column(Date)
    hasta: Mapped[date | None] = mapped_column(Date)
    hora_salida: Mapped[time | None] = mapped_column(Time)  # hora de Lima
    recoge: Mapped[str | None] = mapped_column(String(120))  # quién lo recoge
    # Justificación y permiso: pendiente hasta que el colegio resuelve.
    estado: Mapped[str | None] = mapped_column(String(10))
    resuelto_por_id: Mapped[int | None]
    resuelto_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nota_resolucion: Mapped[str | None] = mapped_column(String(300))
    anulada_por_id: Mapped[int | None]
    anulada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_anulacion: Mapped[str | None] = mapped_column(String(300))
    # Autor: alguien del personal o un apoderado (justificación o permiso pedidos por el padre).
    creado_por_id: Mapped[int | None]
    apoderado_autor_id: Mapped[int | None]
    creado_en: Mapped[datetime] = creado_en()
    # Incidencia: su categoría (mérito o a mejorar).
    categoria_id: Mapped[int | None]
    # Comunicado programado: la familia no lo ve ni recibe el aviso hasta esta hora (UTC).
    programado_para: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DestinoCuaderno(ConColegio, Base):
    __tablename__ = "destino_cuaderno"
    __table_args__ = (
        _fk("entrada_id", "entrada_cuaderno", "CASCADE"),
        _fk("alumno_id", "alumno", "CASCADE"),
        _fk("apoderado_id", "apoderado", "CASCADE"),
        Index("ix_destino_cuaderno_apoderado", "colegio_id", "apoderado_id"),
    )

    entrada_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alumno_id: Mapped[int] = mapped_column(primary_key=True)
    apoderado_id: Mapped[int] = mapped_column(primary_key=True)
    visto_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    firmado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MensajeCuaderno(ConColegio, Base):
    """Respuesta en el hilo de una entrada, del personal o de un apoderado."""

    __tablename__ = "mensaje_cuaderno"
    __table_args__ = (
        _fk("entrada_id", "entrada_cuaderno", "CASCADE"),
        _fk("usuario_id", "usuario", "SET NULL"),
        _fk("apoderado_id", "apoderado", "SET NULL"),
        CheckConstraint("usuario_id IS NULL OR apoderado_id IS NULL", name="un_autor"),
        Index("ix_mensaje_cuaderno_entrada", "colegio_id", "entrada_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entrada_id: Mapped[int] = mapped_column(BigInteger)
    usuario_id: Mapped[int | None]
    apoderado_id: Mapped[int | None]
    # Lo dijo la familia (aunque luego se borre el apoderado, sigue sabiéndose de qué lado vino).
    de_familia: Mapped[bool]
    cuerpo: Mapped[str] = mapped_column(Text)
    creado_en: Mapped[datetime] = creado_en()


class AdjuntoCuaderno(ConColegio, Base):
    __tablename__ = "adjunto_cuaderno"
    __table_args__ = (
        _fk("entrada_id", "entrada_cuaderno", "CASCADE"),
        UniqueConstraint("clave"),
        CheckConstraint("tamano > 0", name="tamano_valido"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entrada_id: Mapped[int] = mapped_column(BigInteger)
    clave: Mapped[str] = mapped_column(String(300))  # en el almacenamiento privado
    nombre: Mapped[str] = mapped_column(String(200))
    tipo_mime: Mapped[str] = mapped_column(String(100))
    tamano: Mapped[int]
    creado_en: Mapped[datetime] = creado_en()
