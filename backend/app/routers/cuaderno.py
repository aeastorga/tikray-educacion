"""Cuaderno de control, lado del colegio: comunicados, incidencias, citaciones,
justificaciones y permisos de salida; quién leyó y quién no; el hilo de respuestas.

Permisos del módulo "cuaderno": ver (leer y ver lectores) y editar (escribir, responder,
aprobar). Un rol con `solo_sus_secciones` solo ve y escribe lo de las secciones a su cargo.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.orm import Session

from app import configuracion, cuaderno
from app.comun import guardar, obtener
from app.db import get_db
from app.deps import Sesion, requerir_permiso
from app.fechas import LIMA, hoy_lima
from app.models import (AdjuntoCuaderno, Alumno, CategoriaIncidencia, ColaAviso, AnioEscolar, AlumnoApoderado, Apoderado, DestinoCuaderno, EntradaCuaderno,
                        Grado, Matricula, MensajeCuaderno, Nivel, Seccion, SeccionDocente, Usuario)
from app.models.cuaderno import CON_RESOLUCION, TIPOS
from app.routers.importacion import _secciones
from app.validacion import sin_tildes

router = APIRouter(prefix="/cuaderno", tags=["cuaderno"])
MAX_DIAS_PROGRAMADO = 90
ver = requerir_permiso("cuaderno")
editar = requerir_permiso("cuaderno", "editar")
editar_padron = requerir_permiso("padron", "editar")


def _entrada(db: Session, s: Sesion, entrada_id: int) -> EntradaCuaderno:
    """La de otro colegio o de una sección que no le toca: 404, como si no existiera."""
    e = obtener(db, EntradaCuaderno, s.colegio.id, entrada_id, "Entrada")
    if not cuaderno.puede_ver(e, cuaderno.secciones_permitidas(db, s.usuario)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entrada no encontrada")
    return e


def _etiquetas_secciones(db: Session, cid: int) -> dict[int, str]:
    filas = db.execute(select(Seccion.id, Grado.nombre, Seccion.nombre, Nivel.nombre)
                       .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
                       .join(Nivel, and_(Nivel.colegio_id == Grado.colegio_id, Nivel.id == Grado.nivel_id))
                       .where(Seccion.colegio_id == cid))
    return {i: f"{g} {sn} · {n}" for i, g, sn, n in filas}


# --- Opciones para escribir ------------------------------------------------------------

@router.get("/opciones")
def opciones(s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    """Niveles, grados y secciones a los que puede escribir (el docente, solo sus secciones)."""
    cid = s.colegio.id
    permitidas = cuaderno.secciones_permitidas(db, s.usuario)
    a = db.scalar(select(AnioEscolar).where(AnioEscolar.colegio_id == cid, AnioEscolar.activo))
    secciones = []
    if a is not None:
        for sec, g, n in _secciones(db, cid, a.id):
            if permitidas is None or sec.id in permitidas:
                secciones.append({"id": sec.id, "nombre": f"{g} {sec.nombre}", "nivel": n, "grado_id": sec.grado_id})
    if permitidas is not None:
        return {"todo_el_colegio": False, "niveles": [], "grados": [], "secciones": secciones}
    niveles = db.execute(select(Nivel.id, Nivel.nombre).where(Nivel.colegio_id == cid).order_by(Nivel.orden)).all()
    grados = db.execute(select(Grado.id, Grado.nombre, Nivel.nombre)
                        .join(Nivel, and_(Nivel.colegio_id == Grado.colegio_id, Nivel.id == Grado.nivel_id))
                        .where(Grado.colegio_id == cid).order_by(Nivel.orden, Grado.orden, Grado.nombre)).all()
    return {"todo_el_colegio": True, "niveles": [{"id": i, "nombre": n} for i, n in niveles],
            "grados": [{"id": i, "nombre": f"{g} {n}"} for i, g, n in grados], "secciones": secciones}


@router.get("/alumnos")
def alumnos(q: str = "", seccion_id: int | None = None, s: Sesion = Depends(ver),
            db: Session = Depends(get_db)) -> list[dict]:
    """Para elegir a un alumno: por nombre o documento, o los de una sección."""
    cid = s.colegio.id
    permitidas = cuaderno.secciones_permitidas(db, s.usuario)
    consulta = (select(Alumno, Matricula.seccion_id)
                .outerjoin(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id, Matricula.alumno_id == Alumno.id,
                                           Matricula.anio_id == cuaderno.anio_activo_id(cid)))
                .where(Alumno.colegio_id == cid, Alumno.activo))
    if seccion_id is not None:
        consulta = consulta.where(Matricula.seccion_id == seccion_id)
    if permitidas is not None:
        consulta = consulta.where(Matricula.seccion_id.in_(permitidas))
    texto = sin_tildes(q.strip().lower())
    if texto:
        consulta = consulta.where(or_(
            func.translate(func.lower(Alumno.apellidos + " " + Alumno.nombres), "áéíóúüñ", "aeiouun").contains(texto),
            Alumno.numero_documento.contains(texto.upper())))
    elif seccion_id is None:
        return []
    etiquetas = _etiquetas_secciones(db, cid)
    filas = db.execute(consulta.order_by(Alumno.apellidos, Alumno.nombres).limit(100))
    return [{"id": a.id, "nombre": f"{a.apellidos}, {a.nombres}", "seccion": etiquetas.get(sid)} for a, sid in filas]


# --- Escribir ---------------------------------------------------------------------------

class EntradaIn(BaseModel):
    tipo: Literal["comunicado", "incidencia", "citacion", "justificacion", "permiso_salida"]
    alcance: Literal["colegio", "nivel", "grado", "seccion", "alumno"] = "alumno"
    nivel_id: int | None = None
    grado_id: int | None = None
    seccion_id: int | None = None
    alumno_id: int | None = None
    titulo: str = Field(min_length=1, max_length=200)
    cuerpo: str = Field(default="", max_length=10000)
    pide_firma: bool = False
    cita_en: datetime | None = None
    lugar: str | None = Field(default=None, max_length=120)
    desde: date | None = None
    hasta: date | None = None
    hora_salida: time | None = None
    recoge: str | None = Field(default=None, max_length=120)
    categoria_id: int | None = None  # incidencia
    programado_para: datetime | None = None  # comunicado: fecha y hora de envío

    @model_validator(mode="after")
    def _segun_tipo(self):
        if self.programado_para is not None:
            if self.tipo != "comunicado":
                raise ValueError("Solo los comunicados se programan")
            if self.programado_para.tzinfo is None:
                raise ValueError("Falta la zona horaria de la hora de envío")
            ahora = datetime.now(UTC)
            if self.programado_para <= ahora + timedelta(minutes=1):
                self.programado_para = None  # para ya mismo: sale ahora
            elif self.programado_para > ahora + timedelta(days=MAX_DIAS_PROGRAMADO):
                raise ValueError(f"Se programa hasta {MAX_DIAS_PROGRAMADO} días adelante")
        if self.tipo != "incidencia":
            self.categoria_id = None
        if self.tipo != "comunicado" and self.alcance != "alumno":
            raise ValueError("Solo los comunicados van a más de un alumno")
        if self.tipo == "citacion" and self.cita_en is None:
            raise ValueError("Indica la fecha y hora de la citación")
        if self.tipo == "justificacion":
            if self.desde is None:
                raise ValueError("Indica desde qué día justifica")
            self.hasta = self.hasta or self.desde
            if self.hasta < self.desde:
                raise ValueError("La fecha final es anterior a la inicial")
        if self.tipo == "permiso_salida" and (self.desde is None or self.hora_salida is None):
            raise ValueError("Indica el día y la hora de salida")
        return self


def crear_entrada(db: Session, cid: int, d: EntradaIn, destino: cuaderno.Destino, *, usuario_id: int | None = None,
                  apoderado_id: int | None = None, estado: str | None = None) -> EntradaCuaderno:
    e = EntradaCuaderno(
        colegio_id=cid, tipo=d.tipo, alcance=destino.alcance, nivel_id=destino.nivel_id, grado_id=destino.grado_id,
        seccion_id=destino.seccion_id, alumno_id=destino.alumno_id, titulo=d.titulo.strip(), cuerpo=d.cuerpo.strip(),
        pide_firma=d.pide_firma and d.tipo == "comunicado",
        cita_en=cuaderno.a_lima(d.cita_en) if d.cita_en and d.tipo == "citacion" else None,
        lugar=d.lugar if d.tipo == "citacion" else None,
        desde=d.desde if d.tipo in CON_RESOLUCION else None, hasta=d.hasta if d.tipo == "justificacion" else None,
        hora_salida=d.hora_salida if d.tipo == "permiso_salida" else None,
        recoge=d.recoge if d.tipo == "permiso_salida" else None,
        categoria_id=d.categoria_id if d.tipo == "incidencia" else None,
        programado_para=d.programado_para if d.tipo == "comunicado" else None,
        estado=(estado or "pendiente") if d.tipo in CON_RESOLUCION else None,
        creado_por_id=usuario_id, apoderado_autor_id=apoderado_id)
    db.add(e)
    db.flush()
    return e


def _leer_datos(datos: str) -> EntradaIn:
    try:
        return EntradaIn.model_validate_json(datos)
    except ValidationError as err:
        primero = err.errors()[0]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            str(primero.get("ctx", {}).get("error") or primero["msg"]).removeprefix("Value error, ")
                            ) from None


@router.post("/entradas", status_code=201)
async def escribir(datos: str = Form(...), archivos: list[UploadFile] | None = File(None),
                   s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Formulario con `datos` (JSON de EntradaIn) y hasta 5 `archivos`. Lo que registra el colegio
    (una justificación que trajo el padre en papel, un permiso de salida) ya queda aprobado."""
    d = _leer_datos(datos)
    cid = s.colegio.id
    destino = cuaderno.validar_destino(db, cid, cuaderno.Destino(d.alcance, d.nivel_id, d.grado_id, d.seccion_id,
                                                                 d.alumno_id),
                                       cuaderno.secciones_permitidas(db, s.usuario))
    alumnos_ids = cuaderno.alumnos_del_destino(db, cid, destino)
    if not alumnos_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No hay alumnos en ese destino")
    if d.tipo == "incidencia":
        _validar_categoria(db, cid, d)
    adjuntos = await cuaderno.leer_adjuntos(archivos)
    e = crear_entrada(db, cid, d, destino, usuario_id=s.usuario.id, estado="aprobada")
    if e.estado == "aprobada":
        e.resuelto_por_id, e.resuelto_en = s.usuario.id, datetime.now(UTC)
        if e.tipo == "justificacion":
            cuaderno.aplicar_justificacion(db, e)
    apoderados = cuaderno.guardar_destinos(db, e, alumnos_ids)
    avisados = cuaderno.avisar(db, e, apoderados, cuaderno.texto_aviso(db, e))
    claves = cuaderno.guardar_adjuntos(db, e, adjuntos)
    configuracion.registrar(db, cid, s.usuario, "crear", "cuaderno", e.tipo, e.id, resumen_entrada(db, e))
    try:
        guardar(db)
    except Exception:
        cuaderno.borrar_archivos(claves)
        raise
    return {"id": e.id, "alumnos": len(alumnos_ids), "apoderados": len(apoderados), "avisados": avisados,
            "programado_para": cuaderno.iso(e.programado_para)}


