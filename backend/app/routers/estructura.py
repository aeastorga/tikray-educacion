"""Configuración del padrón: año escolar, niveles, grados, turnos, secciones
y calendario de días no lectivos. Todo lo define el director por colegio."""

from datetime import date, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.comun import guardar, obtener
from app.configuracion import anotar
from app.db import get_db
from app.deps import Sesion, requerir_permiso
from app.models import AnioEscolar, DiaNoLectivo, Grado, Matricula, Nivel, Seccion, Turno

router = APIRouter(prefix="/padron", tags=["padron"])
ver = requerir_permiso("padron")
editar = requerir_permiso("padron", "editar")


def anio_activo(db: Session, colegio_id: int) -> AnioEscolar:
    anio = db.scalar(select(AnioEscolar).where(AnioEscolar.colegio_id == colegio_id, AnioEscolar.activo))
    if anio is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Primero crea y activa el año escolar")
    return anio


def anio_o_activo(db: Session, colegio_id: int, anio_id: int | None) -> AnioEscolar:
    if anio_id is None:
        return anio_activo(db, colegio_id)
    return obtener(db, AnioEscolar, colegio_id, anio_id, "Año escolar")


# --- Año escolar -------------------------------------------------------------

class DatosAnio(BaseModel):
    anio: int = Field(ge=2000, le=2100)
    inicio: date
    fin: date
    dias_semana: str = Field(default="12345", pattern=r"^1?2?3?4?5?6?7?$", min_length=1)

    @model_validator(mode="after")
    def _fechas(self):
        if self.fin <= self.inicio:
            raise ValueError("La fecha de fin debe ser posterior a la de inicio")
        return self


class AnioOut(DatosAnio):
    id: int
    activo: bool


def _anio(a: AnioEscolar) -> AnioOut:
    return AnioOut(id=a.id, anio=a.anio, inicio=a.inicio, fin=a.fin, dias_semana=a.dias_semana, activo=a.activo)


