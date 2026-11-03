"""Modo reunión: "Verifiqué su DNI en persona" queda en la ficha con el nombre del tutor.

Revision ID: 26b4a82721a0
Revises: f523881eb9f1
Create Date: 2026-11-03 10:34:09.773322

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '26b4a82721a0'
down_revision: Union[str, Sequence[str], None] = 'f523881eb9f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('ficha_reunion', sa.Column('dni_verificado_por_id', sa.Integer(), nullable=True))
    op.add_column('ficha_reunion', sa.Column('dni_verificado_por', sa.String(length=250), nullable=True))
    op.add_column('ficha_reunion', sa.Column('dni_verificado_en', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(op.f('fk_ficha_reunion_colegio_id_dni_verificado_por_id_usuario'), 'ficha_reunion', 'usuario', ['colegio_id', 'dni_verificado_por_id'], ['colegio_id', 'id'], ondelete='SET NULL (dni_verificado_por_id)')
    op.create_check_constraint(op.f('ck_ficha_reunion_verificacion_completa'), 'ficha_reunion',
                               '(dni_verificado_en IS NULL) = (dni_verificado_por IS NULL)')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('ck_ficha_reunion_verificacion_completa'), 'ficha_reunion', type_='check')
    op.drop_constraint(op.f('fk_ficha_reunion_colegio_id_dni_verificado_por_id_usuario'), 'ficha_reunion', type_='foreignkey')
    op.drop_column('ficha_reunion', 'dni_verificado_en')
    op.drop_column('ficha_reunion', 'dni_verificado_por')
    op.drop_column('ficha_reunion', 'dni_verificado_por_id')
