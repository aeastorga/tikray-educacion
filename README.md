# Tikray Educación

Plataforma multi-colegio de Tikray Labs: asistencia de alumnos y personal, avisos a padres, cuaderno de control digital y gestión del colegio.

Ver `CLAUDE.md` para las decisiones de diseño y el orden de construcción del MVP.

## En local

Requisitos: Python 3.12, Node 22, PostgreSQL 16.

```bash
# Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # y completa SECRET_KEY y DATABASE_URL
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli crear-admin tu@correo.pe "Tu nombre"
.venv/bin/uvicorn app.main:app --reload --port 8000

# Frontend (otra terminal)
cd frontend && npm install && npm run dev
```

- Panel de Tikray Labs: http://plataforma.localhost:5173 (ahí se crean los colegios y su director).
- Cada colegio: http://<subdominio>.localhost:5173

## Pruebas

Corren contra PostgreSQL real (borran y recrean el esquema de la base de pruebas):

```bash
cd backend
TEST_DATABASE_URL=postgresql+psycopg://usuario:clave@localhost/tikray_test .venv/bin/pytest
```

## Cómo se aísla cada colegio

- El colegio sale del `Host` (subdominio o dominio propio). Las rutas privadas exigen que el `colegio_id` del token sea el de ese Host; si no, 403.
- `colegio_id` es obligatorio en toda tabla, con llave foránea a `colegio`. Las relaciones internas usan llaves compuestas `(colegio_id, id)`, así la base rechaza, por ejemplo, un usuario con un rol de otro colegio.
- El personal de Tikray Labs usa otro token (firma y audiencia distintas) y solo entra a `/plataforma`.
- `tests/test_aislamiento.py` recorre todas las rutas para comprobar esto.
