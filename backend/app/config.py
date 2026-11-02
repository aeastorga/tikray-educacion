from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Sin valor por defecto: si falta, la app no arranca (lección de SGI).
    secret_key: str = Field(min_length=32)
    database_url: str
    dominio_base: str = "localhost"
    carpeta_archivos: str = "archivos"
    # Redes (CIDR, separadas por comas) de los proxies propios, por ejemplo el
    # balanceador de Render. Solo de ellas se acepta X-Forwarded-For.
    proxies_confianza: str = ""

    token_colegio_minutos: int = 60 * 12
    token_plataforma_minutos: int = 60 * 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