def _validar_categoria(db: Session, cid: int, d: EntradaIn) -> None:
    """Si el colegio tiene categorías, la incidencia lleva una suya y activa."""
    activas = set(db.scalars(select(CategoriaIncidencia.id).where(CategoriaIncidencia.colegio_id == cid,
                                                                 CategoriaIncidencia.activa)))
    if d.categoria_id is None:
        if activas:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Elige la categoría de la incidencia")
    elif d.categoria_id not in activas:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Categoría no válida")


NOMBRE_TIPO = {"comunicado": "Comunicado", "incidencia": "Incidencia", "citacion": "Citación",
               "justificacion": "Justificación", "permiso_salida": "Permiso de salida"}


def resumen_entrada(db: Session, e: EntradaCuaderno) -> str:
    """Para el historial. El comunicado dice su asunto; lo que es de un alumno solo dice de quién (el texto de
    una justificación o una incidencia puede ser de salud o de conducta: no va al historial)."""
    if e.tipo == "comunicado":
        extra = f" (programado para {e.programado_para.astimezone(LIMA):%d/%m %H:%M})" if e.programado_para else ""
        return f"Comunicado «{e.titulo}»{extra}"
    alumno = db.scalar(select(Alumno.apellidos + ", " + Alumno.nombres).where(
        Alumno.colegio_id == e.colegio_id, Alumno.id == e.alumno_id))
    categoria = db.scalar(select(CategoriaIncidencia.nombre).where(
        CategoriaIncidencia.colegio_id == e.colegio_id, CategoriaIncidencia.id == e.categoria_id)) \
        if e.categoria_id else None
    return f"{NOMBRE_TIPO[e.tipo]}{f' ({categoria})' if categoria else ''} de {alumno or 'un alumno'}"


