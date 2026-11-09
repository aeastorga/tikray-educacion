"""Configuración del administrador: plantillas de comunicados, categorías de incidencias e historial de actividad."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ConColegio, creado_en

TIPOS_CATEGORIA = ("merito", "mejora")
ACCIONES = ("crear", "editar", "anular")


class PlantillaComunicado(ConColegio, Base):
    """Asunto y texto listos para elegir en "Escribir"."""

    __tablename__ = "plantilla_comunicado"
    __table_args__ = (UniqueConstraint("colegio_id", "id"), UniqueConstraint("colegio_id", "nombre"))

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80))
    titulo: Mapped[str] = mapped_column(String(200))
    cuerpo: Mapped[str] = mapped_column(Text, default="")
    creado_en: Mapped[datetime] = creado_en()


class CategoriaIncidencia(ConColegio, Base):
    """Participación, Puntualidad, Conducta...: de mérito (la familia la ve en verde) o a mejorar."""

    __tablename__ = "categoria_incidencia"
    __table_args__ = (
        UniqueConstraint("colegio_id", "id"),
        UniqueConstraint("colegio_id", "nombre"),
        CheckConstraint("tipo IN ('merito', 'mejora')", name="tipo_valido"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60))
    tipo: Mapped[str] = mapped_column(String(6))
    activa: Mapped[bool] = mapped_column(default=True)
    orden: Mapped[int] = mapped_column(default=0)


class RegistroActividad(ConColegio, Base):
    """Quién hizo qué. El resumen es corto y nunca lleva datos sensibles (PIN, claves, motivo de una
    licencia, texto de una justificación)."""

    __tablename__ = "registro_actividad"
    __table_args__ = (
        ForeignKeyConstraint(["colegio_id", "usuario_id"], ["usuario.colegio_id", "usuario.id"],
                             ondelete="SET NULL (usuario_id)"),
        CheckConstraint("accion IN ('crear', 'editar', 'anular')", name="accion_valida"),
        Index("ix_registro_actividad_colegio_fecha", "colegio_id", "creado_en"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Quién: alguien del personal, o nadie (Tikray Labs, un proceso); el nombre queda aunque se borre.
    usuario_id: Mapped[int | None]
    quien: Mapped[str] = mapped_column(String(160))
    accion: Mapped[str] = mapped_column(String(8))
    modulo: Mapped[str] = mapped_column(String(20))
    que: Mapped[str] = mapped_column(String(40))  # alumno, apoderado, rol, comunicado...
    objeto_id: Mapped[int | None] = mapped_column(BigInteger)
    resumen: Mapped[str] = mapped_column(String(200))
    creado_en: Mapped[datetime] = creado_en()  # UTC
