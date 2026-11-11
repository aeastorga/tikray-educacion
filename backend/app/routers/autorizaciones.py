"""Autorizaciones, lado del colegio (permiso `autorizaciones`): crear en borrador, publicar, cerrar, anular con
motivo, el seguimiento (conteos y lista por sección con quién respondió y cuándo), "Recordar a los que faltan" y la
lista en PDF y Excel. Un rol con `solo_sus_secciones` solo ve y crea para sus secciones."""

from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app import autorizaciones as reglas
from app import cuaderno, excel, pdf
from app.almacenamiento import get_almacenamiento_privado
from app.comun import obtener
from app.configuracion import anotar
from app.db import get_db
from app.deps import Sesion, requerir_permiso
from app.fechas import LIMA, hoy_lima
from app.models import (Alumno, AlumnoAutorizacion, AnioEscolar, Autorizacion, DestinoAutorizacion, Grado, Matricula,
                        Nivel, Seccion)
from app.routers.importacion import imagen_pdf

router = APIRouter(prefix="/autorizaciones", tags=["autorizaciones"])
ver = requerir_permiso("autorizaciones")
editar = requerir_permiso("autorizaciones", "editar")


class AutorizacionIn(BaseModel):
    titulo: str = Field(max_length=120)
    descripcion: str | None = Field(None, max_length=2000)
    fecha_actividad: date | None = None
    fecha_limite: date
    alcance: Literal["colegio", "niveles", "secciones", "alumnos"] = "colegio"
    niveles: list[int] = Field(default_factory=list, max_length=50)
    secciones: list[int] = Field(default_factory=list, max_length=300)
    alumnos: list[int] = Field(default_factory=list, max_length=500)

    @field_validator("titulo")
    @classmethod
    def _titulo(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Escribe el título")
        return v

    @field_validator("descripcion")
    @classmethod
    def _descripcion(cls, v: str | None) -> str | None:
        v = (v or "").strip()  # conserva los saltos de línea
        return v or None

    @model_validator(mode="after")
    def _reglas(self):
        if self.fecha_actividad and self.fecha_limite > self.fecha_actividad:
            raise ValueError("La fecha límite no puede ser después de la actividad")
        for alcance, campo, texto in (("niveles", "niveles", "un nivel"), ("secciones", "secciones", "una sección"),
                                      ("alumnos", "alumnos", "un alumno")):
            if self.alcance == alcance and not getattr(self, campo):
                raise ValueError(f"Elige al menos {texto}")
            setattr(self, campo, sorted(set(getattr(self, campo))) if self.alcance == alcance else [])
        return self


class AnularIn(BaseModel):
    motivo: str = Field(max_length=200)

    @field_validator("motivo")
    @classmethod
    def _motivo(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Escribe el motivo")
        return v


# --- Ayudas -----------------------------------------------------------------------------------------

def _anio_activo(db: Session, cid: int) -> AnioEscolar:
    anio = db.scalar(select(AnioEscolar).where(AnioEscolar.colegio_id == cid, AnioEscolar.activo))
    if anio is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Primero crea y activa el año escolar en Estructura")
    return anio


def _permitidas(db: Session, s: Sesion) -> set[int] | None:
    return cuaderno.secciones_permitidas(db, s.usuario)


def _revisar_destinos(db: Session, cid: int, anio_id: int, datos: AutorizacionIn,
                      permitidas: set[int] | None) -> dict[int, int | None]:
    """Los destinos deben ser de este colegio (las secciones, del año). Devuelve los alumnos a los que iría.
    Un rol con "solo sus secciones" solo puede elegir sus secciones o alumnos de ellas."""
    if permitidas is not None and datos.alcance in ("colegio", "niveles"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puedes pedir autorizaciones a tus secciones")
    if datos.niveles:
        hay = set(db.scalars(select(Nivel.id).where(Nivel.colegio_id == cid, Nivel.id.in_(datos.niveles))))
        if hay != set(datos.niveles):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Algún nivel no existe")
    if datos.secciones:
        hay = set(db.scalars(select(Seccion.id).where(Seccion.colegio_id == cid, Seccion.anio_id == anio_id,
                                                      Seccion.id.in_(datos.secciones))))
        if hay != set(datos.secciones):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Alguna sección no existe en el año escolar")
    dest = {"niveles": datos.niveles, "secciones": datos.secciones, "alumnos": datos.alumnos}
    alumnos = reglas.alumnos_elegidos(db, cid, anio_id, datos.alcance, dest)
    if datos.alumnos and set(alumnos) != set(datos.alumnos):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Algún alumno no existe o no está activo")
    if not reglas.dentro_de(alumnos, permitidas):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puedes pedir autorizaciones a tus secciones")
    return alumnos


def _guardar_destinos(db: Session, a: Autorizacion, datos: AutorizacionIn) -> None:
    db.execute(delete(DestinoAutorizacion).where(DestinoAutorizacion.colegio_id == a.colegio_id,
                                                 DestinoAutorizacion.autorizacion_id == a.id))
    cid = a.colegio_id
    db.add_all([DestinoAutorizacion(colegio_id=cid, autorizacion_id=a.id, nivel_id=n) for n in datos.niveles]
               + [DestinoAutorizacion(colegio_id=cid, autorizacion_id=a.id, seccion_id=x) for x in datos.secciones]
               + [DestinoAutorizacion(colegio_id=cid, autorizacion_id=a.id, alumno_id=x) for x in datos.alumnos])


def _visible(db: Session, s: Sesion, autorizacion_id: int) -> tuple[Autorizacion, dict[int, int | None]]:
    """La autorización y sus alumnos. El docente ve las que van a alguno de sus alumnos (en borrador, solo las
    que son enteramente de sus secciones); cualquier otra da 404."""
    a = obtener(db, Autorizacion, s.colegio.id, autorizacion_id, "Autorización")
    alumnos = reglas.alumnos_de(db, a)
    permitidas = _permitidas(db, s)
    ve = (reglas.dentro_de(alumnos, permitidas) and (alumnos or permitidas is None or a.creado_por_id == s.usuario.id)
          if a.estado == "borrador" else reglas.toca_secciones(alumnos, permitidas))
    if not ve:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Autorización no encontrada")
    return a, alumnos


def _suya(db: Session, s: Sesion, autorizacion_id: int) -> tuple[Autorizacion, dict[int, int | None]]:
    """Para cambiarla: el docente solo las que son enteramente de sus secciones."""
    a, alumnos = _visible(db, s, autorizacion_id)
    if not reglas.dentro_de(alumnos, _permitidas(db, s)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puedes cambiar las autorizaciones de tus secciones")
    return a, alumnos


def _de_sus_secciones(alumnos: dict[int, int | None], permitidas: set[int] | None) -> dict[int, int | None]:
    return alumnos if permitidas is None else {a: sec for a, sec in alumnos.items() if sec in permitidas}


def _dict(db: Session, a: Autorizacion, alumnos: dict[int, int | None], hoy: date,
          vig: dict | None = None) -> dict:
    dest = reglas.destinos(db, a)
    vig = reglas.vigentes(db, a.colegio_id, [a.id]) if vig is None else vig
    return {
        "id": a.id, "titulo": a.titulo, "descripcion": a.descripcion,
        "fecha_actividad": a.fecha_actividad.isoformat() if a.fecha_actividad else None,
        "fecha_limite": a.fecha_limite.isoformat(), "estado": reglas.estado(a, hoy),
        "alcance": a.alcance, **dest, "para": reglas.para_quien(db, a, dest),
        "adjunto": {"nombre": a.adjunto_nombre, "tipo": a.adjunto_tipo, "tamano": a.adjunto_tamano}
        if a.adjunto_clave else None,
        "publicada_en": a.publicada_en.isoformat() if a.publicada_en else None,
        "recordado_en": a.recordado_en.isoformat() if a.recordado_en else None,
        "anulado_motivo": a.anulado_motivo,
        "conteo": reglas.conteo(list(alumnos), {al: vig.get((a.id, al)) for al in alumnos}),
    }


def _resumen(a: Autorizacion) -> str:
    return f"Autorización «{a.titulo}» (vence {a.fecha_limite:%d/%m/%Y})"


def _abierta(a: Autorizacion) -> None:
    if not reglas.abierta(a, hoy_lima()):
        raise HTTPException(status.HTTP_409_CONFLICT, f"La autorización está {reglas.estado(a, hoy_lima())}")


# --- Lectura -----------------------------------------------------------------------------------------

@router.get("/opciones")
def opciones(s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    """Niveles y secciones del año activo para elegir a quién va (el docente, solo sus secciones)."""
    cid = s.colegio.id
    permitidas = _permitidas(db, s)
    anio = db.scalar(select(AnioEscolar).where(AnioEscolar.colegio_id == cid, AnioEscolar.activo))
    niveles = [] if permitidas is not None else [{"id": i, "nombre": n} for i, n in db.execute(
        select(Nivel.id, Nivel.nombre).where(Nivel.colegio_id == cid).order_by(Nivel.orden, Nivel.nombre))]
    secciones = []
    if anio:
        nombres = reglas.nombres_secciones(db, cid)
        q = (select(Seccion.id, Grado.nivel_id)
             .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
             .join(Nivel, and_(Nivel.colegio_id == Grado.colegio_id, Nivel.id == Grado.nivel_id))
             .where(Seccion.colegio_id == cid, Seccion.anio_id == anio.id)
             .order_by(Nivel.orden, Grado.orden, Seccion.nombre))
        secciones = [{"id": i, "nombre": nombres[i], "nivel_id": n} for i, n in db.execute(q)
                     if permitidas is None or i in permitidas]
    return {"anio": anio.anio if anio else None, "hoy": hoy_lima().isoformat(), "niveles": niveles,
            "secciones": secciones, "solo_sus_secciones": permitidas is not None}


@router.get("/alumnos")
def buscar_alumnos(q: str = Query(min_length=2, max_length=60), s: Sesion = Depends(ver),
                   db: Session = Depends(get_db)) -> list[dict]:
    """Para elegir alumnos sueltos: hasta 20 alumnos activos matriculados en el año (el docente, de sus secciones)."""
    cid = s.colegio.id
    anio = _anio_activo(db, cid)
    permitidas = _permitidas(db, s)
    patron = f"%{' '.join(q.split())}%"
    consulta = (select(Alumno.id, Alumno.nombres, Alumno.apellidos, Matricula.seccion_id)
                .join(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id, Matricula.alumno_id == Alumno.id,
                                      Matricula.anio_id == anio.id))
                .where(Alumno.colegio_id == cid, Alumno.activo,
                       or_(func.concat(Alumno.apellidos, " ", Alumno.nombres).ilike(patron),
                           func.concat(Alumno.nombres, " ", Alumno.apellidos).ilike(patron),
                           Alumno.numero_documento.ilike(patron)))
                .order_by(Alumno.apellidos, Alumno.nombres).limit(20))
    if permitidas is not None:
        consulta = consulta.where(Matricula.seccion_id.in_(permitidas or [-1]))
    nombres = reglas.nombres_secciones(db, cid)
    return [{"id": i, "nombre": f"{ap}, {no}", "seccion": nombres.get(sec, "")}
            for i, no, ap, sec in db.execute(consulta)]


@router.get("")
def lista(s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> list[dict]:
    """Todas las que puede ver, con sus conteos (las abiertas primero, por fecha límite)."""
    cid, hoy = s.colegio.id, hoy_lima()
    permitidas = _permitidas(db, s)
    todas = list(db.scalars(select(Autorizacion).where(Autorizacion.colegio_id == cid)
                            .order_by(Autorizacion.creado_en.desc(), Autorizacion.id.desc())))
    vig = reglas.vigentes(db, cid, [a.id for a in todas])
    fijados: dict[int, dict[int, int | None]] = {}
    for aid, al, sec in db.execute(select(AlumnoAutorizacion.autorizacion_id, AlumnoAutorizacion.alumno_id,
                                          AlumnoAutorizacion.seccion_id).where(AlumnoAutorizacion.colegio_id == cid)):
        fijados.setdefault(aid, {})[al] = sec
    salida = []
    for a in todas:
        alumnos = reglas.alumnos_de(db, a) if a.publicada_en is None else fijados.get(a.id, {})
        if a.estado == "borrador":
            if not (reglas.dentro_de(alumnos, permitidas)
                    and (alumnos or permitidas is None or a.creado_por_id == s.usuario.id)):
                continue
        elif not reglas.toca_secciones(alumnos, permitidas):
            continue
        salida.append(_dict(db, a, _de_sus_secciones(alumnos, permitidas), hoy, vig))
    orden = {"borrador": 0, "publicada": 1, "cerrada": 2, "anulada": 3}
    salida.sort(key=lambda d: (orden[d["estado"]], d["fecha_limite"] if d["estado"] == "publicada" else ""))
    return salida


@router.get("/{autorizacion_id}")
def detalle(autorizacion_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    """Conteos y la lista por sección: estado de cada alumno, quién respondió, cuándo y el historial (A2)."""
    cid, hoy = s.colegio.id, hoy_lima()
    a, alumnos = _visible(db, s, autorizacion_id)
    alumnos = _de_sus_secciones(alumnos, _permitidas(db, s))
    vig = reglas.vigentes(db, cid, [a.id])
    hist = reglas.historial(db, a)
    return _dict(db, a, alumnos, hoy, vig) | {"por_seccion": _por_seccion(db, a, alumnos, vig, hist),
                                             "puede_responder": reglas.abierta(a, hoy)}


def _por_seccion(db: Session, a: Autorizacion, alumnos: dict[int, int | None], vig: dict,
                 hist: dict | None = None) -> list[dict]:
    cid = a.colegio_id
    nombres = reglas.nombres_secciones(db, cid)
    orden = reglas.orden_secciones(db, cid)
    personas = {i: f"{ap}, {no}" for i, no, ap in db.execute(
        select(Alumno.id, Alumno.nombres, Alumno.apellidos).where(Alumno.colegio_id == cid,
                                                                  Alumno.id.in_(list(alumnos) or [-1])))}
    grupos: dict[int | None, list[int]] = {}
    for al, sec in alumnos.items():
        grupos.setdefault(sec, []).append(al)
    salida = []
    for sec in sorted(grupos, key=lambda x: (x is None, orden.get(x, ()), x or 0)):
        ids = sorted(grupos[sec], key=lambda i: personas.get(i, ""))
        filas = []
        for al in ids:
            r = vig.get((a.id, al))
            fila = {"alumno_id": al, "alumno": personas.get(al, "?"),
                    "estado": "sin_respuesta" if r is None else "autoriza" if r.autoriza else "no_autoriza",
                    "respuesta": reglas.respuesta_dict(r) if r else None}
            if hist is not None:
                fila["historial"] = [reglas.respuesta_dict(h) for h in hist.get(al, [])]
            filas.append(fila)
        salida.append({"seccion_id": sec, "seccion": nombres.get(sec, "Sin sección") if sec else "Sin sección",
                       "conteo": reglas.conteo(ids, {al: vig.get((a.id, al)) for al in ids}), "alumnos": filas})
    return salida


def _filas_lista(db: Session, s: Sesion, autorizacion_id: int, seccion_id: int | None):
    a, alumnos = _visible(db, s, autorizacion_id)
    if a.estado == "borrador":
        raise HTTPException(status.HTTP_409_CONFLICT, "Primero publica la autorización")
    alumnos = _de_sus_secciones(alumnos, _permitidas(db, s))
    if seccion_id is not None:
        alumnos = {al: sec for al, sec in alumnos.items() if sec == seccion_id}
    return a, _por_seccion(db, a, alumnos, reglas.vigentes(db, a.colegio_id, [a.id]))


def _texto_respuesta(fila: dict) -> tuple[str, str, str]:
    r = fila["respuesta"]
    if r is None:
        return "Sin respuesta", "", ""
    cuando = datetime.fromisoformat(r["en"]).astimezone(LIMA).strftime("%d/%m/%Y %H:%M")
    return ("Autoriza" if r["autoriza"] else "No autoriza"), r["apoderado"], cuando


def _detalle_pdf(a: Autorizacion) -> str:
    partes = [f"Actividad: {a.fecha_actividad:%d/%m/%Y}"] if a.fecha_actividad else []
    return " · ".join(partes + [f"Fecha límite: {a.fecha_limite:%d/%m/%Y}", f"Impreso: {hoy_lima():%d/%m/%Y}"])


@router.get("/{autorizacion_id}/lista.pdf")
def lista_pdf(autorizacion_id: int, seccion_id: int | None = None, s: Sesion = Depends(ver),
              db: Session = Depends(get_db)) -> Response:
    """Una hoja por sección con cada alumno y su respuesta (para llevar el día de la actividad)."""
    a, secciones = _filas_lista(db, s, autorizacion_id, seccion_id)
    contenido = pdf.lista_autorizacion(imagen_pdf(s.colegio), a.titulo, _detalle_pdf(a), [
        (g["seccion"], [pdf.FilaAutorizacion(f["alumno"], *_texto_respuesta(f)) for f in g["alumnos"]])
        for g in secciones])
    return Response(contenido, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="autorizacion-{a.id}.pdf"'})


@router.get("/{autorizacion_id}/lista.xlsx")
def lista_xlsx(autorizacion_id: int, seccion_id: int | None = None, s: Sesion = Depends(ver),
               db: Session = Depends(get_db)) -> Response:
    a, secciones = _filas_lista(db, s, autorizacion_id, seccion_id)
    filas = []
    for g in secciones:
        for f in g["alumnos"]:
            respuesta, apoderado, cuando = _texto_respuesta(f)
            filas.append([g["seccion"], f["alumno"], respuesta, apoderado, cuando,
                          (f["respuesta"] or {}).get("comentario") or ""])
    return excel.tabla(a.titulo, ["Sección", "Alumno", "Respuesta", "Respondió", "Fecha y hora", "Comentario"],
                       filas, f"autorizacion-{a.id}.xlsx", s.colegio.color_primario)


@router.get("/{autorizacion_id}/adjunto")
def adjunto(autorizacion_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)):
    a, _ = _visible(db, s, autorizacion_id)
    return respuesta_adjunto(a)


def respuesta_adjunto(a: Autorizacion):
    from urllib.parse import quote

    contenido = get_almacenamiento_privado().leer(a.adjunto_clave) if a.adjunto_clave else None
    if contenido is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Archivo no encontrado")
    return Response(contenido, media_type=a.adjunto_tipo, headers={
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(a.adjunto_nombre)}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


# --- Cambios -------------------------------------------------------------------------------------------

@router.post("", status_code=201)
def crear(datos: AutorizacionIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Se crea en borrador; sale a las familias al publicarla."""
    cid = s.colegio.id
    if datos.fecha_limite < hoy_lima():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "La fecha límite ya pasó")
    anio = _anio_activo(db, cid)
    alumnos = _revisar_destinos(db, cid, anio.id, datos, _permitidas(db, s))
    a = Autorizacion(colegio_id=cid, anio_id=anio.id, titulo=datos.titulo, descripcion=datos.descripcion,
                     fecha_actividad=datos.fecha_actividad, fecha_limite=datos.fecha_limite, alcance=datos.alcance,
                     creado_por_id=s.usuario.id)
    db.add(a)
    db.flush()
    _guardar_destinos(db, a, datos)
    anotar(db, s, "crear", "autorizaciones", "autorizacion", a, f"Borrador: {_resumen(a)}")
    return _dict(db, a, alumnos, hoy_lima())


@router.put("/{autorizacion_id}")
def editar_autorizacion(autorizacion_id: int, datos: AutorizacionIn, s: Sesion = Depends(editar),
                        db: Session = Depends(get_db)) -> dict:
    """En borrador se cambia todo. Publicada (y abierta) se cambian los textos y las fechas, no a quién va."""
    cid, hoy = s.colegio.id, hoy_lima()
    a, alumnos = _suya(db, s, autorizacion_id)
    if a.estado != "borrador":
        _abierta(a)
        if datos.alcance != a.alcance or {k: v for k, v in reglas.destinos(db, a).items()} != {
                "niveles": datos.niveles, "secciones": datos.secciones, "alumnos": datos.alumnos}:
            raise HTTPException(status.HTTP_409_CONFLICT, "A quién va no se cambia después de publicar")
    if datos.fecha_limite < hoy:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "La fecha límite ya pasó")
    if a.estado == "borrador":
        alumnos = _revisar_destinos(db, cid, a.anio_id, datos, _permitidas(db, s))
        a.alcance = datos.alcance
        _guardar_destinos(db, a, datos)
    elif datos.fecha_limite != a.fecha_limite:
        # Otra fecha límite: el recordatorio del día anterior vuelve a tocar (si aún falta).
        a.recordatorio_en = datetime.now(UTC) if datos.fecha_limite <= hoy + timedelta(days=1) else None
    for campo in ("titulo", "descripcion", "fecha_actividad", "fecha_limite"):
        setattr(a, campo, getattr(datos, campo))
    anotar(db, s, "editar", "autorizaciones", "autorizacion", a, _resumen(a))
    return _dict(db, a, alumnos, hoy)


@router.put("/{autorizacion_id}/adjunto")
async def poner_adjunto(autorizacion_id: int, archivo: UploadFile = File(...), s: Sesion = Depends(editar),
                        db: Session = Depends(get_db)) -> dict:
    """PDF o imagen de hasta 5 MB, en el almacenamiento privado. Reemplaza al anterior."""
    a, alumnos = _suya(db, s, autorizacion_id)
    if a.estado != "borrador":
        _abierta(a)
    contenido = await archivo.read(reglas.MAX_BYTES_ADJUNTO + 1)
    if len(contenido) > reglas.MAX_BYTES_ADJUNTO:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El archivo pesa más de 5 MB")
    tipo = cuaderno._tipo(contenido, archivo.content_type) if contenido else None
    if tipo not in reglas.TIPOS_ADJUNTO:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Solo se aceptan PDF o imágenes (JPG, PNG, WEBP)")
    import uuid

    almacen = get_almacenamiento_privado()
    anterior, clave = a.adjunto_clave, f"autorizaciones/{a.colegio_id}/{uuid.uuid4().hex}"
    almacen.guardar(clave, contenido, tipo)
    a.adjunto_clave, a.adjunto_nombre = clave, (archivo.filename or "adjunto")[-200:]
    a.adjunto_tipo, a.adjunto_tamano = tipo, len(contenido)
    try:
        anotar(db, s, "editar", "autorizaciones", "autorizacion", a, f"Adjunto en {_resumen(a)}")
    except Exception:
        almacen.borrar(clave)
        raise
    if anterior:
        almacen.borrar(anterior)
    return _dict(db, a, alumnos, hoy_lima())


@router.delete("/{autorizacion_id}/adjunto")
def quitar_adjunto(autorizacion_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    a, alumnos = _suya(db, s, autorizacion_id)
    if a.estado != "borrador":
        _abierta(a)
    anterior = a.adjunto_clave
    a.adjunto_clave = a.adjunto_nombre = a.adjunto_tipo = a.adjunto_tamano = None
    anotar(db, s, "editar", "autorizaciones", "autorizacion", a, f"Quitó el adjunto de {_resumen(a)}")
    if anterior:
        get_almacenamiento_privado().borrar(anterior)
    return _dict(db, a, alumnos, hoy_lima())


@router.post("/{autorizacion_id}/publicar")
def publicar(autorizacion_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    a, alumnos = _suya(db, s, autorizacion_id)
    if a.estado != "borrador":
        raise HTTPException(status.HTTP_409_CONFLICT, "La autorización ya se publicó")
    if a.fecha_limite < hoy_lima():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "La fecha límite ya pasó: cámbiala antes de publicar")
    if not alumnos:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No hay alumnos activos a los que vaya")
    avisados = reglas.publicar(db, a, s.colegio)
    anotar(db, s, "editar", "autorizaciones", "autorizacion", a,
           f"Publicó {_resumen(a)} · {len(alumnos)} alumnos · aviso a {avisados} familia{'s' if avisados != 1 else ''}")
    return _dict(db, a, reglas.alumnos_de(db, a), hoy_lima()) | {"avisos": avisados}


@router.post("/{autorizacion_id}/recordar")
def recordar(autorizacion_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Aviso push solo a los apoderados de los alumnos que aún no tienen respuesta. Una vez al día."""
    a, _ = _suya(db, s, autorizacion_id)
    _abierta(a)
    ahora = datetime.now(UTC)
    if a.recordado_en and a.recordado_en.astimezone(LIMA).date() == ahora.astimezone(LIMA).date():
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya se recordó hoy a los que faltan")
    from app import configuracion

    if not configuracion.aviso_permitido(s.colegio, "autorizar"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Los avisos de autorizaciones están apagados en Configuración")
    avisados = reglas.recordar(db, a, ahora=ahora)
    a.recordado_en = ahora
    anotar(db, s, "editar", "autorizaciones", "autorizacion", a,
           f"Recordó {_resumen(a)} a {avisados} familia{'s' if avisados != 1 else ''}")
    return {"avisos": avisados}


@router.post("/{autorizacion_id}/cerrar")
def cerrar(autorizacion_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Cierra antes de la fecha límite: ya no se responde."""
    a, alumnos = _suya(db, s, autorizacion_id)
    _abierta(a)
    a.estado, a.cerrada_en = "cerrada", datetime.now(UTC)
    reglas.quitar_pendientes(db, a, "autorización cerrada")
    anotar(db, s, "editar", "autorizaciones", "autorizacion", a, f"Cerró {_resumen(a)}")
    return _dict(db, a, alumnos, hoy_lima())


@router.post("/{autorizacion_id}/anular")
def anular(autorizacion_id: int, datos: AnularIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    a, alumnos = _suya(db, s, autorizacion_id)
    if a.estado == "anulada":
        raise HTTPException(status.HTTP_409_CONFLICT, "La autorización ya está anulada")
    a.estado, a.anulado_en, a.anulado_motivo, a.anulado_por_id = "anulada", datetime.now(UTC), datos.motivo, s.usuario.id
    reglas.quitar_pendientes(db, a, "autorización anulada")
    anotar(db, s, "anular", "autorizaciones", "autorizacion", a, f"Anuló {_resumen(a)}: {datos.motivo}")
    return _dict(db, a, alumnos, hoy_lima())