@router.post("/entradas/{entrada_id}/cancelar")
def cancelar_programado(entrada_id: int, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Un comunicado programado que aún no salió se cancela: desaparece con sus avisos en espera."""
    e = _entrada(db, s, entrada_id)
    if e.programado_para is None or e.programado_para <= datetime.now(UTC):
        raise HTTPException(status.HTTP_409_CONFLICT, "Solo se cancela un comunicado programado que aún no sale")
    cid = s.colegio.id
    configuracion.registrar(db, cid, s.usuario, "anular", "cuaderno", "comunicado", e.id,
                            f"Canceló el comunicado programado «{e.titulo}»")
    db.execute(delete(ColaAviso).where(ColaAviso.colegio_id == cid, ColaAviso.tipo == "cuaderno",
                                       ColaAviso.estado == "pendiente",
                                       ColaAviso.datos["entrada_id"].as_integer() == e.id))
    claves = list(db.scalars(select(AdjuntoCuaderno.clave).where(AdjuntoCuaderno.colegio_id == cid,
                                                                 AdjuntoCuaderno.entrada_id == e.id)))
    db.delete(e)
    guardar(db)
    cuaderno.borrar_archivos(claves)
    return {"id": entrada_id, "cancelado": True}


# --- Leer ------------------------------------------------------------------------------

def _destino_texto(e: EntradaCuaderno, etiquetas: dict[int, str], nombres: dict, alumnos: dict) -> str:
    if e.alcance == "colegio":
        return "Todo el colegio"
    if e.alcance == "nivel":
        return nombres["nivel"].get(e.nivel_id, "Nivel")
    if e.alcance == "grado":
        return nombres["grado"].get(e.grado_id, "Grado")
    if e.alcance == "seccion":
        return etiquetas.get(e.seccion_id, "Sección")
    return alumnos.get(e.alumno_id, "Alumno") + (f" · {etiquetas[e.seccion_id]}" if e.seccion_id in etiquetas else "")


def _nombres(db: Session, cid: int, alumno_ids) -> tuple[dict, dict]:
    nombres = {
        "nivel": dict(db.execute(select(Nivel.id, Nivel.nombre).where(Nivel.colegio_id == cid)).all()),
        "grado": {i: f"{g} {n}" for i, g, n in db.execute(
            select(Grado.id, Grado.nombre, Nivel.nombre)
            .join(Nivel, and_(Nivel.colegio_id == Grado.colegio_id, Nivel.id == Grado.nivel_id))
            .where(Grado.colegio_id == cid))},
    }
    alumnos = {i: f"{ap}, {no}" for i, ap, no in db.execute(
        select(Alumno.id, Alumno.apellidos, Alumno.nombres)
        .where(Alumno.colegio_id == cid, Alumno.id.in_(set(alumno_ids))))} if alumno_ids else {}
    return nombres, alumnos


@router.get("/entradas")
def listar(tipo: str | None = None, estado: str | None = None, seccion_id: int | None = None,
           alumno_id: int | None = None, pendientes: bool = False, antes_de: int | None = None,
           s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> list[dict]:
    """Lo último primero, de a 50 (`antes_de` = id de la última que ya se vio). `pendientes`: lo
    que espera al colegio (por aprobar, o con la última respuesta de la familia)."""
    cid = s.colegio.id
    permitidas = cuaderno.secciones_permitidas(db, s.usuario)
    q = select(EntradaCuaderno).where(EntradaCuaderno.colegio_id == cid)
    if tipo in TIPOS:
        q = q.where(EntradaCuaderno.tipo == tipo)
    if estado:
        q = q.where(EntradaCuaderno.estado == estado)
    if seccion_id is not None:
        q = q.where(EntradaCuaderno.seccion_id == seccion_id)
    if alumno_id is not None:
        q = q.where(EntradaCuaderno.id.in_(select(DestinoCuaderno.entrada_id).where(
            DestinoCuaderno.colegio_id == cid, DestinoCuaderno.alumno_id == alumno_id)))
    if permitidas is not None:
        q = q.where(EntradaCuaderno.seccion_id.in_(permitidas))
    if antes_de is not None:
        q = q.where(EntradaCuaderno.id < antes_de)
    ultimo = (select(MensajeCuaderno.de_familia).where(MensajeCuaderno.colegio_id == cid,
                                                       MensajeCuaderno.entrada_id == EntradaCuaderno.id)
              .order_by(MensajeCuaderno.id.desc()).limit(1).scalar_subquery())
    if pendientes:
        q = q.where(or_(EntradaCuaderno.estado == "pendiente", ultimo.is_(True)))
    entradas = db.scalars(q.order_by(EntradaCuaderno.id.desc()).limit(50)).all()
    ids = [e.id for e in entradas]
    conteos = {}
    if ids:
        apo = DestinoCuaderno.apoderado_id
        for eid, total, vistos, firmados in db.execute(
                select(DestinoCuaderno.entrada_id, func.count(apo.distinct()),
                       func.count(case((DestinoCuaderno.visto_en.is_not(None), apo)).distinct()),
                       func.count(case((DestinoCuaderno.firmado_en.is_not(None), apo)).distinct()))
                .where(DestinoCuaderno.colegio_id == cid, DestinoCuaderno.entrada_id.in_(ids))
                .group_by(DestinoCuaderno.entrada_id)):
            conteos[eid] = (total, vistos, firmados)
    mensajes = {}
    if ids:
        cuantos = dict(db.execute(select(MensajeCuaderno.entrada_id, func.count())
                                  .where(MensajeCuaderno.colegio_id == cid, MensajeCuaderno.entrada_id.in_(ids))
                                  .group_by(MensajeCuaderno.entrada_id)).all())
        ultimos = dict(db.execute(select(MensajeCuaderno.entrada_id, MensajeCuaderno.de_familia)
                                  .where(MensajeCuaderno.colegio_id == cid, MensajeCuaderno.entrada_id.in_(ids))
                                  .distinct(MensajeCuaderno.entrada_id)
                                  .order_by(MensajeCuaderno.entrada_id, MensajeCuaderno.id.desc())).all())
        mensajes = {eid: (n, ultimos.get(eid, False)) for eid, n in cuantos.items()}
    etiquetas = _etiquetas_secciones(db, cid)
    nombres, alumnos_n = _nombres(db, cid, [e.alumno_id for e in entradas if e.alumno_id])
    adjuntos = cuaderno.adjuntos_de(db, cid, ids)
    categorias = cuaderno.categorias_de(db, cid)
    salida = []
    for e in entradas:
        total, vistos, firmados = conteos.get(e.id, (0, 0, 0))
        n, ult_familia = mensajes.get(e.id, (0, False))
        salida.append({**cuaderno.entrada_basica(e, categorias), "destino": _destino_texto(e, etiquetas, nombres, alumnos_n),
                       "apoderados": total, "vistos": vistos, "firmados": firmados, "respuestas": n,
                       "espera_al_colegio": e.estado == "pendiente" or ult_familia,
                       "adjuntos": len(adjuntos.get(e.id, []))})
    return salida


@router.get("/entradas/{entrada_id}")
def detalle(entrada_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    """La entrada, sus adjuntos, el hilo y quién leyó o firmó (y quién no)."""
    cid = s.colegio.id
    e = _entrada(db, s, entrada_id)
    personal = dict(db.execute(select(Usuario.id, Usuario.nombres + " " + Usuario.apellidos)
                               .where(Usuario.colegio_id == cid)).all())
    filas = db.execute(
        select(DestinoCuaderno, Alumno.apellidos, Alumno.nombres, Apoderado, AlumnoApoderado.parentesco)
        .join(Alumno, and_(Alumno.colegio_id == DestinoCuaderno.colegio_id, Alumno.id == DestinoCuaderno.alumno_id))
        .join(Apoderado, and_(Apoderado.colegio_id == DestinoCuaderno.colegio_id,
                              Apoderado.id == DestinoCuaderno.apoderado_id))
        .outerjoin(AlumnoApoderado, and_(AlumnoApoderado.colegio_id == DestinoCuaderno.colegio_id,
                                         AlumnoApoderado.alumno_id == DestinoCuaderno.alumno_id,
                                         AlumnoApoderado.apoderado_id == DestinoCuaderno.apoderado_id))
        .where(DestinoCuaderno.colegio_id == cid, DestinoCuaderno.entrada_id == e.id)
        .order_by(Alumno.apellidos, Alumno.nombres, Apoderado.apellidos)).all()
    apoderados = {ap.id: ap for _, _, _, ap, _ in filas}
    mensajes = db.scalars(select(MensajeCuaderno).where(MensajeCuaderno.colegio_id == cid,
                                                        MensajeCuaderno.entrada_id == e.id)
                          .order_by(MensajeCuaderno.id))
    etiquetas = _etiquetas_secciones(db, cid)
    nombres, alumnos_n = _nombres(db, cid, [e.alumno_id] if e.alumno_id else [])
    autor = (personal.get(e.creado_por_id) if e.creado_por_id
             else (f"{a.nombres} {a.apellidos}" if (a := db.get(Apoderado, e.apoderado_autor_id)) else None)
             if e.apoderado_autor_id else None)
    return {
        **cuaderno.entrada_basica(e, cuaderno.categorias_de(db, cid)),
        "destino": _destino_texto(e, etiquetas, nombres, alumnos_n), "autor": autor, "resuelto_por": personal.get(e.resuelto_por_id),
        "anulada_por": personal.get(e.anulada_por_id), "anulada_en": cuaderno.iso(e.anulada_en),
        "adjuntos": cuaderno.adjuntos_de(db, cid, [e.id]).get(e.id, []),
        "lectores": [{
            "alumno": f"{aa}, {an}", "apoderado": f"{ap.apellidos}, {ap.nombres}", "parentesco": par,
            "con_app": ap.estado_acceso == "activo", "visto_en": cuaderno.iso(d.visto_en),
            "firmado_en": cuaderno.iso(d.firmado_en)} for d, aa, an, ap, par in filas],
        "mensajes": [{
            "id": m.id, "cuerpo": m.cuerpo, "creado_en": cuaderno.iso(m.creado_en), "de_familia": m.de_familia,
            "autor": (f"{apo.nombres} {apo.apellidos}" if (apo := apoderados.get(m.apoderado_id))
                      else "Apoderado") if m.de_familia else personal.get(m.usuario_id, "Colegio")}
            for m in mensajes],
    }


class RespuestaIn(BaseModel):
    cuerpo: str = Field(min_length=1, max_length=4000)


@router.post("/entradas/{entrada_id}/respuestas", status_code=201)
def responder(entrada_id: int, d: RespuestaIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    e = _entrada(db, s, entrada_id)
    m = MensajeCuaderno(colegio_id=s.colegio.id, entrada_id=e.id, usuario_id=s.usuario.id, de_familia=False,
                        cuerpo=d.cuerpo.strip())
    db.add(m)
    cuaderno.avisar(db, e, cuaderno.apoderados_de(db, e), cuaderno.texto_aviso(db, e, "respuesta"))
    guardar(db)
    return {"id": m.id}


class ResolucionIn(BaseModel):
    estado: Literal["aprobada", "rechazada"]
    nota: str | None = Field(default=None, max_length=300)


@router.post("/entradas/{entrada_id}/resolver")
def resolver(entrada_id: int, d: ResolucionIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Aprobar o rechazar una justificación o un permiso de salida que pidió el padre."""
    e = _entrada(db, s, entrada_id)
    if e.tipo not in CON_RESOLUCION:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Solo se aprueban justificaciones y permisos de salida")
    if e.estado != "pendiente":
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya fue resuelta")
    e.estado, e.nota_resolucion = d.estado, (d.nota or "").strip() or None
    e.resuelto_por_id, e.resuelto_en = s.usuario.id, datetime.now(UTC)
    faltas = 0
    if e.tipo == "justificacion" and e.estado == "aprobada":
        faltas = cuaderno.aplicar_justificacion(db, e)
    cuaderno.avisar(db, e, cuaderno.apoderados_de(db, e), cuaderno.texto_aviso(db, e, "resuelta"))
    configuracion.registrar(db, s.colegio.id, s.usuario, "editar", "cuaderno", e.tipo, e.id,
                            f"{'Aprobó' if e.estado == 'aprobada' else 'Rechazó'}: {resumen_entrada(db, e)}")
    guardar(db)
    return {"id": e.id, "estado": e.estado, "faltas_justificadas": faltas}


class AnulacionIn(BaseModel):
    motivo: str = Field(min_length=1, max_length=300)


@router.post("/entradas/{entrada_id}/anular")
def anular(entrada_id: int, d: AnulacionIn, s: Sesion = Depends(editar), db: Session = Depends(get_db)) -> dict:
    """Deja sin efecto una justificación o un permiso ya aprobados (p. ej. el certificado era falso).
    Las faltas que había justificado vuelven a ser faltas."""
    e = _entrada(db, s, entrada_id)
    if e.tipo not in CON_RESOLUCION or e.estado != "aprobada":
        raise HTTPException(status.HTTP_409_CONFLICT, "Solo se anula una justificación o un permiso aprobado")
    e.estado, e.motivo_anulacion = "anulada", d.motivo.strip()
    e.anulada_por_id, e.anulada_en = s.usuario.id, datetime.now(UTC)
    db.flush()
    faltas = cuaderno.quitar_justificacion(db, e) if e.tipo == "justificacion" else 0
    cuaderno.avisar(db, e, cuaderno.apoderados_de(db, e), cuaderno.texto_aviso(db, e, "resuelta"))
    configuracion.registrar(db, s.colegio.id, s.usuario, "anular", "cuaderno", e.tipo, e.id,
                            f"Anuló: {resumen_entrada(db, e)}")
    guardar(db)
    return {"id": e.id, "estado": e.estado, "faltas_restituidas": faltas}


@router.get("/adjuntos/{adjunto_id}")
def adjunto(adjunto_id: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)):
    adj = obtener(db, AdjuntoCuaderno, s.colegio.id, adjunto_id, "Archivo")
    _entrada(db, s, adj.entrada_id)  # el docente, solo los de sus secciones
    return cuaderno.respuesta_adjunto(adj)


