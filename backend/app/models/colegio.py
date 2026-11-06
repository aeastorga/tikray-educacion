from datetime import date, datetime, time

from sqlalchemy import CheckConstraint, String, Time
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, creado_en

COLOR = r"^#[0-9a-fA-F]{6}$"
ESTADOS = ("prueba", "activo", "suspendido")
GESTIONES = ("particular", "estatal")
# Módulos que se contratan aparte; el resto (configuración, roles, personal, padrón) viene siempre.
CONTRATABLES = ("asistencia", "cuaderno", "familias", "reuniones", "pensiones", "caja")
# Avisos a los padres que el director puede apagar uno por uno.
TIPOS_AVISO = ("ingreso", "tardanza", "falta", "salida", "cuaderno", "cobro")


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
        CheckConstraint("tipo_gestion IN ('particular', 'estatal')", name="tipo_gestion_valido"),
        CheckConstraint("codigo_modular ~ '^[0-9]{7}$'", name="codigo_modular_valido"),
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

    # --- Perfil: lo edita el director o Tikray Labs ---
    # Particular o estatal. Pensiones y caja están para los dos; el que no los usa los apaga.
    tipo_gestion: Mapped[str] = mapped_column(String(10), default="particular", server_default="particular")
    ugel: Mapped[str | None] = mapped_column(String(120))
    codigo_modular: Mapped[str | None] = mapped_column(String(7))
    direccion: Mapped[str | None] = mapped_column(String(250))
    telefono: Mapped[str | None] = mapped_column(String(20))
    correo_contacto: Mapped[str | None] = mapped_column(String(254))

    # --- Módulos: Tikray Labs marca los contratados; el director apaga los que no usa ---
    modulos_contratados: Mapped[list[str]] = mapped_column(
        JSONB, default=lambda: list(CONTRATABLES), server_default='["asistencia", "cuaderno", "familias", "reuniones", "pensiones", "caja"]')
    modulos_apagados: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")

    # --- Avisos a los padres ---
    avisos_tipos: Mapped[dict] = mapped_column(
        JSONB, default=lambda: {t: True for t in TIPOS_AVISO},
        server_default='{"ingreso": true, "tardanza": true, "falta": true, "salida": true, "cuaderno": true, '
                       '"cobro": true}')
    # Horario sin molestar (hora de Lima): los avisos del cuaderno esperan a que termine.
    silencio_desde: Mapped[time] = mapped_column(Time, default=time(21, 0), server_default="21:00")
    silencio_hasta: Mapped[time] = mapped_column(Time, default=time(6, 0), server_default="06:00")

    def modulo_activo(self, modulo: str) -> bool:
        """Los contratables solo si están contratados y el director no los apagó; el resto, siempre."""
        if modulo not in CONTRATABLES:
            return True
        return modulo in (self.modulos_contratados or []) and modulo not in (self.modulos_apagados or [])

    def disponible(self, hoy: date) -> bool:
        if self.estado == "suspendido":
            return False
        return self.vence_en is None or hoy <= self.vence_en
