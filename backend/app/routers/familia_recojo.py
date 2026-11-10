"""Recojo seguro, lado de la familia: el apoderado ve y arma la lista de quién puede recoger a sus hijos
(entra activo de inmediato) y autoriza a alguien por un solo día.

Solo sus hijos en el colegio por cuya dirección entró y con el acceso activo; cualquier otro id da 404.
"""

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app import configuracion, recojo
from app.almacenamiento import get_almacenamiento_privado
from app.comun import guardar
from app.db import get_db
from app.deps import SesionFamilia, modulo_encendido
from app.fechas import hoy_lima
from app.models import Alumno, AlumnoApoderado, AutorizacionRecojoDia, AutorizadoRecojo
from app.routers.familia_cuaderno import familia_activa
from app.routers.recojo import AutorizadoIn, PersonaIn, foto_respuesta, nombre

privado = APIRouter(prefix="/familia/recojo", tags=["familia"], dependencies=[Depends(modulo_encendido("recojo"))])


class DelDiaIn(PersonaIn):
    fecha: date


def _hijos(db: Session, s: SesionFamilia) -> list[Alumno]:
    return db.scalars(select(Alumno).join(AlumnoApoderado, and_(AlumnoApoderado.colegio_id == Alumno.colegio_id,
                                                                AlumnoApoderado.alumno_id == Alumno.id))
                      .where(Alumno.colegio_id == s.colegio.id, AlumnoApoderado.apoderado_id == s.apoderado.id,
                             Alumno.activo).order_by(Alumno.nombres)).all()


def _hijo(db: Session, s: SesionFamilia, alumno_id: int) -> Alumno:
    for a in _hijos(db, s):
        if a.id == alumno_id:
            return a
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Alumno no encontrado")


def _autorizado(db: Session, s: SesionFamilia, autorizado_id: int) -> AutorizadoRecojo:
    x = db.scalar(select(AutorizadoRecojo).where(AutorizadoRecojo.colegio_id == s.colegio.id,
                                                 AutorizadoRecojo.id == autorizado_id,
                                                 AutorizadoRecojo.alumno_id.in_([a.id for a in _hijos(db, s)])))
    if x is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Autorizado no encontrado")
    return x


def _quien(s: SesionFamilia) -> str:
    return f"{s.apoderado.nombres} {s.apoderado.apellidos} (apoderado)"


def _anotar(db: Session, s: SesionFamilia, accion: str, que: str, objeto, resumen: str, **kwargs) -> None:
    """Como `anotar` del panel, con el apoderado como autor."""
    guardar(db, solo_flush=True, **kwargs)
    objeto_id = objeto if isinstance(objeto, int) or objeto is None else objeto.id
    configuracion.registrar(db, s.colegio.id, _quien(s), accion, "recojo", que, objeto_id, resumen)
    guardar(db, **kwargs)


@privado.get("")
def listar(s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)) -> dict:
    cid, hoy = s.colegio.id, hoy_lima()
    hijos = _hijos(db, s)
    ids = [a.id for a in hijos]
    autorizados: dict[int, list] = {}
    for x in db.scalars(select(AutorizadoRecojo).where(AutorizadoRecojo.colegio_id == cid,
                                                       AutorizadoRecojo.alumno_id.in_(ids))
                        .order_by(AutorizadoRecojo.activo.desc(), AutorizadoRecojo.apellidos)):
        autorizados.setdefault(x.alumno_id, []).append(recojo.autorizado_dict(x))
    del_dia: dict[int, list] = {}
    for x in db.scalars(select(AutorizacionRecojoDia).where(
            AutorizacionRecojoDia.colegio_id == cid, AutorizacionRecojoDia.alumno_id.in_(ids),
            AutorizacionRecojoDia.fecha >= hoy, AutorizacionRecojoDia.anulada_en.is_(None))
            .order_by(AutorizacionRecojoDia.fecha)):
        del_dia.setdefault(x.alumno_id, []).append(recojo.del_dia_dict(x))
    return {
        "hoy": hoy.isoformat(), "max_autorizados": recojo.MAX_AUTORIZADOS, "dias_adelante": recojo.DIAS_ADELANTE,
        "hijos": [{"id": a.id, "nombres": a.nombres, "apellidos": a.apellidos,
                   "autorizados": autorizados.get(a.id, []),
                   "del_dia": del_dia.get(a.id, [])} for a in hijos],
    }


