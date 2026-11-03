"""Pasar un colegio de prueba a activo: borrar los datos de ejemplo que cargó durante la prueba.

Cada tabla con `colegio_id` está en una de dos listas: lo que se borra (alumnos, apoderados, marcaciones,
cuaderno, avisos y todo lo que cuelga de ellos) y lo que se conserva (estructura, turnos, calendario, roles,
personal, imagen y configuración). Una prueba exige que toda tabla nueva esté en una de las dos.
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.almacenamiento import get_almacenamiento_privado
from app.db import Base
from app.models import AdjuntoCuaderno, Apoderado, Colegio, CuentaFamilia

BORRAR = {
    "alumno", "apoderado", "alumno_apoderado", "matricula", "cambio_apoderado", "consentimiento_apoderado",
    "invitacion_familia", "reto_usado", "suscripcion_push",
    "marcacion", "asistencia_alumno", "asistencia_personal",
    "entrada_cuaderno", "destino_cuaderno", "mensaje_cuaderno", "adjunto_cuaderno",
    "cola_aviso", "entrega_aviso",
    "reunion_padres", "ficha_reunion",
}
CONSERVAR = {
    "anio_escolar", "nivel", "grado", "seccion", "turno", "dia_no_lectivo",
    "rol", "permiso_rol", "usuario", "licencia_personal", "seccion_docente",
    "config_asistencia", "config_familias", "categoria_incidencia", "plantilla_comunicado", "registro_actividad",
}


def tablas_del_colegio() -> set[str]:
    return {t.name for t in Base.metadata.sorted_tables if "colegio_id" in t.c}


def borrar_datos_de_ejemplo(db: Session, colegio: Colegio) -> dict[str, int]:
    """Borra solo de este colegio y solo las tablas de BORRAR. Devuelve cuántas filas por tabla y, en
    "_archivos", las claves de adjuntos a borrar del almacenamiento después del commit. No hace commit."""
    cid = colegio.id
    archivos = list(db.scalars(select(AdjuntoCuaderno.clave).where(AdjuntoCuaderno.colegio_id == cid)))
    # Cuentas de familia (globales) de sus apoderados: se borran luego si ya no son de ningún otro colegio.
    cuentas = set(db.scalars(select(Apoderado.cuenta_id).where(Apoderado.colegio_id == cid,
                                                              Apoderado.cuenta_id.is_not(None))))
    conteo: dict = {}
    for tabla in reversed(Base.metadata.sorted_tables):  # los hijos antes que los padres
        if tabla.name in BORRAR:
            n = db.execute(tabla.delete().where(tabla.c.colegio_id == cid)).rowcount
            if n:
                conteo[tabla.name] = n
    if cuentas:
        en_uso = set(db.scalars(select(Apoderado.cuenta_id).where(Apoderado.cuenta_id.in_(cuentas))))
        huerfanas = cuentas - en_uso
        if huerfanas:
            conteo["cuenta_familia"] = db.execute(delete(CuentaFamilia).where(CuentaFamilia.id.in_(huerfanas))).rowcount
    conteo["_archivos"] = archivos
    return conteo


def borrar_archivos(claves: list[str]) -> None:
    almacen = get_almacenamiento_privado()
    for clave in claves:
        almacen.borrar(clave)


