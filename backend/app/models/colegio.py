from datetime import date, datetime

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, creado_en

COLOR = r"^#[0-9a-fA-F]{6}$"
ESTADOS = ("prueba", "activo", "suspendido")


class Colegio(Base):
    """Raíz del multi-colegio: es la única tabla de datos sin `colegio_id`."""

    __tablename__ = "colegio"
    __table_args__ = (
        CheckConstraint("subdominio ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'", name="subdominio_valido"),
        CheckConstraint(f"color_primario ~ '{COLOR}'", name="color_primario_valido"),
        CheckConstraint(f"color_secundario ~ '{COLOR}'", name="color_secundario_valido"),
        CheckConstraint("estado IN ('prueba', 'activo', 'suspendido')", name="estado_valido"),
        # Una prueba siempre tiene fin.
        CheckConstraint("estado <> 'prueba' OR vence_en IS NOT NULL", name="prueba_con_vencimiento"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    subdominio: Mapped[str] = mapped_column(String(63), unique=True)
    dominio_propio: Mapped[str | None] = mapped_column(String(253), unique=True)
    # Clave del archivo en el almacenamiento (no la URL, que depende del proveedor).
    logo_clave: Mapped[str | None] = mapped_column(String(300))
    color_primario: Mapped[str] = mapped_column(String(7), default="#1F4E79")
    color_secundario: Mapped[str] = mapped_column(String(7), default="#F2A900")
    # Menú lateral del panel: oscuro (por defecto) o claro. Lo elige el director.
    menu_claro: Mapped[bool] = mapped_column(default=False, server_default="false")
    estado: Mapped[str] = mapped_column(String(12), default="activo")
    # Último día con acceso (fecha de Lima). Vacío = sin vencimiento.
    vence_en: Mapped[date | None]
    # Colegio de demostración con datos ficticios: el único que se puede borrar y volver a crear.
    es_demo: Mapped[bool] = mapped_column(default=False, server_default="false")
    creado_en: Mapped[datetime] = creado_en()

    def disponible(self, hoy: date) -> bool:
        if self.estado == "suspendido":
            return False
        return self.vence_en is None or hoy <= self.vence_en
