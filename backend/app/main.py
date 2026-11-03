import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from app import asistencia as reglas_asistencia
from app import avisos
from app.config import get_settings
from app.deps import colegio_del_host, familia_sesion, usuario_actual, usuario_sesion
from app.routers import (alumnos, asistencia, auth, colegio, cuaderno, estructura, familia, familia_cuaderno, familias,
                         importacion, panel, personal, plataforma, reunion, roles)


def crear_app() -> FastAPI:
    settings = get_settings()  # falla aquí si falta SECRET_KEY o DATABASE_URL

    @asynccontextmanager
    async def ciclo(_: FastAPI):
        parar = threading.Event()
        if settings.tareas_en_fondo:
            threading.Thread(target=reglas_asistencia.bucle_faltas, args=(parar,), daemon=True,
                             name="faltas").start()
            threading.Thread(target=avisos.bucle_avisos, args=(parar,), daemon=True, name="avisos").start()
        yield
        parar.set()

    app = FastAPI(title="Tikray Educación", lifespan=ciclo)

    # /api: todo lo del colegio del Host. Tres niveles de acceso, cada uno
    # aplicado al router entero para que ninguna ruta nueva se lo salte.
    api_publica = APIRouter(dependencies=[Depends(colegio_del_host)])
    api_publica.include_router(auth.publico)
    api_publica.include_router(colegio.publico)
    api_publica.include_router(familia.publico)
    api_publica.include_router(reunion.publico)

    # Sesión válida aunque falte cambiar la clave temporal.
    api_sesion = APIRouter(dependencies=[Depends(usuario_sesion)])
    api_sesion.include_router(auth.sesion)

    # Padres y apoderados: su propio tipo de token, del mismo colegio del Host.
    api_familia = APIRouter(dependencies=[Depends(familia_sesion)])
    api_familia.include_router(familia.privado)
    api_familia.include_router(familia_cuaderno.privado)

    # Sesión completa: token del mismo colegio del Host y clave ya cambiada.
    api_privada = APIRouter(dependencies=[Depends(usuario_actual)])
    for r in (colegio.privado, roles.router, personal.router, estructura.router, alumnos.router,
              importacion.router, asistencia.router, familias.router, cuaderno.router, panel.router,
              reunion.router):
        api_privada.include_router(r)

    for r in (api_publica, api_sesion, api_familia, api_privada):
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
