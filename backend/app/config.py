from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Sin valor por defecto: si falta, la app no arranca (lección de SGI).
    secret_key: str = Field(min_length=32)
    database_url: str
    dominio_base: str = "localhost"
    carpeta_archivos: str = "archivos"
    # Archivos que no son públicos (adjuntos del cuaderno): se sirven solo con sesión.
    carpeta_privada: str = "archivos-privados"
    # Redes (CIDR, separadas por comas) de los proxies propios, por ejemplo el
    # balanceador de Render. Solo de ellas se acepta X-Forwarded-For.
    proxies_confianza: str = ""
    # Carpeta con el frontend compilado (vite build). Si está, el mismo servidor lo sirve
    # (Render: un solo servicio). En local se deja vacía y se usa Vite.
    carpeta_frontend: str = ""

    # Faltas automáticas cada minuto dentro del servidor. En pruebas se apaga.
    tareas_en_fondo: bool = True
    # Web Push (VAPID). Sin ellas no se envían avisos: quedan en la cola hasta configurarlas.
    # Se generan con: python -m app.cli claves-push
    vapid_clave_privada: str = ""
    vapid_clave_publica: str = ""
    vapid_contacto: str = "mailto:soporte@tikraylabs.pe"

    @field_validator("database_url")
    @classmethod
    def _driver(cls, url: str) -> str:
        """Render (y otros) dan `postgres://` o `postgresql://`; SQLAlchemy necesita el driver psycopg 3."""
        for prefijo in ("postgres://", "postgresql://"):
            if url.startswith(prefijo):
                return "postgresql+psycopg://" + url[len(prefijo):]
        return url

    token_colegio_minutos: int = 60 * 12
    token_plataforma_minutos: int = 60 * 2
    # El padre entra con PIN o huella; una sesión larga es lo que espera de una app del celular.
    token_familia_minutos: int = 60 * 24 * 90


@lru_cache
def get_settings() -> Settings:
    return Settings()
