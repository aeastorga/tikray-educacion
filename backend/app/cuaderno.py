"""Reglas del cuaderno de control, compartidas por el panel del colegio y el espacio de la familia.

- A quién le llega una entrada (`destinos`): se resuelve al crearla y queda guardado.
- Qué secciones ve cada persona del personal (`secciones_permitidas`): todas, o solo las
  suyas si su rol tiene `solo_sus_secciones`.
- Adjuntos: se revisa el tipo por su contenido y se guardan en el almacenamiento privado.
- Cada novedad deja un aviso "cuaderno" por apoderado en `cola_aviso`; lo envía el mismo
  proceso de los avisos de asistencia.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.almacenamiento import get_almacenamiento_privado
from app.fechas import LIMA
from app.models import (AdjuntoCuaderno, Alumno, AlumnoApoderado, AnioEscolar, Apoderado, AsistenciaAlumno,
                        CategoriaIncidencia, ColaAviso,
                        DestinoCuaderno, EntradaCuaderno, Grado, Matricula, Nivel, Seccion, SeccionDocente, Usuario)

MAX_ADJUNTOS = 5
MAX_BYTES = 10 * 1024 * 1024
# Tipo -> cómo empieza el archivo. Los de Office son zip.
TIPOS_ADJUNTO = {
    "application/pdf": (b"%PDF",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (b"PK\x03\x04",),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (b"PK\x03\x04",),
}
# Los que el navegador puede mostrar sin riesgo; el resto se descarga.
EN_LINEA = {"application/pdf", "image/jpeg", "image/png", "image/webp"}

NOMBRE_TIPO = {"comunicado": "Comunicado", "incidencia": "Incidencia", "citacion": "Citación",
               "justificacion": "Justificación", "permiso_salida": "Permiso de salida"}


def requiere_firma(e: EntradaCuaderno) -> bool:
    """Comunicado si el colegio la pide; incidencia ("enterado") y citación ("asistiré") siempre."""
    return e.pide_firma if e.tipo == "comunicado" else e.tipo in ("incidencia", "citacion")


def anio_activo_id(colegio_id: int):
    return (select(AnioEscolar.id).where(AnioEscolar.colegio_id == colegio_id, AnioEscolar.activo)
            .scalar_subquery())


def seccion_de(db: Session, colegio_id: int, alumno_id: int) -> int | None:
    return db.scalar(select(Matricula.seccion_id).where(
        Matricula.colegio_id == colegio_id, Matricula.alumno_id == alumno_id,
        Matricula.anio_id == anio_activo_id(colegio_id)))


# --- Qué ve cada persona del personal ----------------------------------------------

def secciones_permitidas(db: Session, usuario: Usuario) -> set[int] | None:
    """None: ve todo el colegio. Un conjunto: solo esas secciones (puede estar vacío)."""
    if usuario.rol.es_director or not usuario.rol.solo_sus_secciones:
        return None
    return set(db.scalars(select(SeccionDocente.seccion_id).where(
        SeccionDocente.colegio_id == usuario.colegio_id, SeccionDocente.usuario_id == usuario.id)))


def puede_ver(e: EntradaCuaderno, permitidas: set[int] | None) -> bool:
    return permitidas is None or (e.seccion_id is not None and e.seccion_id in permitidas)


# --- A quién le llega ----------------------------------------------------------------

@dataclass
class Destino:
    alcance: str
    nivel_id: int | None = None
    grado_id: int | None = None
    seccion_id: int | None = None
    alumno_id: int | None = None


def validar_destino(db: Session, colegio_id: int, d: Destino, permitidas: set[int] | None) -> Destino:
    """Revisa que el destino sea de este colegio (404 si no) y que la persona pueda escribirle.
    Para un alumno completa su sección del año activo."""
    def existe(modelo, id_, nombre):
        if id_ is None or db.scalar(select(modelo.id).where(modelo.colegio_id == colegio_id,
                                                            modelo.id == id_)) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{nombre} no encontrado")

    if d.alcance == "nivel":
        existe(Nivel, d.nivel_id, "Nivel")
        d = Destino("nivel", nivel_id=d.nivel_id)
    elif d.alcance == "grado":
        existe(Grado, d.grado_id, "Grado")
        d = Destino("grado", grado_id=d.grado_id)
    elif d.alcance == "seccion":
        existe(Seccion, d.seccion_id, "Sección")
        d = Destino("seccion", seccion_id=d.seccion_id)
    elif d.alcance == "alumno":
        existe(Alumno, d.alumno_id, "Alumno")
        d = Destino("alumno", alumno_id=d.alumno_id, seccion_id=seccion_de(db, colegio_id, d.alumno_id))
    else:
        d = Destino("colegio")
    if permitidas is not None and (d.alcance not in ("seccion", "alumno") or d.seccion_id not in permitidas):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puedes escribir a las secciones a tu cargo")
    return d


def alumnos_del_destino(db: Session, colegio_id: int, d: Destino) -> list[int]:
    if d.alcance == "alumno":
        return [d.alumno_id]
    q = (select(Alumno.id).join(Matricula, and_(Matricula.colegio_id == Alumno.colegio_id,
                                                Matricula.alumno_id == Alumno.id,
                                                Matricula.anio_id == anio_activo_id(colegio_id)))
         .join(Seccion, and_(Seccion.colegio_id == Matricula.colegio_id, Seccion.id == Matricula.seccion_id))
         .join(Grado, and_(Grado.colegio_id == Seccion.colegio_id, Grado.id == Seccion.grado_id))
         .where(Alumno.colegio_id == colegio_id, Alumno.activo))
    if d.alcance == "nivel":
        q = q.where(Grado.nivel_id == d.nivel_id)
    elif d.alcance == "grado":
        q = q.where(Grado.id == d.grado_id)
    elif d.alcance == "seccion":
        q = q.where(Seccion.id == d.seccion_id)
    return list(db.scalars(q))


def guardar_destinos(db: Session, e: EntradaCuaderno, alumnos: list[int]) -> list[int]:
    """Una fila por alumno y apoderado. Devuelve los apoderados (sin repetir)."""
    if not alumnos:
        return []
    pares = db.execute(select(AlumnoApoderado.alumno_id, AlumnoApoderado.apoderado_id).where(
        AlumnoApoderado.colegio_id == e.colegio_id, AlumnoApoderado.alumno_id.in_(alumnos))).all()
    if pares:
        db.execute(insert(DestinoCuaderno).values([
            {"colegio_id": e.colegio_id, "entrada_id": e.id, "alumno_id": a, "apoderado_id": p} for a, p in pares
        ]).on_conflict_do_nothing())
    return sorted({p for _, p in pares})


def apoderados_de(db: Session, e: EntradaCuaderno) -> list[int]:
    return list(db.scalars(select(DestinoCuaderno.apoderado_id).distinct().where(
        DestinoCuaderno.colegio_id == e.colegio_id, DestinoCuaderno.entrada_id == e.id)))


def avisar(db: Session, e: EntradaCuaderno, apoderados: list[int], mensaje: str) -> int:
    """Deja un aviso push por apoderado con cuenta activa. No envía nada aquí."""
    if not apoderados:
        return 0
    con_app = list(db.scalars(select(Apoderado.id).where(
        Apoderado.colegio_id == e.colegio_id, Apoderado.id.in_(apoderados), Apoderado.estado_acceso == "activo")))
    if con_app:
        datos = {"mensaje": mensaje[:280], "url": f"/familia/cuaderno/{e.id}", "entrada_id": e.id}
        # Programado: el aviso espera en la cola hasta la hora de envío (y luego, si cae en el horario sin
        # molestar, hasta que termine).
        desde = e.programado_para or datetime.now(UTC)
        db.execute(insert(ColaAviso).values([
            {"colegio_id": e.colegio_id, "tipo": "cuaderno", "apoderado_id": a, "datos": datos,
             "fecha": desde.astimezone(LIMA).date(), "procesar_desde": desde}
            for a in con_app]))
    return len(con_app)


def nombre_alumno(db: Session, colegio_id: int, alumno_id: int | None) -> str:
    if alumno_id is None:
        return ""
    a = db.scalar(select(Alumno).where(Alumno.colegio_id == colegio_id, Alumno.id == alumno_id))
    return a.nombres.split()[0] if a and a.nombres else ""


def texto_aviso(db: Session, e: EntradaCuaderno, que: str = "nueva") -> str:
    n = nombre_alumno(db, e.colegio_id, e.alumno_id)
    de = f" de {n}" if n else ""
    if que == "respuesta":
        return f"Respuesta del colegio en «{e.titulo}»."
    if que == "resuelta":
        return f"{NOMBRE_TIPO[e.tipo]}{de}: {e.estado}."
    if e.tipo == "comunicado":
        return f"Comunicado: {e.titulo}" + (" (firma de lectura)" if e.pide_firma else "")
    if e.tipo == "incidencia":
        return f"Incidencia{de}: {e.titulo}"
    if e.tipo == "citacion":
        cuando = e.cita_en.astimezone(LIMA).strftime("%d/%m a las %H:%M")
        return f"Citación{de} el {cuando}: {e.titulo}. Confirma tu asistencia."
    if e.tipo == "justificacion":
        return f"Se registró una justificación{de}: {e.titulo}"
    return f"Permiso de salida{de} el {e.desde.strftime('%d/%m')} a las {e.hora_salida.strftime('%H:%M')}."


def firmar(db: Session, e: EntradaCuaderno, apoderado_id: int) -> datetime:
    ahora = datetime.now(UTC)
    for d in db.scalars(select(DestinoCuaderno).where(
            DestinoCuaderno.colegio_id == e.colegio_id, DestinoCuaderno.entrada_id == e.id,
            DestinoCuaderno.apoderado_id == apoderado_id)):
        d.visto_en = d.visto_en or ahora
        d.firmado_en = d.firmado_en or ahora
    return ahora


# --- Adjuntos ----------------------------------------------------------------------

def _tipo(contenido: bytes, declarado: str | None) -> str | None:
    if contenido[:4] == b"RIFF" and contenido[8:12] != b"WEBP":
        return None
    candidatos = [t for t, firmas in TIPOS_ADJUNTO.items() if any(contenido.startswith(f) for f in firmas)]
    if declarado in candidatos:
        return declarado
    # Office: el navegador a veces no declara el tipo; se decide por la extensión.
    return candidatos[0] if len(candidatos) == 1 else None


async def leer_adjuntos(archivos: list[UploadFile] | None) -> list[tuple[str, str, bytes]]:
    """(nombre, tipo, contenido) de cada archivo, o 422 con el motivo."""
    archivos = [a for a in archivos or [] if a.filename]
    if len(archivos) > MAX_ADJUNTOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Hasta {MAX_ADJUNTOS} archivos")
    salida = []
    for a in archivos:
        contenido = await a.read(MAX_BYTES + 1)
        if len(contenido) > MAX_BYTES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{a.filename}: pesa más de 10 MB")
        if not contenido:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{a.filename}: está vacío")
        declarado = a.content_type
        if declarado in (None, "", "application/octet-stream", "application/zip"):
            ext = a.filename.rsplit(".", 1)[-1].lower()
            declarado = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}.get(ext)
        tipo = _tipo(contenido, declarado)
        if tipo is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                f"{a.filename}: solo se aceptan PDF, imágenes (JPG, PNG, WEBP), Word o Excel")
        salida.append((a.filename[-200:], tipo, contenido))
    return salida


def guardar_adjuntos(db: Session, e: EntradaCuaderno, archivos: list[tuple[str, str, bytes]]) -> list[str]:
    """Sube los archivos y deja sus filas (sin commit). Devuelve las claves, para borrarlas si
    después falla el commit."""
    almacen = get_almacenamiento_privado()
    claves = []
    for nombre, tipo, contenido in archivos:
        clave = f"cuaderno/{e.colegio_id}/{uuid.uuid4().hex}"
        almacen.guardar(clave, contenido, tipo)
        claves.append(clave)
        db.add(AdjuntoCuaderno(colegio_id=e.colegio_id, entrada_id=e.id, clave=clave, nombre=nombre,
                               tipo_mime=tipo, tamano=len(contenido)))
    return claves


def borrar_archivos(claves: list[str]) -> None:
    almacen = get_almacenamiento_privado()
    for c in claves:
        almacen.borrar(c)


def respuesta_adjunto(adj: AdjuntoCuaderno):
    from urllib.parse import quote

    from fastapi import Response

    contenido = get_almacenamiento_privado().leer(adj.clave)
    if contenido is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Archivo no encontrado")
    modo = "inline" if adj.tipo_mime in EN_LINEA else "attachment"
    return Response(contenido, media_type=adj.tipo_mime, headers={
        "Content-Disposition": f"{modo}; filename*=UTF-8''{quote(adj.nombre)}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


def adjuntos_de(db: Session, colegio_id: int, entrada_ids: list[int]) -> dict[int, list[dict]]:
    salida: dict[int, list[dict]] = {}
    if not entrada_ids:
        return salida
    for a in db.scalars(select(AdjuntoCuaderno).where(AdjuntoCuaderno.colegio_id == colegio_id,
                                                      AdjuntoCuaderno.entrada_id.in_(entrada_ids))
                        .order_by(AdjuntoCuaderno.id)):
        salida.setdefault(a.entrada_id, []).append(
            {"id": a.id, "nombre": a.nombre, "tipo": a.tipo_mime, "tamano": a.tamano})
    return salida


def a_lima(momento: datetime) -> datetime:
    """Fecha y hora escrita en el formulario (sin zona) = hora de Lima."""
    return momento.replace(tzinfo=LIMA) if momento.tzinfo is None else momento


def iso(m: datetime | None) -> str | None:
    return m.isoformat() if m else None


def publicada(ahora: datetime | None = None):
    """Condición: ya salió (no es un comunicado programado para más tarde). La familia solo ve estas."""
    ahora = ahora or datetime.now(UTC)
    return or_(EntradaCuaderno.programado_para.is_(None), EntradaCuaderno.programado_para <= ahora)


def categorias_de(db: Session, colegio_id: int) -> dict[int, dict]:
    return {c.id: {"id": c.id, "nombre": c.nombre, "tipo": c.tipo} for c in db.scalars(
        select(CategoriaIncidencia).where(CategoriaIncidencia.colegio_id == colegio_id))}


def entrada_basica(e: EntradaCuaderno, categorias: dict[int, dict] | None = None) -> dict:
    """Lo que ven igual el colegio y la familia."""
    return {
        "categoria": (categorias or {}).get(e.categoria_id), "programado_para": iso(e.programado_para),
        "id": e.id, "tipo": e.tipo, "titulo": e.titulo, "cuerpo": e.cuerpo, "alcance": e.alcance,
        "pide_firma": requiere_firma(e), "cita_en": iso(e.cita_en), "lugar": e.lugar,
        "desde": e.desde.isoformat() if e.desde else None, "hasta": e.hasta.isoformat() if e.hasta else None,
        "hora_salida": e.hora_salida.strftime("%H:%M") if e.hora_salida else None, "recoge": e.recoge,
        "estado": e.estado, "nota_resolucion": e.nota_resolucion, "resuelto_en": iso(e.resuelto_en),
        "motivo_anulacion": e.motivo_anulacion,
        "creado_en": iso(e.creado_en), "de_familia": e.apoderado_autor_id is not None,
    }


# --- Justificación aprobada -> asistencia ---------------------------------------------------

def justificacion_vigente(colegio_id: int, alumno_id, fecha):
    """Subconsulta: la justificación aprobada (la primera) que cubre a ese alumno en esa fecha.
    Sirve con columnas (en la falta automática) o con valores."""
    return (select(EntradaCuaderno.id).where(
        EntradaCuaderno.colegio_id == colegio_id, EntradaCuaderno.tipo == "justificacion",
        EntradaCuaderno.estado == "aprobada", EntradaCuaderno.alumno_id == alumno_id,
        EntradaCuaderno.desde <= fecha, EntradaCuaderno.hasta >= fecha)
        .order_by(EntradaCuaderno.id).limit(1).scalar_subquery())


def aplicar_justificacion(db: Session, e: EntradaCuaderno) -> int:
    """Las faltas de esos días pasan a "justificada". Las que se marquen después (un día que aún no
    llegó) ya nacen justificadas (ver `asistencia.marcar_faltas`). Devuelve cuántas cambió."""
    r = db.execute(update(AsistenciaAlumno).where(
        AsistenciaAlumno.colegio_id == e.colegio_id, AsistenciaAlumno.alumno_id == e.alumno_id,
        AsistenciaAlumno.fecha.between(e.desde, e.hasta), AsistenciaAlumno.estado == "falta")
        .values(estado="justificada", justificacion_id=e.id))
    # El aviso de falta que aún no salió ya no corresponde.
    db.execute(delete(ColaAviso).where(
        ColaAviso.colegio_id == e.colegio_id, ColaAviso.alumno_id == e.alumno_id, ColaAviso.tipo == "falta",
        ColaAviso.fecha.between(e.desde, e.hasta), ColaAviso.estado == "pendiente"))
    return r.rowcount


def quitar_justificacion(db: Session, e: EntradaCuaderno) -> int:
    """Al anularla, sus días vuelven a "falta", salvo los que cubra otra justificación aprobada."""
    filas = db.scalars(select(AsistenciaAlumno).where(
        AsistenciaAlumno.colegio_id == e.colegio_id, AsistenciaAlumno.justificacion_id == e.id,
        AsistenciaAlumno.estado == "justificada")).all()
    for f in filas:
        otra = db.scalar(select(justificacion_vigente(e.colegio_id, f.alumno_id, f.fecha)))
        f.estado, f.justificacion_id = ("justificada", otra) if otra else ("falta", None)
    return sum(1 for f in filas if f.estado == "falta")
