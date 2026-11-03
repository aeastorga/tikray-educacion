from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import codigos, familias, validacion
from app.comun import guardar, obtener
from app.db import get_db
from app.deps import Sesion, requerir_permiso
from app.models import Alumno, AlumnoApoderado, AnioEscolar, Apoderado, Grado, Matricula, Nivel, Seccion
from app.routers.estructura import anio_o_activo

router = APIRouter(prefix="/padron", tags=["padron"])
ver = requerir_permiso("padron")
editar = requerir_permiso("padron", "editar")


class ConDocumento(BaseModel):
    tipo_documento: str = "DNI"
    numero_documento: str
    nombres: str
    apellidos: str

    @model_validator(mode="after")
    def _normalizar(self):
        self.tipo_documento = validacion.tipo_documento(self.tipo_documento)
        self.numero_documento = validacion.documento(self.tipo_documento, self.numero_documento)
        self.nombres = validacion.nombre(self.nombres)
        self.apellidos = validacion.nombre(self.apellidos)
        return self


class DatosAlumno(ConDocumento):
    fecha_nacimiento: date | None = None
    seccion_id: int | None = None
    activo: bool = True


class DatosApoderado(ConDocumento):
    celular: str | None = None
    correo: str | None = None

    _celular = field_validator("celular")(classmethod(lambda cls, v: validacion.celular(v)))
    _correo = field_validator("correo")(classmethod(lambda cls, v: validacion.correo(v)))


class Vinculo(DatosApoderado):
    parentesco: str = Field(min_length=1, max_length=30)
    recibe_avisos: bool = True


def matricular(db: Session, colegio_id: int, alumno_id: int, seccion: Seccion) -> bool:
    """Matricula en la sección (o cambia de sección dentro del mismo año). True si cambió algo."""
    m = db.scalar(select(Matricula).where(Matricula.colegio_id == colegio_id, Matricula.anio_id == seccion.anio_id,
                                          Matricula.alumno_id == alumno_id))
    if m is None:
        db.add(Matricula(colegio_id=colegio_id, anio_id=seccion.anio_id, alumno_id=alumno_id, seccion_id=seccion.id))
        return True
    if m.seccion_id != seccion.id:
        m.seccion_id = seccion.id
        return True
    return False