@privado.post("/hijos/{alumno_id}/autorizados", status_code=201)
def crear(alumno_id: int, datos: AutorizadoIn, s: SesionFamilia = Depends(familia_activa),
          db: Session = Depends(get_db)) -> dict:
    a = _hijo(db, s, alumno_id)
    x = recojo.crear_autorizado(db, s.colegio.id, a.id, datos.campos(), apoderado_id=s.apoderado.id)
    _anotar(db, s, "crear", "autorizado", x, f"Autorizó a {nombre(x)} ({x.parentesco}) a recoger a {nombre(a)}")
    return recojo.autorizado_dict(x)


@privado.put("/autorizados/{autorizado_id}")
def editar(autorizado_id: int, datos: AutorizadoIn, s: SesionFamilia = Depends(familia_activa),
           db: Session = Depends(get_db)) -> dict:
    x = _autorizado(db, s, autorizado_id)
    que = recojo.editar_autorizado(db, x, datos.campos(), datos.activo)
    a = db.get(Alumno, x.alumno_id)
    _anotar(db, s, "editar", "autorizado", x, f"{que} a {nombre(x)} en la lista de recojo de {nombre(a)}")
    return recojo.autorizado_dict(x)


@privado.put("/autorizados/{autorizado_id}/foto")
async def subir_foto(autorizado_id: int, archivo: UploadFile | None = File(None),
                     s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)) -> dict:
    x = _autorizado(db, s, autorizado_id)
    tipo, contenido = await recojo.leer_foto(archivo)
    anterior = recojo.guardar_foto(x, tipo, contenido)
    try:
        _anotar(db, s, "editar", "autorizado", x, f"Foto de {nombre(x)} (lista de recojo)")
    except Exception:
        get_almacenamiento_privado().borrar(x.foto_clave)
        raise
    if anterior:
        get_almacenamiento_privado().borrar(anterior)
    return recojo.autorizado_dict(x)


@privado.get("/autorizados/{autorizado_id}/foto")
def foto(autorizado_id: int, s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)) -> Response:
    return foto_respuesta(_autorizado(db, s, autorizado_id))


@privado.post("/hijos/{alumno_id}/del-dia", status_code=201)
def autorizar_dia(alumno_id: int, datos: DelDiaIn, s: SesionFamilia = Depends(familia_activa),
                  db: Session = Depends(get_db)) -> dict:
    a = _hijo(db, s, alumno_id)
    hoy = hoy_lima()
    if not hoy <= datos.fecha <= hoy + timedelta(days=recojo.DIAS_ADELANTE):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Elige una fecha desde hoy hasta {recojo.DIAS_ADELANTE} días adelante")
    x = AutorizacionRecojoDia(colegio_id=s.colegio.id, alumno_id=a.id, apoderado_id=s.apoderado.id,
                              **datos.model_dump())
    db.add(x)
    _anotar(db, s, "crear", "autorización del día", x,
            f"Autorizó a {nombre(x)} ({x.parentesco}) a recoger a {nombre(a)} el {x.fecha.strftime('%d/%m/%Y')}")
    return recojo.del_dia_dict(x)


@privado.post("/del-dia/{autorizacion_id}/anular", status_code=204)
def anular_dia(autorizacion_id: int, s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)) -> None:
    x = db.scalar(select(AutorizacionRecojoDia).where(
        AutorizacionRecojoDia.colegio_id == s.colegio.id, AutorizacionRecojoDia.id == autorizacion_id,
        AutorizacionRecojoDia.alumno_id.in_([a.id for a in _hijos(db, s)]),
        AutorizacionRecojoDia.anulada_en.is_(None)))
    if x is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Autorización no encontrada")
    x.anulada_en = datetime.now(UTC)
    a = db.get(Alumno, x.alumno_id)
    _anotar(db, s, "anular", "autorización del día", x,
            f"Anuló la autorización de {nombre(x)} para recoger a {nombre(a)} el {x.fecha.strftime('%d/%m/%Y')}")