@router.get("/anios")
def listar_anios(s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> list[AnioOut]:
    filas = db.scalars(select(AnioEscolar).where(AnioEscolar.colegio_id == s.colegio.id)
                       .order_by(AnioEscolar.anio.desc()))
    return [_anio(a) for a in filas]


@router.post("/anios", status_code=201)
def crear_anio(datos: DatosAnio, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> AnioOut:
    hay_activo = db.scalar(select(AnioEscolar.id).where(AnioEscolar.colegio_id == s.colegio.id,
                                                        AnioEscolar.activo))
    a = AnioEscolar(colegio_id=s.colegio.id, activo=hay_activo is None, **datos.model_dump())
    db.add(a)
    anotar(db, s, "crear", "padron", "anio", a, f"Año escolar {a.anio}", "Ese año escolar ya existe")
    return _anio(a)


@router.put("/anios/{anio_id}")
def editar_anio(anio_id: int, datos: DatosAnio, s: Sesion = Depends(editar),
                db: Session = Depends(get_db)) -> AnioOut:
    a = obtener(db, AnioEscolar, s.colegio.id, anio_id, "Año escolar")
    a.anio, a.inicio, a.fin, a.dias_semana = datos.anio, datos.inicio, datos.fin, datos.dias_semana
    anotar(db, s, "editar", "padron", "anio", a, f"Año escolar {a.anio}: {a.inicio:%d/%m} al {a.fin:%d/%m}",
           "Ese año escolar ya existe")
    return _anio(a)


@router.post("/anios/{anio_id}/activar")
def activar_anio(anio_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> AnioOut:
    a = obtener(db, AnioEscolar, s.colegio.id, anio_id, "Año escolar")
    db.execute(update(AnioEscolar).where(AnioEscolar.colegio_id == s.colegio.id, AnioEscolar.id != a.id)
               .values(activo=False))
    a.activo = True
    anotar(db, s, "editar", "padron", "anio", a, f"Activó el año escolar {a.anio}")
    return _anio(a)


# --- Niveles y grados ---------------------------------------------------------

class DatosNivel(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    orden: int = 0


class DatosGrado(DatosNivel):
    nivel_id: int


@router.get("/estructura")
def estructura(s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    """Niveles con sus grados, y turnos: lo que se necesita para armar secciones."""
    cid = s.colegio.id
    niveles = db.scalars(select(Nivel).where(Nivel.colegio_id == cid).order_by(Nivel.orden, Nivel.nombre)).all()
    grados = db.scalars(select(Grado).where(Grado.colegio_id == cid).order_by(Grado.orden, Grado.nombre)).all()
    turnos = db.scalars(select(Turno).where(Turno.colegio_id == cid).order_by(Turno.hora_entrada)).all()
    return {
        "niveles": [
            {"id": n.id, "nombre": n.nombre, "orden": n.orden,
             "grados": [{"id": g.id, "nombre": g.nombre, "orden": g.orden} for g in grados if g.nivel_id == n.id]}
            for n in niveles
        ],
        "turnos": [_turno(t) for t in turnos],
    }


@router.post("/niveles", status_code=201)
def crear_nivel(datos: DatosNivel, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    n = Nivel(colegio_id=s.colegio.id, nombre=datos.nombre.strip(), orden=datos.orden)
    db.add(n)
    anotar(db, s, "crear", "padron", "nivel", n, f"Nivel {n.nombre}", "Ya existe un nivel con ese nombre")
    return {"id": n.id, "nombre": n.nombre, "orden": n.orden}


@router.put("/niveles/{nivel_id}")
def editar_nivel(nivel_id: int, datos: DatosNivel, s: Sesion = Depends(editar),
                 db: Session = Depends(get_db)) -> dict:
    n = obtener(db, Nivel, s.colegio.id, nivel_id, "Nivel")
    n.nombre, n.orden = datos.nombre.strip(), datos.orden
    anotar(db, s, "editar", "padron", "nivel", n, f"Nivel {n.nombre}", "Ya existe un nivel con ese nombre")
    return {"id": n.id, "nombre": n.nombre, "orden": n.orden}


@router.delete("/niveles/{nivel_id}", status_code=204)
def borrar_nivel(nivel_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> None:
    n = obtener(db, Nivel, s.colegio.id, nivel_id, "Nivel")
    db.delete(n)
    anotar(db, s, "anular", "padron", "nivel", nivel_id, f"Borró el nivel {n.nombre}",
           en_uso="El nivel tiene grados; bórralos primero")


@router.post("/grados", status_code=201)
def crear_grado(datos: DatosGrado, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    obtener(db, Nivel, s.colegio.id, datos.nivel_id, "Nivel")
    g = Grado(colegio_id=s.colegio.id, nivel_id=datos.nivel_id, nombre=datos.nombre.strip(), orden=datos.orden)
    db.add(g)
    anotar(db, s, "crear", "padron", "grado", g, f"Grado {g.nombre}", "Ese grado ya existe en el nivel")
    return {"id": g.id, "nivel_id": g.nivel_id, "nombre": g.nombre, "orden": g.orden}


@router.put("/grados/{grado_id}")
def editar_grado(grado_id: int, datos: DatosGrado, s: Sesion = Depends(editar),
                 db: Session = Depends(get_db)) -> dict:
    g = obtener(db, Grado, s.colegio.id, grado_id, "Grado")
    obtener(db, Nivel, s.colegio.id, datos.nivel_id, "Nivel")
    g.nivel_id, g.nombre, g.orden = datos.nivel_id, datos.nombre.strip(), datos.orden
    anotar(db, s, "editar", "padron", "grado", g, f"Grado {g.nombre}", "Ese grado ya existe en el nivel")
    return {"id": g.id, "nivel_id": g.nivel_id, "nombre": g.nombre, "orden": g.orden}


@router.delete("/grados/{grado_id}", status_code=204)
def borrar_grado(grado_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> None:
    g = obtener(db, Grado, s.colegio.id, grado_id, "Grado")
    db.delete(g)
    anotar(db, s, "anular", "padron", "grado", grado_id, f"Borró el grado {g.nombre}",
           en_uso="El grado tiene secciones; bórralas primero")


# --- Turnos -------------------------------------------------------------------

class DatosTurno(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    hora_entrada: time
    tolerancia_minutos: int = Field(default=0, ge=0, le=120)
    hora_salida: time

    @model_validator(mode="after")
    def _horas(self):
        if self.hora_salida <= self.hora_entrada:
            raise ValueError("La hora de salida debe ser posterior a la de entrada")
        return self


def _turno(t: Turno) -> dict:
    return {"id": t.id, "nombre": t.nombre, "hora_entrada": t.hora_entrada.strftime("%H:%M"),
            "tolerancia_minutos": t.tolerancia_minutos, "hora_salida": t.hora_salida.strftime("%H:%M")}


def _texto_turno(t: Turno) -> str:
    return (f"Turno {t.nombre}: entrada {t.hora_entrada:%H:%M} (tolerancia {t.tolerancia_minutos} min), "
            f"salida {t.hora_salida:%H:%M}")


@router.post("/turnos", status_code=201)
def crear_turno(datos: DatosTurno, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    t = Turno(colegio_id=s.colegio.id, **{**datos.model_dump(), "nombre": datos.nombre.strip()})
    db.add(t)
    anotar(db, s, "crear", "padron", "turno", t, _texto_turno(t), "Ya existe un turno con ese nombre")
    return _turno(t)


@router.put("/turnos/{turno_id}")
def editar_turno(turno_id: int, datos: DatosTurno, s: Sesion = Depends(editar),
                 db: Session = Depends(get_db)) -> dict:
    t = obtener(db, Turno, s.colegio.id, turno_id, "Turno")
    for campo, valor in datos.model_dump().items():
        setattr(t, campo, valor.strip() if campo == "nombre" else valor)
    anotar(db, s, "editar", "padron", "turno", t, _texto_turno(t), "Ya existe un turno con ese nombre")
    return _turno(t)


@router.delete("/turnos/{turno_id}", status_code=204)
def borrar_turno(turno_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> None:
    t = obtener(db, Turno, s.colegio.id, turno_id, "Turno")
    db.delete(t)
    anotar(db, s, "anular", "padron", "turno", turno_id, f"Borró el turno {t.nombre}",
           en_uso="Hay secciones en este turno")


# --- Secciones ----------------------------------------------------------------

class DatosSeccion(BaseModel):
    grado_id: int
    turno_id: int
    nombre: str = Field(min_length=1, max_length=20)


@router.get("/secciones")
def listar_secciones(anio_id: int | None = None, s: Sesion = Depends(ver),
                     db: Session = Depends(get_db)) -> list[dict]:
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    alumnos = (select(Matricula.seccion_id, func.count().label("n"))
               .where(Matricula.colegio_id == cid, Matricula.anio_id == anio.id)
               .group_by(Matricula.seccion_id).subquery())
    filas = db.execute(
        select(Seccion, Grado, Nivel, Turno, func.coalesce(alumnos.c.n, 0))
        .join(Grado, (Grado.colegio_id == Seccion.colegio_id) & (Grado.id == Seccion.grado_id))
        .join(Nivel, (Nivel.colegio_id == Grado.colegio_id) & (Nivel.id == Grado.nivel_id))
        .join(Turno, (Turno.colegio_id == Seccion.colegio_id) & (Turno.id == Seccion.turno_id))
        .outerjoin(alumnos, alumnos.c.seccion_id == Seccion.id)
        .where(Seccion.colegio_id == cid, Seccion.anio_id == anio.id)
        .order_by(Nivel.orden, Grado.orden, Grado.nombre, Seccion.nombre)
    ).all()
    return [
        {"id": sec.id, "anio_id": sec.anio_id, "nombre": sec.nombre, "grado_id": g.id, "grado": g.nombre,
         "nivel_id": n.id, "nivel": n.nombre, "turno_id": t.id, "turno": t.nombre, "alumnos": total,
         "etiqueta": f"{n.nombre} · {g.nombre} {sec.nombre}"}
        for sec, g, n, t, total in filas
    ]


@router.post("/secciones", status_code=201)
def crear_seccion(datos: DatosSeccion, anio_id: int | None = None, s: Sesion = Depends(editar),
                  db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    obtener(db, Grado, cid, datos.grado_id, "Grado")
    obtener(db, Turno, cid, datos.turno_id, "Turno")
    sec = Seccion(colegio_id=cid, anio_id=anio.id, grado_id=datos.grado_id, turno_id=datos.turno_id,
                  nombre=datos.nombre.strip().upper())
    db.add(sec)
    anotar(db, s, "crear", "padron", "seccion", sec, f"Sección {sec.nombre}", "Esa sección ya existe en el grado")
    return {"id": sec.id, "anio_id": sec.anio_id, "grado_id": sec.grado_id, "turno_id": sec.turno_id,
            "nombre": sec.nombre}


@router.put("/secciones/{seccion_id}")
def editar_seccion(seccion_id: int, datos: DatosSeccion, s: Sesion = Depends(editar),
                   db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    sec = obtener(db, Seccion, cid, seccion_id, "Sección")
    obtener(db, Grado, cid, datos.grado_id, "Grado")
    obtener(db, Turno, cid, datos.turno_id, "Turno")
    sec.grado_id, sec.turno_id, sec.nombre = datos.grado_id, datos.turno_id, datos.nombre.strip().upper()
    anotar(db, s, "editar", "padron", "seccion", sec, f"Sección {sec.nombre}", "Esa sección ya existe en el grado")
    return {"id": sec.id, "anio_id": sec.anio_id, "grado_id": sec.grado_id, "turno_id": sec.turno_id,
            "nombre": sec.nombre}


@router.delete("/secciones/{seccion_id}", status_code=204)
def borrar_seccion(seccion_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> None:
    sec = obtener(db, Seccion, s.colegio.id, seccion_id, "Sección")
    db.delete(sec)
    anotar(db, s, "anular", "padron", "seccion", seccion_id, f"Borró la sección {sec.nombre}",
           en_uso="La sección tiene alumnos matriculados")


# --- Días no lectivos ---------------------------------------------------------

class DatosDiaNoLectivo(BaseModel):
    desde: date
    hasta: date | None = None  # para vacaciones o semanas completas
    motivo: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def _rango(self):
        if self.hasta is not None and self.hasta < self.desde:
            raise ValueError("'hasta' no puede ser anterior a 'desde'")
        if self.hasta is not None and (self.hasta - self.desde).days > 120:
            raise ValueError("El rango no puede pasar de 120 días")
        return self


@router.get("/dias-no-lectivos")
def listar_dias(anio_id: int | None = None, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> list[dict]:
    anio = anio_o_activo(db, s.colegio.id, anio_id)
    filas = db.scalars(select(DiaNoLectivo).where(DiaNoLectivo.colegio_id == s.colegio.id,
                                                  DiaNoLectivo.anio_id == anio.id).order_by(DiaNoLectivo.fecha))
    return [{"id": d.id, "fecha": d.fecha.isoformat(), "motivo": d.motivo} for d in filas]


@router.post("/dias-no-lectivos", status_code=201)
def agregar_dias(datos: DatosDiaNoLectivo, anio_id: int | None = None, s: Sesion = Depends(editar),
                 db: Session = Depends(get_db)) -> dict:
    """Agrega un día o un rango. Solo se guardan los días de clase de la semana del año."""
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    hasta = datos.hasta or datos.desde
    if datos.desde < anio.inicio or hasta > anio.fin:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Las fechas están fuera del año escolar")
    existentes = set(db.scalars(select(DiaNoLectivo.fecha).where(
        DiaNoLectivo.colegio_id == cid, DiaNoLectivo.fecha.between(datos.desde, hasta))))
    agregados = 0
    dia = datos.desde
    while dia <= hasta:
        if str(dia.isoweekday()) in anio.dias_semana and dia not in existentes:
            db.add(DiaNoLectivo(colegio_id=cid, anio_id=anio.id, fecha=dia, motivo=datos.motivo.strip()))
            agregados += 1
        dia += timedelta(days=1)
    rango = f"{datos.desde:%d/%m}" + (f" al {hasta:%d/%m}" if hasta != datos.desde else "")
    anotar(db, s, "crear", "padron", "dia_no_lectivo", None, f"Día no lectivo {rango}: {datos.motivo.strip()}",
           "Ese día ya está marcado como no lectivo")
    return {"agregados": agregados}


@router.delete("/dias-no-lectivos/{dia_id}", status_code=204)
def borrar_dia(dia_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> None:
    d = obtener(db, DiaNoLectivo, s.colegio.id, dia_id, "Día no lectivo")
    db.delete(d)
    anotar(db, s, "anular", "padron", "dia_no_lectivo", dia_id, f"Quitó el día no lectivo {d.fecha:%d/%m/%Y}")


def es_dia_lectivo(db: Session, colegio_id: int, dia: date) -> bool:
    """Lo usarán las faltas automáticas (paso 2): día de clase de la semana, dentro del año
    activo y no marcado como no lectivo."""
    anio = db.scalar(select(AnioEscolar).where(AnioEscolar.colegio_id == colegio_id, AnioEscolar.activo))
    if anio is None or not (anio.inicio <= dia <= anio.fin) or str(dia.isoweekday()) not in anio.dias_semana:
        return False
    return db.scalar(select(DiaNoLectivo.id).where(DiaNoLectivo.colegio_id == colegio_id,
                                                   DiaNoLectivo.fecha == dia)) is None
