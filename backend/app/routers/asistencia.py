"""Asistencia: receptor único de marcaciones, padrón para la portería sin
internet, reportes del día y del mes, licencias del personal y reglas."""

import calendar
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app import asistencia
from app.comun import guardar, obtener
from app.db import get_db
from app.deps import Sesion, requerir_permiso, tiene_permiso
from app.fechas import hoy_lima
from app.models import (Alumno, AnioEscolar, AsistenciaAlumno, AsistenciaPersonal, ConfigAsistencia,
                        LicenciaPersonal, Marcacion, Matricula, Rol, Seccion, Turno, Usuario)
from app.models.asistencia import TIPOS_LICENCIA
from app.routers.estructura import anio_activo, es_dia_lectivo
from app.routers.importacion import XLSX, _secciones

router = APIRouter(prefix="/asistencia", tags=["asistencia"])
ver = requerir_permiso("asistencia")
marcar = requerir_permiso("asistencia", "editar")
editar_licencias = requerir_permiso("personal", "editar")
editar_reglas = requerir_permiso("configuracion", "editar")


# --- Marcaciones -----------------------------------------------------------------

class MarcaIn(BaseModel):
    # Lo genera el dispositivo (uuid). Un reenvío con el mismo id no duplica.
    id_cliente: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    momento: datetime | None = None  # sin hora: ahora (marcación en línea)
    codigo: str | None = Field(default=None, max_length=40)  # lo que leyó el QR o el lector
    alumno_id: int | None = None  # marcación manual, sin carnet
    usuario_id: int | None = None
    origen: Literal["qr", "equipo"] = "qr"
    equipo: str | None = Field(default=None, max_length=60)

    @model_validator(mode="after")
    def _una_persona(self):
        if sum(x is not None for x in (self.codigo, self.alumno_id, self.usuario_id)) != 1:
            raise ValueError("Indica el código del carnet, o el alumno o la persona del personal")
        return self


class LoteIn(BaseModel):
    marcaciones: list[MarcaIn] = Field(min_length=1, max_length=500)


@router.post("/marcaciones")
def recibir(datos: LoteIn, s: Sesion = Depends(marcar), db: Session = Depends(get_db)) -> dict:
    """Receptor único: portería (QR o lector USB), marcación manual y, en la fase 2, los equipos.
    Solo guarda y responde; los avisos quedan en la cola. Cada marcación se confirma por separado,
    así un lote que llega de una portería sin internet no se pierde entero por una mala."""
    resultados = []
    for m in datos.marcaciones:
        lectura = asistencia.Lectura(
            id_cliente=m.id_cliente, momento=m.momento or datetime.now(UTC),
            origen="manual" if m.codigo is None else m.origen,
            codigo=m.codigo, alumno_id=m.alumno_id, usuario_id=m.usuario_id, equipo=m.equipo)
        try:
            resultados.append(asistencia.registrar(db, s.colegio.id, lectura, s.usuario.id))
            db.commit()
        except Exception:
            db.rollback()
            asistencia.log.exception("Marcación %s", m.id_cliente)
            resultados.append({"id_cliente": m.id_cliente, "estado": "error",
                               "mensaje": "No se pudo guardar; se reintentará"})
    return {"resultados": resultados}


@router.get("/marcaciones")
def marcaciones(fecha: date | None = None, limite: int = 100, s: Sesion = Depends(ver),
                db: Session = Depends(get_db)) -> list[dict]:
    cid, fecha = s.colegio.id, fecha or hoy_lima()
    filas = db.execute(
        select(Marcacion, Alumno.apellidos, Alumno.nombres, Usuario.apellidos, Usuario.nombres)
        .select_from(Marcacion)
        .outerjoin(Alumno, and_(Alumno.colegio_id == Marcacion.colegio_id, Alumno.id == Marcacion.alumno_id))
        .outerjoin(Usuario, and_(Usuario.colegio_id == Marcacion.colegio_id, Usuario.id == Marcacion.usuario_id))
        .where(Marcacion.colegio_id == cid, Marcacion.fecha == fecha)
        .order_by(Marcacion.momento.desc()).limit(min(max(limite, 1), 500)))
    return [{"id": m.id, "hora": asistencia.hora(m.momento), "resultado": m.resultado, "origen": m.origen,
             "equipo": m.equipo, "tipo": "alumno" if m.alumno_id else "personal",
             "registrada_despues": m.recibido_en - m.momento > asistencia.REGISTRO_TARDIO,
             "nombre": f"{aa or ua}, {an or un}"} for m, aa, an, ua, un in filas]


