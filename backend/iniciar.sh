#!/bin/sh
# Arranque en Render (y en cualquier contenedor): primero las migraciones, después el servidor.
# Si una migración falla, el servidor no arranca y Render mantiene la versión anterior.
set -e
alembic upgrade head
# Sin --proxy-headers: la IP real la lee la app desde X-Forwarded-For, solo si viene de
# PROXIES_CONFIANZA (app/proteccion.py). Así nadie se inventa una IP.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --no-proxy-headers
