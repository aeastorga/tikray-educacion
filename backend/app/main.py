import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import asistencia as reglas_asistencia
from app import avisos, pensiones
from app.config import get_settings
from app.deps import colegio_del_host, familia_sesion, usuario_actual, usuario_sesion
from app.proteccion import ip_cliente
from app.routers import (alumnos, asistencia, auth, caja, colegio, configuracion, cuaderno, estructura, familia,
                         familia_cuaderno, familia_pagos, familias, importacion, panel, pensiones as rutas_pensiones,
                         personal, plataforma, reunion, roles)


def crear_app() -> FastAPI:
    settings = get_settings()  # falla aquí si falta SECRET_KEY o DATABASE_URL

    @asynccontextmanager
    async def ciclo(_: FastAPI):
        parar = threading.Event()
        if settings.tareas_en_fondo:
            threading.Thread(target=reglas_asistencia.bucle_faltas, args=(parar,), daemon=True,
                             name="faltas").start()
            threading.Thread(target=avisos.bucle_avisos, args=(parar,), daemon=True, name="avisos").start()
            threading.Thread(target=pensiones.bucle_cobros, args=(parar,), daemon=True, name="cobros").start()
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
    api_familia.include_router(familia_pagos.privado)

    # Sesión completa: token del mismo colegio del Host y clave ya cambiada.
    api_privada = APIRouter(dependencies=[Depends(usuario_actual)])
    for r in (colegio.privado, roles.router, personal.router, estructura.router, alumnos.router,
              importacion.router, asistencia.router, familias.router, cuaderno.router, panel.router,
              reunion.router, configuracion.router, rutas_pensiones.router, caja.router):
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

    @app.get("/salud/ip", include_in_schema=False)
    def salud_ip(request: Request) -> dict:
        """Para revisar PROXIES_CONFIANZA tras un proxy: lo que llega y la IP que el sistema usa
        para los límites de intentos. Solo muestra datos de la propia petición."""
        return {"ip_cliente": ip_cliente(request), "directa": request.client.host if request.client else None,
                "x_forwarded_for": request.headers.get("x-forwarded-for")}

    if settings.carpeta_frontend:
        servir_frontend(app, Path(settings.carpeta_frontend))

    return app


# Rutas del backend: nunca caen en el index.html de la app.
_DEL_BACKEND = ("api", "plataforma", "archivos", "salud", "docs", "openapi.json", "redoc")


def servir_frontend(app: FastAPI, carpeta: Path) -> None:
    """La PWA compilada desde el mismo servidor: los archivos tal cual y, para cualquier otra ruta
    (/panel, /familia/activar…), el index.html. index.html y el service worker sin caché, para que
    un despliegue nuevo llegue a los celulares; lo de /assets lleva hash en el nombre y se cachea."""
    carpeta = carpeta.resolve()
    indice = carpeta / "index.html"
    if not indice.is_file():
        raise RuntimeError(f"CARPETA_FRONTEND={carpeta} no tiene index.html: compila el frontend (npm run build)")
    sin_cache = {"Cache-Control": "no-cache"}

    @app.get("/{ruta:path}", include_in_schema=False)
    def frontend(ruta: str):
        if ruta.split("/", 1)[0] in _DEL_BACKEND:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontrado")
        archivo = (carpeta / ruta).resolve()
        if ruta and archivo.is_file() and archivo.is_relative_to(carpeta):
            if ruta.startswith("assets/"):
                return FileResponse(archivo, headers={"Cache-Control": "public, max-age=31536000, immutable"})
            return FileResponse(archivo, headers=sin_cache)
        if "." in ruta.rsplit("/", 1)[-1]:  # un archivo que no existe: 404, no la app
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontrado")
        return FileResponse(indice, headers=sin_cache)


app = crear_app()
