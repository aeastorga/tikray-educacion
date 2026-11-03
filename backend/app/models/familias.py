"""Familias: cuenta global del apoderado, invitaciones de un solo uso,
consentimiento (Ley 29733), passkeys, suscripciones push, entregas de avisos
por padre y registro de cambios de datos de contacto.

`cuenta_familia` y `passkey_familia` son globales (sin colegio_id): una persona
con hijos en dos colegios tiene una sola cuenta. Lo que cada colegio decide
(acceso, bloqueo, sesiones) vive en `apoderado`, que sí es del colegio.
"""

from datetime import datetime

from sqlalchemy import (CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, LargeBinary, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, ConColegio, creado_en


def _fk(columna: str, tabla: str, ondelete: str = "CASCADE") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["colegio_id", columna], [f"{tabla}.colegio_id", f"{tabla}.id"], ondelete=ondelete)


class CuentaFamilia(Base):
    """Una por documento. El PIN es de la persona, no de un colegio."""

    __tablename__ = "cuenta_familia"
    __table_args__ = (UniqueConstraint("tipo_documento", "numero_documento"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo_documento: Mapped[str] = mapped_column(String(4))
    numero_documento: Mapped[str] = mapped_column(String(15))
    pin_hash: Mapped[str] = mapped_column(String(255))
    # PIN fallidos seguidos (en cualquier colegio). Al llegar al límite se bloquea el PIN
    # por un día; la huella sigue sirviendo. En la base para que valga entre servidores y reinicios.
    pin_fallidos: Mapped[int] = mapped_column(default=0, server_default="0")
    pin_bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = creado_en()


class PasskeyFamilia(Base):
    """Huella o rostro del celular (WebAuthn). Atada al dominio donde se registró (`rp_id`)."""

    __tablename__ = "passkey_familia"

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuenta_familia.id", ondelete="CASCADE"), index=True)
    credencial_id: Mapped[str] = mapped_column(String(400), unique=True)  # base64url
    clave_publica: Mapped[bytes] = mapped_column(LargeBinary)
    contador: Mapped[int] = mapped_column(default=0)
    rp_id: Mapped[str] = mapped_column(String(253))
    creado_en: Mapped[datetime] = creado_en()
    usado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RetoUsado(ConColegio, Base):
    """Retos de huella ya presentados: cada uno sirve una sola vez. Se borran al vencer."""

    __tablename__ = "reto_usado"

    reto: Mapped[str] = mapped_column(String(100), primary_key=True)  # el challenge en base64url
    vence_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ConfigFamilias(Base):
    __tablename__ = "config_familias"
    __table_args__ = (CheckConstraint("activacion IN ('automatica', 'aprobacion')", name="activacion_valida"),)

    colegio_id: Mapped[int] = mapped_column(ForeignKey("colegio.id", ondelete="CASCADE"), primary_key=True)
    # automatica: el padre entra apenas activa. aprobacion: queda pendiente hasta que el colegio aprueba.
    activacion: Mapped[str] = mapped_column(String(12), default="automatica")


class InvitacionFamilia(ConColegio, Base):
    """Enlace personal de un solo uso. Solo se guarda el hash del token."""

    __tablename__ = "invitacion_familia"
    __table_args__ = (
        _fk("apoderado_id", "apoderado"),
        _fk("creado_por_id", "usuario", "SET NULL"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    apoderado_id: Mapped[int]
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    celular: Mapped[str | None] = mapped_column(String(9))  # a dónde se envió
    # El colegio lo marca cuando el padre olvidó su PIN: al activar crea uno nuevo.
    nuevo_pin: Mapped[bool] = mapped_column(default=False)
    creado_por_id: Mapped[int | None]
    creado_en: Mapped[datetime] = creado_en()
    vence_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    intentos: Mapped[int] = mapped_column(default=0)
    usada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anulada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_anulacion: Mapped[str | None] = mapped_column(String(80))


class ConsentimientoApoderado(ConColegio, Base):
    """Ley 29733: el apoderado acepta el tratamiento de sus datos y los de su hijo.
    El colegio es el titular del banco de datos; Tikray Labs, el encargado."""

    __tablename__ = "consentimiento_apoderado"
    __table_args__ = (_fk("apoderado_id", "apoderado"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    apoderado_id: Mapped[int]
    version: Mapped[str] = mapped_column(String(20))
    aceptado_en: Mapped[datetime] = creado_en()
    ip: Mapped[str | None] = mapped_column(String(45))


class SuscripcionPush(ConColegio, Base):
    """Un navegador de un padre que acepta notificaciones. `colegio_id` es el colegio por cuya
    dirección se suscribió (el service worker es de ese origen)."""

    __tablename__ = "suscripcion_push"

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuenta_familia.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    creado_en: Mapped[datetime] = creado_en()
    ultimo_envio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EntregaAviso(ConColegio, Base):
    """Qué pasó con un aviso para cada apoderado: el "estado de avisos por padre"."""

    __tablename__ = "entrega_aviso"
    __table_args__ = (
        _fk("aviso_id", "cola_aviso"),
        _fk("apoderado_id", "apoderado"),
        UniqueConstraint("colegio_id", "aviso_id", "apoderado_id"),
        CheckConstraint("estado IN ('enviado', 'sin_notificaciones', 'error')", name="estado_valido"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    aviso_id: Mapped[int]
    apoderado_id: Mapped[int]
    estado: Mapped[str] = mapped_column(String(20))
    dispositivos: Mapped[int] = mapped_column(default=0)
    titulo: Mapped[str] = mapped_column(String(120))
    cuerpo: Mapped[str] = mapped_column(String(300))
    detalle: Mapped[str | None] = mapped_column(String(200))
    creado_en: Mapped[datetime] = creado_en()


class CambioApoderado(ConColegio, Base):
    """Quién cambió un dato del apoderado, cuándo y desde dónde. `familia`: lo provocó el propio
    padre (p. ej. un PIN nuevo creado con el enlace de otro colegio deja su acceso pendiente aquí)."""

    __tablename__ = "cambio_apoderado"
    __table_args__ = (
        _fk("apoderado_id", "apoderado"),
        _fk("cambiado_por_id", "usuario", "SET NULL"),
        CheckConstraint("origen IN ('excel', 'panel', 'familia')", name="origen_valido"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    apoderado_id: Mapped[int]
    campo: Mapped[str] = mapped_column(String(20))
    antes: Mapped[str | None] = mapped_column(String(254))
    despues: Mapped[str | None] = mapped_column(String(254))
    origen: Mapped[str] = mapped_column(String(10))
    cambiado_por_id: Mapped[int | None]
    creado_en: Mapped[datetime] = creado_en()
