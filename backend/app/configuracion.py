"""Lo que decide el administrador: módulos activos, qué avisos salen y cuándo, categorías por defecto,
y el historial de actividad."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.fechas import LIMA
from app.models import CategoriaGasto, CategoriaIncidencia, Colegio, RegistroActividad, Usuario

# Las que recibe todo colegio nuevo (y las que la migración dio a los que ya existían). Editables.
CATEGORIAS_POR_DEFECTO = (
    ("Participación", "merito"), ("Compañerismo", "merito"), ("Logro académico", "merito"),
    ("Puntualidad", "mejora"), ("Conducta", "mejora"), ("Tareas y materiales", "mejora"),
)

CATEGORIAS_GASTO_POR_DEFECTO = ("Servicios", "Materiales", "Mantenimiento", "Planilla", "Otros")

# Tipo de la cola de avisos -> interruptor del administrador y módulo del que depende.
AVISO_DE_COLA = {"ingreso": ("ingreso", "asistencia"), "tarde": ("tardanza", "asistencia"),
                 "falta": ("falta", "asistencia"), "salida": ("salida", "asistencia"),
                 "cuaderno": ("cuaderno", "cuaderno"), "cobro": ("cobro", "pensiones"),
                 "calendario": ("calendario", "calendario"),
                 "autorizar": ("autorizaciones", "autorizaciones")}


def crear_categorias_por_defecto(db: Session, colegio_id: int) -> None:
    db.add_all([CategoriaIncidencia(colegio_id=colegio_id, nombre=n, tipo=t, orden=i)
                for i, (n, t) in enumerate(CATEGORIAS_POR_DEFECTO, 1)])
    db.add_all([CategoriaGasto(colegio_id=colegio_id, nombre=n, orden=i)
                for i, n in enumerate(CATEGORIAS_GASTO_POR_DEFECTO, 1)])


def aviso_permitido(colegio: Colegio, tipo_cola: str) -> bool:
    """¿El colegio deja salir este tipo de aviso? Los de la cuenta del padre salen siempre."""
    if tipo_cola not in AVISO_DE_COLA:
        return True
    interruptor, modulo = AVISO_DE_COLA[tipo_cola]
    return colegio.modulo_activo(modulo) and bool((colegio.avisos_tipos or {}).get(interruptor, True))


def fin_del_silencio(colegio: Colegio, ahora: datetime) -> datetime | None:
    """Si `ahora` cae en el horario sin molestar (hora de Lima), cuándo termina (UTC). Si no, None.
    El horario puede cruzar la medianoche (21:00 a 6:00) o no (13:00 a 15:00). Desde = hasta: sin horario."""
    desde, hasta = colegio.silencio_desde, colegio.silencio_hasta
    if desde == hasta:
        return None
    local = ahora.astimezone(LIMA)
    h = local.time()
    if desde < hasta:
        dentro, fin_dia = desde <= h < hasta, local.date()
    else:
        dentro = h >= desde or h < hasta
        fin_dia = local.date() + timedelta(days=1) if h >= desde else local.date()
    if not dentro:
        return None
    return datetime.combine(fin_dia, hasta, LIMA).astimezone(UTC)


# --- Historial de actividad ----------------------------------------------------------------

def registrar(db: Session, colegio_id: int, quien: Usuario | str | None, accion: str, modulo: str, que: str,
              objeto_id: int | None, resumen: str) -> None:
    """Deja una fila en el historial (sin commit: entra en la misma transacción que el cambio).
    `resumen` es corto y sin datos sensibles: ni PIN, ni claves, ni motivos de licencia, ni el texto de
    una justificación. Quien llama elige qué poner; aquí solo se recorta."""
    if isinstance(quien, Usuario):
        usuario_id, nombre = quien.id, f"{quien.nombres} {quien.apellidos}".strip()
    else:
        usuario_id, nombre = None, quien or "Sistema"
    db.add(RegistroActividad(colegio_id=colegio_id, usuario_id=usuario_id, quien=nombre[:160], accion=accion,
                             modulo=modulo, que=que[:40], objeto_id=objeto_id, resumen=" ".join(resumen.split())[:200]))




def anotar(db: Session, sesion, accion: str, modulo: str, que: str, objeto, resumen: str, *args, **kwargs) -> None:
    """Guarda el cambio y su línea del historial en una sola transacción. `objeto` es la fila (su id se
    conoce tras el flush) o un id. Los demás argumentos van a `comun.guardar` (mensajes de 409)."""
    from app.comun import guardar

    guardar(db, *args, solo_flush=True, **kwargs)
    objeto_id = objeto if isinstance(objeto, int) or objeto is None else objeto.id
    registrar(db, sesion.colegio.id, sesion.usuario, accion, modulo, que, objeto_id, resumen)
    guardar(db, *args, **kwargs)