# --- Secciones a cargo de cada docente ----------------------------------------------------

@router.get("/docentes")
def docentes(s: Sesion = Depends(editar_padron), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    a = db.scalar(select(AnioEscolar).where(AnioEscolar.colegio_id == cid, AnioEscolar.activo))
    asignados: dict[int, list[int]] = {}
    for sec_id, u_id in db.execute(select(SeccionDocente.seccion_id, SeccionDocente.usuario_id)
                                   .where(SeccionDocente.colegio_id == cid)):
        asignados.setdefault(sec_id, []).append(u_id)
    personal = db.execute(select(Usuario.id, Usuario.apellidos, Usuario.nombres)
                          .where(Usuario.colegio_id == cid, Usuario.activo).order_by(Usuario.apellidos)).all()
    return {
        "secciones": [{"id": sec.id, "nombre": f"{g} {sec.nombre} · {n}", "docentes": asignados.get(sec.id, [])}
                      for sec, g, n in (_secciones(db, cid, a.id) if a else [])],
        "personal": [{"id": i, "nombre": f"{ap}, {no}"} for i, ap, no in personal],
    }


class DocentesIn(BaseModel):
    usuario_ids: list[int] = Field(max_length=50)


@router.put("/secciones/{seccion_id}/docentes")
def asignar_docentes(seccion_id: int, d: DocentesIn, s: Sesion = Depends(editar_padron),
                     db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    sec = obtener(db, Seccion, cid, seccion_id, "Sección")
    ids = set(d.usuario_ids)
    validos = set(db.scalars(select(Usuario.id).where(Usuario.colegio_id == cid, Usuario.id.in_(ids))))
    if ids - validos:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Hay personas que no son de este colegio")
    db.execute(delete(SeccionDocente).where(SeccionDocente.colegio_id == cid, SeccionDocente.seccion_id == sec.id))
    db.add_all([SeccionDocente(colegio_id=cid, seccion_id=sec.id, usuario_id=u) for u in sorted(ids)])
    configuracion.registrar(db, cid, s.usuario, "editar", "padron", "seccion", sec.id,
                            f"Docentes a cargo de la sección {sec.nombre}: {len(ids)}")
    guardar(db)
    return {"id": sec.id, "docentes": sorted(ids)}


# --- Portería ----------------------------------------------------------------------------

def permisos_salida(db: Session, colegio_id: int, fecha: date | None = None) -> dict[int, dict]:
    """Permisos de salida del día por alumno (aprobados o por aprobar), para la portería."""
    fecha = fecha or hoy_lima()
    salida: dict[int, dict] = {}
    for e in db.scalars(select(EntradaCuaderno).where(
            EntradaCuaderno.colegio_id == colegio_id, EntradaCuaderno.tipo == "permiso_salida",
            EntradaCuaderno.desde == fecha, EntradaCuaderno.estado.in_(("aprobada", "pendiente")))
            .order_by(EntradaCuaderno.id)):
        actual = salida.get(e.alumno_id)
        if actual is None or actual["estado"] != "aprobada" or e.estado == "aprobada":
            salida[e.alumno_id] = {"hora": e.hora_salida.strftime("%H:%M"), "recoge": e.recoge,
                                   "motivo": e.titulo, "estado": e.estado}
    return salida
