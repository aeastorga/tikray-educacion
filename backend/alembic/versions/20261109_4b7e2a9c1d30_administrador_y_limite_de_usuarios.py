"""Administrador del colegio y límite de usuarios por plan: `rol.es_director` pasa a `es_administrador`
(el rol principal "Director" se llama "Administrador") y `colegio.max_usuarios` (vacío = sin límite).

Revision ID: 4b7e2a9c1d30
Revises: 9ff6e5951cf5
Create Date: 2026-11-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4b7e2a9c1d30'
down_revision: Union[str, Sequence[str], None] = '9ff6e5951cf5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('rol', 'es_director', new_column_name='es_administrador')
    # Solo el rol principal; si el colegio ya tiene otro rol llamado "Administrador", no se toca (único
    # por colegio) y se anota en el PR.
    op.execute("""
        UPDATE rol SET nombre = 'Administrador'
        WHERE es_administrador AND nombre = 'Director'
          AND NOT EXISTS (SELECT 1 FROM rol r2 WHERE r2.colegio_id = rol.colegio_id AND r2.nombre = 'Administrador')
    """)
    op.add_column('colegio', sa.Column('max_usuarios', sa.Integer(), nullable=True))
    op.create_check_constraint(op.f('ck_colegio_max_usuarios_valido'), 'colegio',
                               'max_usuarios IS NULL OR max_usuarios >= 1')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('ck_colegio_max_usuarios_valido'), 'colegio', type_='check')
    op.drop_column('colegio', 'max_usuarios')
    op.execute("""
        UPDATE rol SET nombre = 'Director'
        WHERE es_administrador AND nombre = 'Administrador'
          AND NOT EXISTS (SELECT 1 FROM rol r2 WHERE r2.colegio_id = rol.colegio_id AND r2.nombre = 'Director')
    """)
    op.alter_column('rol', 'es_administrador', new_column_name='es_director')
