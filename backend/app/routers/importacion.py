import base64
from dataclasses import asdict

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import codigos, importacion, pdf
from app.almacenamiento import get_almacenamiento
from app.comun import guardar, obtener
from app.db import get_db
from app.deps import Sesion, requerir_permiso, tiene_permiso
from app.models import Alumno, AnioEscolar, Colegio, Grado, Matricula, Nivel, Rol, Seccion
from app.routers.estructura import anio_o_activo

router = APIRouter(prefix="/padron", tags=["padron"])
ver = requerir_permiso("padron")
editar = requerir_permiso("padron", "editar")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def imagen_pdf(colegio: Colegio) -> pdf.Imagen:
    logo = get_almacenamiento().leer(colegio.logo_clave) if colegio.logo_clave else None
    return pdf.Imagen(nombre=colegio.nombre, color_primario=colegio.color_primario, logo=logo)


def _secciones(db: Session, cid: int, anio_id: int):
    return db.execute(
        select(Seccion, Grado.nombre, Nivel.nombre)
        .join(Grado, (Grado.colegio_id == Seccion.colegio_id) & (Grado.id == Seccion.grado_id))
        .join(Nivel, (Nivel.colegio_id == Grado.colegio_id) & (Nivel.id == Grado.nivel_id))
        .where(Seccion.colegio_id == cid, Seccion.anio_id == anio_id)
        .order_by(Nivel.orden, Grado.orden, Grado.nombre, Seccion.nombre)
    ).all()


@router.get("/importacion/plantilla")
def plantilla(anio_id: int | None = None, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> Response:
    cid = s.colegio.id
    anio = anio_o_activo(db, cid, anio_id)
    secciones = [(n, g, sec.nombre) for sec, g, n in _secciones(db, cid, anio.id)]
    roles = [r.nombre for r in db.scalars(select(Rol).where(Rol.colegio_id == cid).order_by(Rol.nombre))]
    return Response(importacion.plantilla(secciones, roles), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="padron-{anio.anio}.xlsx"'})


def _analizar(archivo: UploadFile, anio_id: int | None, s: Sesion, db: Session) -> importacion.Analisis:
    anio = anio_o_activo(db, s.colegio.id, anio_id)
    contenido = archivo.file.read(importacion.MAX_BYTES + 1)
    try:
        return importacion.analizar(db, s.colegio.id, anio, contenido,
                                    puede_personal=tiene_permiso(s.usuario, "personal", "editar"),
                                    es_director=s.usuario.rol.es_director)
    except importacion.ArchivoInvalido as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None


def _informe(a: importacion.Analisis) -> dict:
    return {"anio": a.anio.anio, "resumen": a.resumen, "total_errores": a.total_errores,
            "errores": [asdict(e) for e in a.errores],
            "filas_alumnos": len(a.alumnos), "filas_personal": len(a.personal)}


@router.post("/importacion/vista-previa")
def vista_previa(archivo: UploadFile = File(...), anio_id: int | None = None,
                 s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """No guarda nada: dice qué se haría y qué errores hay."""
    return _informe(_analizar(archivo, anio_id, s, db))


@router.post("/importacion/confirmar")
def confirmar(request: Request, archivo: UploadFile = File(...), anio_id: int | None = None,
              s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Vuelve a analizar el archivo y lo guarda todo, solo si no hay ningún error."""
    a = _analizar(archivo, anio_id, s, db)
    if a.total_errores:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"mensaje": "El archivo tiene errores; corrígelos y vuelve a subirlo", **_informe(a)})
    credenciales = importacion.aplicar(db, s.colegio.id, a)
    guardar(db, "Otro usuario cambió el padrón mientras tanto; vuelve a intentarlo")
    cartas = None
    if credenciales:
        # Las claves temporales solo existen en esta respuesta: no se guardan en ningún lado.
        direccion = f"{request.url.scheme}://{request.headers.get('host', '')}"
        cartas = base64.b64encode(pdf.cartas_personal(imagen_pdf(s.colegio), direccion, [
            pdf.FilaCarta(c.nombres, c.apellidos, c.usuario, c.clave_temporal) for c in credenciales
        ])).decode("ascii")
    return {**_informe(a), "cartas_pdf": cartas, "personal_nuevo": len(credenciales)}


@router.get("/carnets")
def carnets(seccion_id: int | None = None, alumno_id: int | None = None, anio_id: int | None = None,
            s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> Response:
    """PDF con 10 carnets por hoja A4, de una sección o de un alumno."""
    cid = s.colegio.id
    if (seccion_id is None) == (alumno_id is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Indica una sección o un alumno")
    anio: AnioEscolar = anio_o_activo(db, cid, anio_id)
    etiquetas = {sec.id: f"{n} · {g} {sec.nombre}" for sec, g, n in _secciones(db, cid, anio.id)}
    consulta = (select(Alumno, Matricula.seccion_id)
                .join(Matricula, (Matricula.colegio_id == Alumno.colegio_id) & (Matricula.alumno_id == Alumno.id))
                .where(Alumno.colegio_id == cid, Matricula.anio_id == anio.id, Alumno.activo))
    if seccion_id is not None:
        obtener(db, Seccion, cid, seccion_id, "Sección")
        consulta = consulta.where(Matricula.seccion_id == seccion_id)
    else:
        obtener(db, Alumno, cid, alumno_id, "Alumno")
        consulta = consulta.where(Alumno.id == alumno_id)
    filas = db.execute(consulta.order_by(Alumno.apellidos, Alumno.nombres)).all()
    contenido = pdf.carnets(imagen_pdf(s.colegio), [
        pdf.FilaCarnet(apellidos=a.apellidos, nombres=a.nombres, seccion=etiquetas.get(sid, ""), anio=anio.anio,
                       qr=codigos.contenido_qr(a.codigo), codigo=a.codigo)
        for a, sid in filas
    ])
    return Response(contenido, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="carnets.pdf"'})
