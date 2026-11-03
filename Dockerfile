# Un solo servicio para Render: el backend (FastAPI) sirve también la PWA compilada.

# 1) Frontend: vite build
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2) Backend
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    CARPETA_FRONTEND=/app/frontend
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY backend/iniciar.sh ./
COPY --from=frontend /frontend/dist /app/frontend
RUN useradd --create-home tikray && mkdir -p archivos archivos-privados && chown -R tikray archivos archivos-privados
USER tikray
EXPOSE 8000
CMD ["./iniciar.sh"]
