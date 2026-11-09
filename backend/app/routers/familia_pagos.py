"""Pagos, lado de la familia: las cuotas de cada hijo (estado, saldo y vencimiento), los pagos hechos y su
recibo. Solo los ve el apoderado responsable de pago del alumno (si nadie está marcado, el primero).

La deuda no bloquea nada: es solo información. Sin pago en línea.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app import pensiones
from app.db import get_db
from app.deps import SesionFamilia, modulo_encendido
from app.models import Alumno, AlumnoApoderado, Pago
from app.routers.caja import recibo_pdf
from app.routers.familia_cuaderno import familia_activa
from app.routers.pensiones import cuotas_de_alumno, pagos_de_alumno

privado = APIRouter(prefix="/familia/pagos", tags=["familia"], dependencies=[Depends(modulo_encendido("pensiones"))])


def _a_cargo(db: Session, s: SesionFamilia) -> list[Alumno]:
    """Hijos de los que este apoderado es el responsable de pago."""
    cid = s.colegio.id
    hijos = db.scalars(select(Alumno).join(AlumnoApoderado, and_(AlumnoApoderado.colegio_id == Alumno.colegio_id,
                                                                 AlumnoApoderado.alumno_id == Alumno.id))
                       .where(Alumno.colegio_id == cid, AlumnoApoderado.apoderado_id == s.apoderado.id)
                       .order_by(Alumno.nombres)).all()
    resp = pensiones.responsables(db, cid, [a.id for a in hijos])
    return [a for a in hijos if resp.get(a.id) == s.apoderado.id]


@privado.get("")
def pagos(s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)) -> dict:
    cid = s.colegio.id
    hijos = []
    for a in _a_cargo(db, s):
        cuotas = [c for c in cuotas_de_alumno(db, cid, a.id) if c["estado"] != "anulada"]
        hijos.append({"id": a.id, "nombres": a.nombres, "apellidos": a.apellidos, "cuotas": cuotas,
                      "saldo": str(sum((pensiones.soles(c["saldo"]) for c in cuotas), pensiones.CERO)),
                      "vencido": str(sum((pensiones.soles(c["saldo"]) for c in cuotas if c["estado"] == "vencida"),
                                         pensiones.CERO)),
                      "pagos": [p for p in pagos_de_alumno(db, cid, a.id) if not p["anulado"]]})
    return {"hijos": hijos}


@privado.get("/{pago_id}/recibo.pdf")
def recibo(pago_id: int, s: SesionFamilia = Depends(familia_activa), db: Session = Depends(get_db)) -> Response:
    """Solo el recibo de un pago válido de un hijo a su cargo; cualquier otro da 404."""
    p = db.scalar(select(Pago).where(Pago.colegio_id == s.colegio.id, Pago.id == pago_id, Pago.anulado_en.is_(None),
                                     Pago.alumno_id.in_([a.id for a in _a_cargo(db, s)])))
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recibo no encontrado")
    return recibo_pdf(db, s.colegio, p)
