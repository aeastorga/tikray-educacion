from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, creado_en


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