def _etiquetas_seccion(db: Session, colegio_id: int, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    filas = db.execute(
        select(Seccion.id, Nivel.nombre, Grado.nombre, Seccion.nombre)
        .join(Grado, (Grado.colegio_id == Seccion.colegio_id) & (Grado.id == Seccion.grado_id))
        .join(Nivel, (Nivel.colegio_id == Grado.colegio_id) & (Nivel.id == Grado.nivel_id))
        .where(Seccion.colegio_id == colegio_id, Seccion.id.in_(ids))
    )
    return {sid: f"{n} · {g} {s}" for sid, n, g, s in filas}


def _alumno(a: Alumno, seccion_id: int | None = None, seccion: str | None = None) -> dict:
    return {"id": a.id, "tipo_documento": a.tipo_documento, "numero_documento": a.numero_documento,
            "nombres": a.nombres, "apellidos": a.apellidos,
            "fecha_nacimiento": a.fecha_nacimiento.isoformat() if a.fecha_nacimiento else None,
            "codigo": a.codigo, "activo": a.activo, "seccion_id": seccion_id, "seccion": seccion}


def _apoderado(ap: Apoderado, v: AlumnoApoderado | None = None) -> dict:
    d = {"id": ap.id, "tipo_documento": ap.tipo_documento, "numero_documento": ap.numero_documento,
         "nombres": ap.nombres, "apellidos": ap.apellidos, "celular": ap.celular, "correo": ap.correo}
    if v is not None:
        d |= {"parentesco": v.parentesco, "recibe_avisos": v.recibe_avisos}
    return d


@router.get("/alumnos")
def listar(
    anio_id: int | None = None, seccion_id: int | None = None, q: str | None = None,
    desde: int = Query(0, ge=0), limite: int = Query(50, ge=1, le=500),
    s: Sesion = Depends(ver), db: Session = Depends(get_db),
) -> dict:
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    consulta = (select(Alumno, Matricula.seccion_id)
                .outerjoin(Matricula, (Matricula.colegio_id == Alumno.colegio_id) & (Matricula.alumno_id == Alumno.id)
                           & (Matricula.anio_id == anio.id))
                .where(Alumno.colegio_id == cid))
    if seccion_id is not None:
        consulta = consulta.where(Matricula.seccion_id == seccion_id)
    if q and q.strip():
        patron = f"%{q.strip()}%"
        consulta = consulta.where(or_(Alumno.apellidos.ilike(patron), Alumno.nombres.ilike(patron),
                                      Alumno.numero_documento.ilike(patron)))
    total = db.scalar(select(func.count()).select_from(consulta.subquery()))
    filas = db.execute(consulta.order_by(Alumno.apellidos, Alumno.nombres).offset(desde).limit(limite)).all()
    etiquetas = _etiquetas_seccion(db, cid, {sid for _, sid in filas if sid})
    return {"total": total, "alumnos": [_alumno(a, sid, etiquetas.get(sid)) for a, sid in filas]}


@router.post("/alumnos", status_code=201)
def crear(datos: DatosAlumno, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    seccion = obtener(db, Seccion, cid, datos.seccion_id, "Sección") if datos.seccion_id else None
    a = Alumno(colegio_id=cid, codigo=codigos.generar(db, cid),
               **datos.model_dump(exclude={"seccion_id"}))
    db.add(a)
    guardar(db, "Ya existe un alumno con ese documento", solo_flush=True)
    if seccion:
        matricular(db, cid, a.id, seccion)
    guardar(db, "Ya existe un alumno con ese documento")
    return detalle(a.id, s, db)


@router.get("/alumnos/{alumno_id}")
def detalle(alumno_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    a = obtener(db, Alumno, cid, alumno_id, "Alumno")
    matriculas = db.execute(
        select(Matricula, AnioEscolar.anio).join(
            AnioEscolar, (AnioEscolar.colegio_id == Matricula.colegio_id) & (AnioEscolar.id == Matricula.anio_id))
        .where(Matricula.colegio_id == cid, Matricula.alumno_id == a.id).order_by(AnioEscolar.anio.desc())
    ).all()
    etiquetas = _etiquetas_seccion(db, cid, {m.seccion_id for m, _ in matriculas})
    activo = db.scalar(select(AnioEscolar.id).where(AnioEscolar.colegio_id == cid, AnioEscolar.activo))
    actual = next((m for m, _ in matriculas if m.anio_id == activo), None)
    apoderados = db.execute(
        select(Apoderado, AlumnoApoderado).join(
            AlumnoApoderado, (AlumnoApoderado.colegio_id == Apoderado.colegio_id)
            & (AlumnoApoderado.apoderado_id == Apoderado.id))
        .where(AlumnoApoderado.colegio_id == cid, AlumnoApoderado.alumno_id == a.id)
        .order_by(Apoderado.apellidos)
    ).all()
    return {
        **_alumno(a, actual.seccion_id if actual else None, etiquetas.get(actual.seccion_id) if actual else None),
        "matriculas": [{"anio": anio, "seccion_id": m.seccion_id, "seccion": etiquetas.get(m.seccion_id)}
                       for m, anio in matriculas],
        "apoderados": [_apoderado(ap, v) for ap, v in apoderados],
    }


@router.put("/alumnos/{alumno_id}")
def editar_alumno(alumno_id: int, datos: DatosAlumno, s: Sesion = Depends(editar),
                  db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    a = obtener(db, Alumno, cid, alumno_id, "Alumno")
    for campo, valor in datos.model_dump(exclude={"seccion_id"}).items():
        setattr(a, campo, valor)
    # Antes de cualquier otra consulta: el autoflush haría saltar el documento repetido fuera de guardar().
    guardar(db, "Ya existe un alumno con ese documento", solo_flush=True)
    if datos.seccion_id:
        matricular(db, cid, a.id, obtener(db, Seccion, cid, datos.seccion_id, "Sección"))
    guardar(db, "Ya existe un alumno con ese documento")
    return detalle(a.id, s, db)


@router.post("/alumnos/{alumno_id}/nuevo-codigo")
def nuevo_codigo(alumno_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Para un carnet perdido: el código anterior deja de servir."""
    a = obtener(db, Alumno, s.colegio.id, alumno_id, "Alumno")
    a.codigo = codigos.generar(db, s.colegio.id)
    guardar(db)
    return {"codigo": a.codigo}


def buscar_o_crear_apoderado(db: Session, colegio_id: int, datos: DatosApoderado,
                             usuario_id: int | None = None) -> Apoderado:
    ap = db.scalar(select(Apoderado).where(Apoderado.colegio_id == colegio_id,
                                           Apoderado.tipo_documento == datos.tipo_documento,
                                           Apoderado.numero_documento == datos.numero_documento))
    if ap is None:
        ap = Apoderado(colegio_id=colegio_id, tipo_documento=datos.tipo_documento,
                       numero_documento=datos.numero_documento)
        db.add(ap)
    ap.nombres, ap.apellidos = datos.nombres, datos.apellidos
    # Un dato vacío no borra el que ya estaba; un cambio queda registrado.
    familias.cambiar_contacto(db, ap, datos.celular, datos.correo, "panel", usuario_id)
    db.flush()
    return ap


@router.post("/alumnos/{alumno_id}/apoderados", status_code=201)
def vincular(alumno_id: int, datos: Vinculo, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    a = obtener(db, Alumno, cid, alumno_id, "Alumno")
    ap = buscar_o_crear_apoderado(db, cid, datos, s.usuario.id)
    v = db.get(AlumnoApoderado, (a.id, ap.id))
    if v is None:
        v = AlumnoApoderado(colegio_id=cid, alumno_id=a.id, apoderado_id=ap.id)
        db.add(v)
    v.parentesco, v.recibe_avisos = datos.parentesco.strip(), datos.recibe_avisos
    guardar(db)
    return _apoderado(ap, v)


@router.delete("/alumnos/{alumno_id}/apoderados/{apoderado_id}", status_code=204)
def desvincular(alumno_id: int, apoderado_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> None:
    cid = s.colegio.id
    obtener(db, Alumno, cid, alumno_id, "Alumno")
    v = db.scalar(select(AlumnoApoderado).where(AlumnoApoderado.colegio_id == cid,
                                                AlumnoApoderado.alumno_id == alumno_id,
                                                AlumnoApoderado.apoderado_id == apoderado_id))
    if v is not None:
        db.delete(v)
        guardar(db)


@router.put("/apoderados/{apoderado_id}")
def editar_apoderado(apoderado_id: int, datos: DatosApoderado, s: Sesion = Depends(editar),
                     db: Session = Depends(get_db)) -> dict:
    ap = obtener(db, Apoderado, s.colegio.id, apoderado_id, "Apoderado")
    if ap.cuenta_id is not None and (datos.tipo_documento, datos.numero_documento) != (
            ap.tipo_documento, ap.numero_documento):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Este apoderado ya activó su cuenta con ese documento; no se puede cambiar")
    familias.cambiar_contacto(db, ap, datos.celular, datos.correo, "panel", s.usuario.id)
    for campo, valor in datos.model_dump(exclude={"celular", "correo"}).items():
        setattr(ap, campo, valor)
    guardar(db, "Ya existe un apoderado con ese documento")
    return _apoderado(ap)