@router.get("/porteria")
def porteria(s: Sesion = Depends(marcar), db: Session = Depends(get_db)) -> dict:
    """Lo que la portería guarda en el celular para seguir marcando sin internet: códigos,
    nombres, sección y turnos. Sin DNI ni datos de los apoderados."""
    cid = s.colegio.id
    anio = db.scalar(select(AnioEscolar.id).where(AnioEscolar.colegio_id == cid, AnioEscolar.activo))
    etiquetas = {sec.id: (f"{g} {sec.nombre}", sec.turno_id) for sec, g, _ in _secciones(db, cid, anio)} if anio else {}
    alumnos = db.execute(
        select(Alumno.id, Alumno.codigo, Alumno.apellidos, Alumno.nombres, Matricula.seccion_id)
        .outerjoin(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id, Matricula.alumno_id == Alumno.id,
                                   Matricula.anio_id == anio))
        .where(Alumno.colegio_id == cid, Alumno.activo).order_by(Alumno.apellidos, Alumno.nombres))
    personal = db.execute(select(Usuario.id, Usuario.codigo, Usuario.apellidos, Usuario.nombres, Usuario.turno_id)
                          .where(Usuario.colegio_id == cid, Usuario.activo).order_by(Usuario.apellidos))
    turnos = db.scalars(select(Turno).where(Turno.colegio_id == cid).order_by(Turno.hora_entrada))
    return {
        "generado_en": datetime.now(UTC).isoformat(),
        "minutos_duplicado": asistencia.config(db, cid).minutos_duplicado,
        "turnos": [{"id": t.id, "nombre": t.nombre, "hora_entrada": t.hora_entrada.strftime("%H:%M"),
                    "tolerancia_minutos": t.tolerancia_minutos} for t in turnos],
        "alumnos": [{"id": i, "codigo": c, "nombre": f"{ap}, {no}",
                     "seccion": etiquetas.get(sid, ("", None))[0], "turno_id": etiquetas.get(sid, ("", None))[1]}
                    for i, c, ap, no, sid in alumnos],
        "personal": [{"id": i, "codigo": c, "nombre": f"{ap}, {no}", "turno_id": t}
                     for i, c, ap, no, t in personal],
    }


# --- Reportes de alumnos -----------------------------------------------------------

def _estados_vacios() -> dict:
    return {"total": 0, "presente": 0, "tarde": 0, "falta": 0, "sin_registro": 0}


@router.get("/dia")
def dia(fecha: date | None = None, seccion_id: int | None = None, s: Sesion = Depends(ver),
        db: Session = Depends(get_db)) -> dict:
    """Resumen del día por sección; con `seccion_id`, la lista de alumnos de esa sección."""
    cid, fecha = s.colegio.id, fecha or hoy_lima()
    anio = anio_activo(db, cid)
    tardia = asistencia.registrada_despues(cid, fecha, alumno_id=Alumno.id)
    base = (select(Matricula.seccion_id, Alumno, AsistenciaAlumno, tardia)
            .join(Alumno, and_(Alumno.colegio_id == Matricula.colegio_id, Alumno.id == Matricula.alumno_id))
            .outerjoin(AsistenciaAlumno, and_(AsistenciaAlumno.colegio_id == Matricula.colegio_id,
                                              AsistenciaAlumno.alumno_id == Matricula.alumno_id,
                                              AsistenciaAlumno.fecha == fecha))
            .where(Matricula.colegio_id == cid, Matricula.anio_id == anio.id, Alumno.activo))
    salida: dict = {"fecha": fecha.isoformat(), "lectivo": es_dia_lectivo(db, cid, fecha)}
    if seccion_id is not None:
        obtener(db, Seccion, cid, seccion_id, "Sección")
        filas = db.execute(base.where(Matricula.seccion_id == seccion_id).order_by(Alumno.apellidos, Alumno.nombres))
        salida["alumnos"] = [{
            "alumno_id": a.id, "nombre": f"{a.apellidos}, {a.nombres}", "estado": f.estado if f else None,
            "entrada": asistencia.hora(f.entrada) if f else None, "salida": asistencia.hora(f.salida) if f else None,
            "minutos_tarde": f.minutos_tarde if f else 0, "registrada_despues": tardia,
        } for _, a, f, tardia in filas]
        return salida
    por_seccion: dict[int, dict] = {}
    for sid, estado, n in db.execute(
            select(Matricula.seccion_id, AsistenciaAlumno.estado, func.count())
            .join(Alumno, and_(Alumno.colegio_id == Matricula.colegio_id, Alumno.id == Matricula.alumno_id))
            .outerjoin(AsistenciaAlumno, and_(AsistenciaAlumno.colegio_id == Matricula.colegio_id,
                                              AsistenciaAlumno.alumno_id == Matricula.alumno_id,
                                              AsistenciaAlumno.fecha == fecha))
            .where(Matricula.colegio_id == cid, Matricula.anio_id == anio.id, Alumno.activo)
            .group_by(Matricula.seccion_id, AsistenciaAlumno.estado)):
        c = por_seccion.setdefault(sid, _estados_vacios())
        c[estado or "sin_registro"] += n
        c["total"] += n
    totales = _estados_vacios()
    secciones = []
    for sec, g, n in _secciones(db, cid, anio.id):
        c = por_seccion.get(sec.id, _estados_vacios())
        secciones.append({"id": sec.id, "nombre": f"{n} · {g} {sec.nombre}", **c})
        for k in totales:
            totales[k] += c[k]
    return {**salida, "totales": totales, "secciones": secciones}


