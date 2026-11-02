from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import DateTime, ForeignKey, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, declared_attr, mapped_column, sessionmaker

from app.config import get_settings

NOMBRES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def ahora_utc() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NOMBRES)


class ConColegio:
    """Mixin para toda tabla de datos de un colegio.

    `colegio_id` es obligatorio y tiene llave foránea real a `colegio`.
    Se llena desde el token en el servidor, nunca desde el navegador.
    """

    @declared_attr
    def colegio_id(cls) -> Mapped[int]:
        return mapped_column(ForeignKey("colegio.id", ondelete="RESTRICT"), index=True)


def creado_en() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=ahora_utc)


@lru_cache
def get_engine():
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with get_sessionmaker()() as db:
        yield db
