from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ahora_utc, creado_en


class AdminPlataforma(Base):
    """Personal de Tikray Labs. No pertenece a ningún colegio y entra solo por /plataforma."""

    __tablename__ = "admin_plataforma"

    id: Mapped[int] = mapped_column(primary_key=True)
    correo: Mapped[str] = mapped_column(String(254), unique=True)
    nombre: Mapped[str] = mapped_column(String(200))
    clave_hash: Mapped[str] = mapped_column(String(255))
    activo: Mapped[bool] = mapped_column(default=True)
    version_sesion: Mapped[int] = mapped_column(default=0)
    creado_en: Mapped[datetime] = creado_en()


class IntentoFallido(Base):
    """Ingresos fallidos (clave o PIN incorrecto) para el límite de intentos. En la base y no en
    memoria: vale con varias instancias del servidor y sobrevive a un reinicio.

    Sin colegio_id a propósito: las claves son de la plataforma (correo del admin), de un colegio
    (`colegio:<id>:<usuario>`) o de una IP, y se consultan todas igual. No guarda la clave intentada."""

    __tablename__ = "intento_fallido"
    __table_args__ = (Index("ix_intento_fallido_clave", "ambito", "clave", "momento"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ambito: Mapped[str] = mapped_column(String(20))  # "cuenta" o "ip"
    clave: Mapped[str] = mapped_column(String(300))
    momento: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora_utc, index=True)