def _dias(db: Session, cid: int, anio: int, mes: int) -> list[date]:
    if not 1 <= mes <= 12 or not 2000 <= anio <= 2100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Mes no válido")
    ultimo = calendar.monthrange(anio, mes)[1]
    return [d for d in (date(anio, mes, i) for i in range(1, ultimo + 1)) if es_dia_lectivo(db, cid, d)]


LETRA = {"presente": "P", "tarde": "T", "falta": "F", "licencia": "L"}
RELLENO = {"T": PatternFill("solid", fgColor="FFF2CC"), "F": PatternFill("solid", fgColor="F8CBAD"),
           "L": PatternFill("solid", fgColor="DDEBF7")}


def _hoja(ws, titulo: str, dias: list[date], filas: list[tuple[str, dict[date, str]]], letras: str) -> None:
    """Una fila por persona, una columna por día lectivo y los totales al final."""
    ws.append([titulo])
    ws["A1"].font = Font(bold=True, size=12)
    nombres_total = {"P": "Asistió", "T": "Tardanzas", "F": "Faltas", "L": "Licencia"}
    ws.append(["Apellidos y nombres", *[d.day for d in dias], *[nombres_total[x] for x in letras]])
    for celda in ws[2]:
        celda.font = Font(bold=True)
        celda.alignment = Alignment(horizontal="center")
    for nombre, estados in filas:
        valores = [estados.get(d, "") for d in dias]
        ws.append([nombre, *valores, *[(valores.count("P") + valores.count("T")) if x == "P" else valores.count(x)
                                       for x in letras]])
        for celda in ws[ws.max_row][1:len(dias) + 1]:
            celda.alignment = Alignment(horizontal="center")
            if celda.value in RELLENO:
                celda.fill = RELLENO[celda.value]
    ws.column_dimensions["A"].width = 38
    ws.freeze_panes = "B3"


def _excel(wb: Workbook, nombre: str) -> Response:
    buf = BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.get("/mensual.xlsx")
