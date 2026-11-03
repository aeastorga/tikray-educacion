import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from app import asistencia as reglas_asistencia
from app.config import get_settings
from app.deps import colegio_del_host, usuario_actual, usuario_sesion
from app.routers import alumnos, asistencia, auth, colegio, estructura, importacion, personal, plataforma, roles


def crear_app() -> FastAPI:
    settings = get_settings()  # falla aquí si falta SECRET_KEY o DATABASE_URL

    @asynccontextmanager
    async def ciclo(_: FastAPI):
        parar = threading.Event()
        if settings.tareas_en_fondo:
            threading.Thread(target=reglas_asistencia.bucle_faltas, args=(parar,), daemon=True,
                             name="faltas").start()
        yield
        parar.set()

    app = FastAPI(title="Tikray Educación", lifespan=ciclo)

    # /api: todo lo del colegio del Host. Tres niveles de acceso, cada uno
    # aplicado al router entero para que ninguna ruta nueva se lo salte.
    api_publica = APIRouter(dependencies=[Depends(colegio_del_host)])
    api_publica.include_router(auth.publico)
    api_publica.include_router(colegio.publico)

    # Sesión válida aunque falte cambiar la clave temporal.
    api_sesion = APIRouter(dependencies=[Depends(usuario_sesion)])
    api_sesion.include_router(auth.sesion)

    # Sesión completa: token del mismo colegio del Host y clave ya cambiada.
    api_privada = APIRouter(dependencies=[Depends(usuario_actual)])
    for r in (colegio.privado, roles.router, personal.router, estructura.router, alumnos.router,
              importacion.router, asistencia.router):
        api_privada.include_router(r)

    for r in (api_publica, api_sesion, api_privada):
        app.include_router(r, prefix="/api")

    app.include_router(plataforma.publico)
    app.include_router(plataforma.router)

    carpeta = Path(settings.carpeta_archivos)
    carpeta.mkdir(parents=True, exist_ok=True)
    app.mount("/archivos", StaticFiles(directory=carpeta), name="archivos")

    @app.get("/salud", include_in_schema=False)
    def salud() -> dict:
        return {"ok": True}

    return app


app = crear_app()
