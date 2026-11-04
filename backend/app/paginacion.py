"""Paginación común de las listas del panel: ?pagina=1&por_pagina=25 (máximo 100).
Responde siempre total, pagina, paginas y por_pagina junto a las filas."""

from dataclasses import dataclass

from fastapi import Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

POR_PAGINA = 25
MAXIMO = 100


@dataclass
class Pagina:
    pagina: int
    por_pagina: int

    @property
    def desde(self) -> int:
        return (self.pagina - 1) * self.por_pagina

    def datos(self, total: int) -> dict:
        return {"total": total, "pagina": self.pagina, "por_pagina": self.por_pagina,
                "paginas": max(1, -(-total // self.por_pagina))}


def pagina(pagina: int = Query(1, ge=1, le=100000),
           por_pagina: int = Query(POR_PAGINA, ge=1, le=MAXIMO)) -> Pagina:
    """Dependencia: fuera de rango responde 422."""
    return Pagina(pagina, por_pagina)


def contar(db: Session, consulta: Select) -> int:
    return db.scalar(select(func.count()).select_from(consulta.order_by(None).subquery())) or 0


def recortar(consulta: Select, p: Pagina) -> Select:
    return consulta.offset(p.desde).limit(p.por_pagina)
