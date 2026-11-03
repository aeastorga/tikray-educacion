"""Modo reunión: reuniones de padres con QR por aula y fichas del apoderado.

Revision ID: f523881eb9f1
Revises: 17b5692068c9
Create Date: 2026-11-03 09:46:10.902515

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f523881eb9f1'
down_revision: Union[str, Sequence[str], None] = '17b5692068c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # La ficha apunta al enlace de activación (llave compuesta con colegio_id): primero la llave única.
    op.add_column('invitacion_familia', sa.Column('presencial', sa.Boolean(), server_default='false', nullable=False))
    op.create_unique_constraint(op.f('uq_invitacion_familia_colegio_id_id'), 'invitacion_familia', ['colegio_id', 'id'])
    op.create_table('reunion_padres',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('seccion_id', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=120), nullable=False),
    sa.Column('nonce', sa.String(length=32), nullable=False),
    sa.Column('creado_por_id', sa.Integer(), nullable=True),
    sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('vence_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('cerrada_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('intentos_fallidos', sa.Integer(), server_default='0', nullable=False),
    sa.Column('colegio_id', sa.Integer(), nullable=False),
    sa.CheckConstraint("vence_en <= creado_en + interval '12 hours'", name=op.f('ck_reunion_padres_vigencia_maxima')),
    sa.CheckConstraint('vence_en > creado_en', name=op.f('ck_reunion_padres_vence_despues')),
    sa.ForeignKeyConstraint(['colegio_id', 'creado_por_id'], ['usuario.colegio_id', 'usuario.id'], name=op.f('fk_reunion_padres_colegio_id_creado_por_id_usuario'), ondelete='SET NULL (creado_por_id)'),
    sa.ForeignKeyConstraint(['colegio_id', 'seccion_id'], ['seccion.colegio_id', 'seccion.id'], name=op.f('fk_reunion_padres_colegio_id_seccion_id_seccion'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['colegio_id'], ['colegio.id'], name=op.f('fk_reunion_padres_colegio_id_colegio'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reunion_padres')),
    sa.UniqueConstraint('colegio_id', 'id', name=op.f('uq_reunion_padres_colegio_id_id'))
    )
    op.create_index(op.f('ix_reunion_padres_colegio_id'), 'reunion_padres', ['colegio_id'], unique=False)
    op.create_table('ficha_reunion',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('reunion_id', sa.Integer(), nullable=False),
    sa.Column('alumno_id', sa.Integer(), nullable=False),
    sa.Column('origen', sa.String(length=10), nullable=False),
    sa.Column('datos', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('documento', sa.String(length=15), nullable=False),
    sa.Column('consentimiento_version', sa.String(length=20), nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('token_hash', sa.String(length=64), nullable=True),
    sa.Column('estado', sa.String(length=10), nullable=False),
    sa.Column('apoderado_id', sa.Integer(), nullable=True),
    sa.Column('otro_apoderado_id', sa.Integer(), nullable=True),
    sa.Column('invitacion_id', sa.Integer(), nullable=True),
    sa.Column('revisado_por_id', sa.Integer(), nullable=True),
    sa.Column('revisado_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('motivo_rechazo', sa.String(length=200), nullable=True),
    sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('colegio_id', sa.Integer(), nullable=False),
    sa.CheckConstraint("estado = 'pendiente' OR revisado_en IS NOT NULL", name=op.f('ck_ficha_reunion_revisada_con_fecha')),
    sa.CheckConstraint("estado IN ('pendiente', 'aprobada', 'rechazada')", name=op.f('ck_ficha_reunion_estado_valido')),
    sa.CheckConstraint("origen IN ('celular', 'quiosco', 'papel')", name=op.f('ck_ficha_reunion_origen_valido')),
    sa.ForeignKeyConstraint(['colegio_id', 'alumno_id'], ['alumno.colegio_id', 'alumno.id'], name=op.f('fk_ficha_reunion_colegio_id_alumno_id_alumno'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['colegio_id', 'apoderado_id'], ['apoderado.colegio_id', 'apoderado.id'], name=op.f('fk_ficha_reunion_colegio_id_apoderado_id_apoderado'), ondelete='SET NULL (apoderado_id)'),
    sa.ForeignKeyConstraint(['colegio_id', 'invitacion_id'], ['invitacion_familia.colegio_id', 'invitacion_familia.id'], name=op.f('fk_ficha_reunion_colegio_id_invitacion_id_invitacion_familia'), ondelete='SET NULL (invitacion_id)'),
    sa.ForeignKeyConstraint(['colegio_id', 'otro_apoderado_id'], ['apoderado.colegio_id', 'apoderado.id'], name=op.f('fk_ficha_reunion_colegio_id_otro_apoderado_id_apoderado'), ondelete='SET NULL (otro_apoderado_id)'),
    sa.ForeignKeyConstraint(['colegio_id', 'reunion_id'], ['reunion_padres.colegio_id', 'reunion_padres.id'], name=op.f('fk_ficha_reunion_colegio_id_reunion_id_reunion_padres'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['colegio_id', 'revisado_por_id'], ['usuario.colegio_id', 'usuario.id'], name=op.f('fk_ficha_reunion_colegio_id_revisado_por_id_usuario'), ondelete='SET NULL (revisado_por_id)'),
    sa.ForeignKeyConstraint(['colegio_id'], ['colegio.id'], name=op.f('fk_ficha_reunion_colegio_id_colegio'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ficha_reunion')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_ficha_reunion_token_hash'))
    )
    op.create_index(op.f('ix_ficha_reunion_colegio_id'), 'ficha_reunion', ['colegio_id'], unique=False)
    op.create_index('ix_ficha_reunion_reunion', 'ficha_reunion', ['colegio_id', 'reunion_id', 'estado'], unique=False)
    # Cambios del padrón hechos al aprobar una ficha de la reunión.
    op.drop_constraint(op.f('ck_cambio_apoderado_origen_valido'), 'cambio_apoderado', type_='check')
    op.create_check_constraint(op.f('ck_cambio_apoderado_origen_valido'), 'cambio_apoderado',
                               "origen IN ('excel', 'panel', 'familia', 'reunion')")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM cambio_apoderado WHERE origen = 'reunion'")
    op.drop_constraint(op.f('ck_cambio_apoderado_origen_valido'), 'cambio_apoderado', type_='check')
    op.create_check_constraint(op.f('ck_cambio_apoderado_origen_valido'), 'cambio_apoderado',
                               "origen IN ('excel', 'panel', 'familia')")
    op.drop_index('ix_ficha_reunion_reunion', table_name='ficha_reunion')
    op.drop_index(op.f('ix_ficha_reunion_colegio_id'), table_name='ficha_reunion')
    op.drop_table('ficha_reunion')
    op.drop_index(op.f('ix_reunion_padres_colegio_id'), table_name='reunion_padres')
    op.drop_table('reunion_padres')
    op.drop_constraint(op.f('uq_invitacion_familia_colegio_id_id'), 'invitacion_familia', type_='unique')
    op.drop_column('invitacion_familia', 'presencial')
