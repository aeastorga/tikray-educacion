"""Corrección de recojo seguro: en `autorizado_recojo`, `autorizacion_recojo_dia` y `recojo` la llave hacia
`colegio` queda en RESTRICT (como en todas las tablas `ConColegio`) y se agrega el índice de `colegio_id`.
La migración de recojo (c3d8e1f4a2b7) las había creado en CASCADE y sin índice.

Revision ID: e7a1c5d9f3b2
Revises: d4e9f2a5b8c1
Create Date: 2026-11-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e7a1c5d9f3b2'
down_revision: Union[str, Sequence[str], None] = 'd4e9f2a5b8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLAS = ('autorizado_recojo', 'autorizacion_recojo_dia', 'recojo')


def _llave(tabla: str, ondelete: str) -> None:
    op.drop_constraint(op.f(f'fk_{tabla}_colegio_id_colegio'), tabla, type_='foreignkey')
    op.create_foreign_key(op.f(f'fk_{tabla}_colegio_id_colegio'), tabla, 'colegio', ['colegio_id'], ['id'],
                          ondelete=ondelete)


def upgrade() -> None:
    """Upgrade schema."""
    for tabla in TABLAS:
        _llave(tabla, 'RESTRICT')
        op.create_index(op.f(f'ix_{tabla}_colegio_id'), tabla, ['colegio_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    for tabla in TABLAS:
        op.drop_index(op.f(f'ix_{tabla}_colegio_id'), table_name=tabla)
        _llave(tabla, 'CASCADE')
