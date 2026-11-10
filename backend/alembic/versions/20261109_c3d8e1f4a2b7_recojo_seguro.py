"""Recojo seguro: autorizados permanentes y del día, quién recogió a cada alumno y el módulo contratable
`recojo` (apagado en colegios nuevos, encendido en la demo).

Revision ID: c3d8e1f4a2b7
Revises: 4b7e2a9c1d30
Create Date: 2026-11-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3d8e1f4a2b7'
down_revision: Union[str, Sequence[str], None] = '4b7e2a9c1d30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TIPO_DOC = "tipo_documento IN ('DNI', 'CE', 'PAS', 'OTRO')"


def _fk(columna: str, tabla: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(['colegio_id', columna], [f'{tabla}.colegio_id', f'{tabla}.id'],
                                   ondelete=ondelete)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(op.f('uq_marcacion_colegio_id_id'), 'marcacion', ['colegio_id', 'id'])

    op.create_table(
        'autorizado_recojo',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('colegio_id', sa.Integer(), nullable=False),
        sa.Column('alumno_id', sa.Integer(), nullable=False),
        sa.Column('nombres', sa.String(120), nullable=False),
        sa.Column('apellidos', sa.String(120), nullable=False),
        sa.Column('tipo_documento', sa.String(4), nullable=False),
        sa.Column('numero_documento', sa.String(15), nullable=False),
        sa.Column('parentesco', sa.String(30), nullable=False),
        sa.Column('celular', sa.String(9), nullable=True),
        sa.Column('foto_clave', sa.String(300), nullable=True),
        sa.Column('foto_tipo', sa.String(20), nullable=True),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('origen', sa.String(10), nullable=False),
        sa.Column('creado_por_usuario_id', sa.Integer(), nullable=True),
        sa.Column('creado_por_apoderado_id', sa.Integer(), nullable=True),
        sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(TIPO_DOC, name=op.f('ck_autorizado_recojo_tipo_documento_valido')),
        sa.CheckConstraint("origen IN ('colegio', 'familia')", name=op.f('ck_autorizado_recojo_origen_valido')),
        sa.ForeignKeyConstraint(['colegio_id'], ['colegio.id'], ondelete='CASCADE'),
        _fk('alumno_id', 'alumno', 'CASCADE'),
        _fk('creado_por_usuario_id', 'usuario', 'SET NULL (creado_por_usuario_id)'),
        _fk('creado_por_apoderado_id', 'apoderado', 'SET NULL (creado_por_apoderado_id)'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('colegio_id', 'id'),
    )
    op.create_index('ix_autorizado_recojo_alumno', 'autorizado_recojo', ['colegio_id', 'alumno_id'])

    op.create_table(
        'autorizacion_recojo_dia',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('colegio_id', sa.Integer(), nullable=False),
        sa.Column('alumno_id', sa.Integer(), nullable=False),
        sa.Column('apoderado_id', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('nombres', sa.String(120), nullable=False),
        sa.Column('apellidos', sa.String(120), nullable=False),
        sa.Column('tipo_documento', sa.String(4), nullable=False),
        sa.Column('numero_documento', sa.String(15), nullable=False),
        sa.Column('parentesco', sa.String(30), nullable=False),
        sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
        sa.Column('anulada_en', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(TIPO_DOC, name=op.f('ck_autorizacion_recojo_dia_tipo_documento_valido')),
        sa.ForeignKeyConstraint(['colegio_id'], ['colegio.id'], ondelete='CASCADE'),
        _fk('alumno_id', 'alumno', 'CASCADE'),
        _fk('apoderado_id', 'apoderado', 'CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('colegio_id', 'id'),
    )
    op.create_index('ix_autorizacion_recojo_dia_fecha', 'autorizacion_recojo_dia', ['colegio_id', 'fecha'])

    op.create_table(
        'recojo',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('colegio_id', sa.Integer(), nullable=False),
        sa.Column('marcacion_id', sa.BigInteger(), nullable=False),
        sa.Column('alumno_id', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('momento', sa.DateTime(timezone=True), nullable=False),
        sa.Column('tipo', sa.String(10), nullable=False),
        sa.Column('fuera_de_lista', sa.Boolean(), nullable=False),
        sa.Column('apoderado_id', sa.Integer(), nullable=True),
        sa.Column('autorizado_id', sa.Integer(), nullable=True),
        sa.Column('autorizacion_dia_id', sa.Integer(), nullable=True),
        sa.Column('nombre', sa.String(250), nullable=False),
        sa.Column('tipo_documento', sa.String(4), nullable=False),
        sa.Column('numero_documento', sa.String(15), nullable=False),
        sa.Column('parentesco', sa.String(30), nullable=True),
        sa.Column('registrado_por_id', sa.Integer(), nullable=True),
        sa.Column('recibido_en', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("tipo IN ('apoderado', 'autorizado', 'del_dia', 'otro')",
                           name=op.f('ck_recojo_tipo_valido')),
        sa.ForeignKeyConstraint(['colegio_id'], ['colegio.id'], ondelete='CASCADE'),
        _fk('alumno_id', 'alumno', 'CASCADE'),
        _fk('marcacion_id', 'marcacion', 'CASCADE'),
        _fk('apoderado_id', 'apoderado', 'SET NULL (apoderado_id)'),
        _fk('autorizado_id', 'autorizado_recojo', 'SET NULL (autorizado_id)'),
        _fk('autorizacion_dia_id', 'autorizacion_recojo_dia', 'SET NULL (autorizacion_dia_id)'),
        _fk('registrado_por_id', 'usuario', 'SET NULL (registrado_por_id)'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('colegio_id', 'marcacion_id'),
    )
    op.create_index('ix_recojo_colegio_fecha', 'recojo', ['colegio_id', 'fecha'])

    # Se contrata aparte (no entra en los colegios que ya existen); la demo lo trae encendido.
    op.execute("""
        UPDATE colegio SET modulos_contratados = (modulos_contratados - 'recojo') || '["recojo"]'::jsonb,
                           modulos_apagados = modulos_apagados - 'recojo'
        WHERE es_demo
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
        UPDATE colegio SET modulos_contratados = modulos_contratados - 'recojo',
                           modulos_apagados = modulos_apagados - 'recojo'
    """)
    op.execute("DELETE FROM permiso_rol WHERE modulo = 'recojo'")
    op.drop_index('ix_recojo_colegio_fecha', table_name='recojo')
    op.drop_table('recojo')
    op.drop_index('ix_autorizacion_recojo_dia_fecha', table_name='autorizacion_recojo_dia')
    op.drop_table('autorizacion_recojo_dia')
    op.drop_index('ix_autorizado_recojo_alumno', table_name='autorizado_recojo')
    op.drop_table('autorizado_recojo')
    op.drop_constraint(op.f('uq_marcacion_colegio_id_id'), 'marcacion', type_='unique')