def mensual(anio: int, mes: int, seccion_id: int | None = None, s: Sesion = Depends(ver),
            db: Session = Depends(get_db)) -> Response:
    """Registro del mes: una hoja por sección (o solo la pedida)."""
    cid = s.colegio.id
    dias = _dias(db, cid, anio, mes)
    activo = anio_activo(db, cid)
    secciones = _secciones(db, cid, activo.id)
    if seccion_id is not None:
        obtener(db, Seccion, cid, seccion_id, "Sección")
        secciones = [x for x in secciones if x[0].id == seccion_id]
    estados: dict[int, dict[date, str]] = {}
    if dias:
        for alumno_id, fecha, estado in db.execute(
                select(AsistenciaAlumno.alumno_id, AsistenciaAlumno.fecha, AsistenciaAlumno.estado)
                .where(AsistenciaAlumno.colegio_id == cid, AsistenciaAlumno.fecha.between(dias[0], dias[-1]))):
            estados.setdefault(alumno_id, {})[fecha] = LETRA[estado]
    alumnos: dict[int, list] = {}
    for sid, a in db.execute(
            select(Matricula.seccion_id, Alumno)
            .join(Alumno, and_(Alumno.colegio_id == Matricula.colegio_id, Alumno.id == Matricula.alumno_id))
            .where(Matricula.colegio_id == cid, Matricula.anio_id == activo.id, Alumno.activo)
            .order_by(Alumno.apellidos, Alumno.nombres)):
        alumnos.setdefault(sid, []).append(a)

    wb = Workbook()
    wb.remove(wb.active)
    for sec, g, n in secciones:
        ws = wb.create_sheet(f"{g} {sec.nombre}"[:31].replace("/", "-"))
        _hoja(ws, f"{s.colegio.nombre} · {n} {g} {sec.nombre} · {mes:02d}/{anio}", dias,
              [(f"{a.apellidos}, {a.nombres}", estados.get(a.id, {})) for a in alumnos.get(sec.id, [])], "PTF")
    if not wb.worksheets:
        wb.create_sheet("Sin secciones")
    return _excel(wb, f"asistencia-{anio}-{mes:02d}.xlsx")


# --- Personal -------------------------------------------------------------------

def _licencias_en(db: Session, cid: int, desde: date, hasta: date):
    return db.scalars(select(LicenciaPersonal).where(
        LicenciaPersonal.colegio_id == cid, LicenciaPersonal.desde <= hasta, LicenciaPersonal.hasta >= desde)
        .order_by(LicenciaPersonal.desde)).all()


