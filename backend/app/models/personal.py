from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.codigos import aleatorio
from app.db import Base, ConColegio, creado_en


class Rol(ConColegio, Base):
    __tablename__ = "rol"
    __table_args__ = (
        UniqueConstraint("colegio_id", "nombre"),
        # Destino de las llaves compuestas: un rol solo se puede usar dentro de su colegio.
        UniqueConstraint("colegio_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80))
    # El rol del director se crea con el colegio, tiene todos los permisos y no se borra.
    es_director: Mapped[bool] = mapped_column(default=False)
    # Cuaderno de control: solo ve y escribe lo de las secciones a su cargo (docente, tutor).
    solo_sus_secciones: Mapped[bool] = mapped_column(default=False, server_default="false")
    creado_en: Mapped[datetime] = creado_en()

    permisos: Mapped[list["PermisoRol"]] = relationship(
        back_populates="rol", cascade="all, delete-orphan", lazy="selectin",
        overlaps="colegio_id",
    )


class PermisoRol(ConColegio, Base):
    __tablename__ = "permiso_rol"
    __table_args__ = (
        ForeignKeyConstraint(
            ["colegio_id", "rol_id"], ["rol.colegio_id", "rol.id"], ondelete="CASCADE",
        ),
        CheckConstraint("nivel IN ('ver', 'editar')", name="nivel_valido"),
    )

    rol_id: Mapped[int] = mapped_column(primary_key=True)
    modulo: Mapped[str] = mapped_column(String(40), primary_key=True)
    nivel: Mapped[str] = mapped_column(String(10))

    rol: Mapped[Rol] = relationship(back_populates="permisos", overlaps="colegio_id")


class Usuario(ConColegio, Base):
    """Personal del colegio (director, docentes, portería, secretaría...)."""

    __tablename__ = "usuario"
    __table_args__ = (
        UniqueConstraint("colegio_id", "usuario"),
        UniqueConstraint("colegio_id", "tipo_documento", "numero_documento"),
        UniqueConstraint("colegio_id", "codigo"),
        UniqueConstraint("colegio_id", "id"),
        ForeignKeyConstraint(["colegio_id", "turno_id"], ["turno.colegio_id", "turno.id"], ondelete="RESTRICT"),
        CheckConstraint("tipo_documento IN ('DNI', 'CE')", name="tipo_documento_valido"),
        ForeignKeyConstraint(
            ["colegio_id", "rol_id"], ["rol.colegio_id", "rol.id"], ondelete="RESTRICT",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo_documento: Mapped[str] = mapped_column(String(4), default="DNI")
    numero_documento: Mapped[str] = mapped_column(String(12))
    usuario: Mapped[str] = mapped_column(String(60))
    nombres: Mapped[str] = mapped_column(String(120))
    apellidos: Mapped[str] = mapped_column(String(120))
    celular: Mapped[str | None] = mapped_column(String(9))
    correo: Mapped[str | None] = mapped_column(String(254))
    clave_hash: Mapped[str] = mapped_column(String(255))
    debe_cambiar_clave: Mapped[bool] = mapped_column(default=True)
    activo: Mapped[bool] = mapped_column(default=True)
    # Se incrementa para invalidar todos los tokens emitidos (cerrar sesiones).
    version_sesion: Mapped[int] = mapped_column(default=0)
    rol_id: Mapped[int]
    # Horario del personal: con turno se calcula tardanza y falta automática; sin turno, no.
    turno_id: Mapped[int | None]
    # Lo que lleva el QR de su carnet (TK1P:...). Con 32^8 combinaciones, el choque es
    # despreciable y lo atrapa la restricción única.
    codigo: Mapped[str] = mapped_column(String(12), default=aleatorio)
    creado_en: Mapped[datetime] = creado_en()

    rol: Mapped[Rol] = relationship(lazy="joined", overlaps="colegio_id")