@router.get("/personal/dia")
def personal_dia(fecha: date | None = None, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    cid, fecha = s.colegio.id, fecha or hoy_lima()
    licencias = {lic.usuario_id: lic.tipo for lic in _licencias_en(db, cid, fecha, fecha)}
    filas = db.execute(
        select(Usuario, Rol.nombre, Turno.nombre, AsistenciaPersonal,
               asistencia.registrada_despues(cid, fecha, usuario_id=Usuario.id))
        .join(Rol, and_(Rol.colegio_id == Usuario.colegio_id, Rol.id == Usuario.rol_id))
        .outerjoin(Turno, and_(Turno.colegio_id == Usuario.colegio_id, Turno.id == Usuario.turno_id))
        .outerjoin(AsistenciaPersonal, and_(AsistenciaPersonal.colegio_id == Usuario.colegio_id,
                                            AsistenciaPersonal.usuario_id == Usuario.id,
                                            AsistenciaPersonal.fecha == fecha))
        .where(Usuario.colegio_id == cid, Usuario.activo).order_by(Usuario.apellidos, Usuario.nombres))
    return {"fecha": fecha.isoformat(), "lectivo": es_dia_lectivo(db, cid, fecha), "personal": [{
        "usuario_id": u.id, "nombre": f"{u.apellidos}, {u.nombres}", "rol": rol, "turno": turno,
        "estado": f.estado if f else ("licencia" if u.id in licencias else None),
        "entrada": asistencia.hora(f.entrada) if f else None, "salida": asistencia.hora(f.salida) if f else None,
        "minutos_tarde": f.minutos_tarde if f else 0, "licencia": licencias.get(u.id),
        "registrada_despues": tardia,
    } for u, rol, turno, f, tardia in filas]}


@router.get("/personal/mensual.xlsx")
def personal_mensual(anio: int, mes: int, s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> Response:
    cid = s.colegio.id
    dias = _dias(db, cid, anio, mes)
    estados: dict[int, dict[date, str]] = {}
    if dias:
        for usuario_id, fecha, estado in db.execute(
                select(AsistenciaPersonal.usuario_id, AsistenciaPersonal.fecha, AsistenciaPersonal.estado)
                .where(AsistenciaPersonal.colegio_id == cid,
                       AsistenciaPersonal.fecha.between(dias[0], dias[-1]))):
            estados.setdefault(usuario_id, {})[fecha] = LETRA[estado]
        for lic in _licencias_en(db, cid, dias[0], dias[-1]):  # licencia sin fila (persona sin turno)
            for d in dias:
                if lic.desde <= d <= lic.hasta:
                    estados.setdefault(lic.usuario_id, {}).setdefault(d, "L")
    personal = db.scalars(select(Usuario).where(Usuario.colegio_id == cid, Usuario.activo)
                          .order_by(Usuario.apellidos, Usuario.nombres))
    wb = Workbook()
    _hoja(wb.active, f"{s.colegio.nombre} · Personal · {mes:02d}/{anio}", dias,
          [(f"{u.apellidos}, {u.nombres}", estados.get(u.id, {})) for u in personal], "PTFL")
    wb.active.title = "Personal"
    return _excel(wb, f"asistencia-personal-{anio}-{mes:02d}.xlsx")


class DatosLicencia(BaseModel):
    usuario_id: int
    tipo: Literal[TIPOS_LICENCIA]  # type: ignore[valid-type]
    desde: date
    hasta: date
    motivo: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _fechas(self):
        if self.hasta < self.desde:
            raise ValueError("La fecha final no puede ser anterior a la inicial")
        if (self.hasta - self.desde) > timedelta(days=366):
            raise ValueError("Una licencia no puede durar más de un año")
        self.motivo = (self.motivo or "").strip() or None
        return self


def _licencia(lic: LicenciaPersonal, u: Usuario, con_motivo: bool = True) -> dict:
    return {"id": lic.id, "usuario_id": lic.usuario_id, "nombre": f"{u.apellidos}, {u.nombres}", "tipo": lic.tipo,
            "desde": lic.desde.isoformat(), "hasta": lic.hasta.isoformat(),
            "motivo": lic.motivo if con_motivo else None}


@router.get("/licencias")
def licencias(desde: date | None = None, hasta: date | None = None, s: Sesion = Depends(ver),
              db: Session = Depends(get_db)) -> list[dict]:
    hoy = hoy_lima()
    desde, hasta = desde or hoy - timedelta(days=60), hasta or hoy + timedelta(days=365)
    lics = _licencias_en(db, s.colegio.id, desde, hasta)
    personas = {u.id: u for u in db.scalars(select(Usuario).where(
        Usuario.colegio_id == s.colegio.id, Usuario.id.in_({lic.usuario_id for lic in lics})))}
    # El motivo (p. ej. un descanso médico) solo lo ve quien tiene permiso sobre el personal.
    con_motivo = tiene_permiso(s.usuario, "personal", "ver")
    return [_licencia(lic, personas[lic.usuario_id], con_motivo) for lic in lics]


@router.post("/licencias", status_code=201)
def crear_licencia(datos: DatosLicencia, s: Sesion = Depends(editar_licencias), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    u = obtener(db, Usuario, cid, datos.usuario_id, "Personal")
    if any(lic.usuario_id == u.id for lic in _licencias_en(db, cid, datos.desde, datos.hasta)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya tiene una licencia en esas fechas")
    lic = LicenciaPersonal(colegio_id=cid, usuario_id=u.id, tipo=datos.tipo, desde=datos.desde, hasta=datos.hasta,
                           motivo=datos.motivo, registrado_por_id=s.usuario.id)
    db.add(lic)
    asistencia.aplicar_licencia(db, lic)
    guardar(db)
    return _licencia(lic, u)


@router.delete("/licencias/{licencia_id}", status_code=204)
def borrar_licencia(licencia_id: int, s: Sesion = Depends(editar_licencias), db: Session = Depends(get_db)) -> None:
    lic = obtener(db, LicenciaPersonal, s.colegio.id, licencia_id, "Registro de licencia")
    asistencia.aplicar_licencia(db, lic, quitar=True)
    db.delete(lic)
    guardar(db)


# --- Reglas del colegio --------------------------------------------------------------

class DatosConfig(BaseModel):
    minutos_duplicado: int = Field(ge=1, le=120)
    minutos_corte_falta: int = Field(ge=15, le=600)


def _config(c: ConfigAsistencia) -> dict:
    return {"minutos_duplicado": c.minutos_duplicado, "minutos_corte_falta": c.minutos_corte_falta}


@router.get("/configuracion")
def ver_config(s: Sesion = Depends(ver), db: Session = Depends(get_db)) -> dict:
    return _config(asistencia.config(db, s.colegio.id))


@router.put("/configuracion")
def editar_config(datos: DatosConfig, s: Sesion = Depends(editar_reglas), db: Session = Depends(get_db)) -> dict:
    c = db.get(ConfigAsistencia, s.colegio.id)
    if c is None:
        c = ConfigAsistencia(colegio_id=s.colegio.id)
        db.add(c)
    c.minutos_duplicado, c.minutos_corte_falta = datos.minutos_duplicado, datos.minutos_corte_falta
    guardar(db)
    return _config(c)

