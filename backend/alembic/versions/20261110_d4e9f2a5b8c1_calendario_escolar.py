"""Calendario escolar: eventos por año escolar y a quién van, aviso "calendario" en la cola (al publicar y
recordatorio del día anterior) y el módulo contratable `calendario` (apagado en colegios nuevos, encendido en
la demo). Los días sin clases siguen en `dia_no_lectivo`.

Revision ID: d4e9f2a5b8c1
Revises: c3d8e1f4a2b7
Create Date: 2026-11-10 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e9f2a5b8c1'
down_revision: Union[str, Sequence[str], None] = 'c3d8e1f4a2b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AVISOS_ANTES = """'{"ingreso": true, "tardanza": true, "falta": true, "salida": true, "cuaderno": true, "cobro": true}'::jsonb"""
AVISOS_AHORA = """'{"ingreso": true, "tardanza": true, "falta": true, "salida": true, "cuaderno": true, "cobro": true, "calendario": true}'::jsonb"""


def _tipos_cola(tipos: str, a_apoderado: str) -> None:
    op.drop_constraint(op.f('ck_cola_aviso_tipo_valido'), 'cola_aviso', type_='check')
    op.drop_constraint(op.f('ck_cola_aviso_tipo_segun_destino'), 'cola_aviso', type_='check')
    op.create_check_constraint(op.f('ck_cola_aviso_tipo_valido'), 'cola_aviso', f"tipo IN ({tipos})")
    op.create_check_constraint(op.f('ck_cola_aviso_tipo_segun_destino'), 'cola_aviso',
                               f"(tipo IN ({a_apoderado})) = (apoderado_id IS NOT NULL)")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('evento_calendario',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('anio_id', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=120), nullable=False),
    sa.Column('descripcion', sa.String(length=1000), nullable=True),
    sa.Column('inicio', sa.Date(), nullable=False),
    sa.Column('fin', sa.Date(), nullable=False),
    sa.Column('hora', sa.Time(), nullable=True),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('alcance', sa.String(length=10), nullable=False),
    sa.Column('avisar', sa.Boolean(), nullable=False),
    sa.Column('aviso_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('recordatorio_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('creado_por_id', sa.Integer(), nullable=True),
    sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('anulado_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('anulado_motivo', sa.String(length=200), nullable=True),
    sa.Column('anulado_por_id', sa.Integer(), nullable=True),
    sa.Column('colegio_id', sa.Integer(), nullable=False),
    sa.CheckConstraint("alcance IN ('colegio', 'niveles', 'secciones')", name=op.f('ck_evento_calendario_alcance_valido')),
    sa.CheckConstraint("tipo IN ('actuacion', 'reunion_padres', 'examen', 'feriado', 'salida', 'otro')", name=op.f('ck_evento_calendario_tipo_valido')),
    sa.CheckConstraint('(anulado_en IS NULL) = (anulado_motivo IS NULL)', name=op.f('ck_evento_calendario_anulado_con_motivo')),
    sa.CheckConstraint('fin >= inicio', name=op.f('ck_evento_calendario_fechas_validas')),
    sa.ForeignKeyConstraint(['colegio_id', 'anio_id'], ['anio_escolar.colegio_id', 'anio_escolar.id'], name=op.f('fk_evento_calendario_colegio_id_anio_id_anio_escolar'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['colegio_id', 'anulado_por_id'], ['usuario.colegio_id', 'usuario.id'], name=op.f('fk_evento_calendario_colegio_id_anulado_por_id_usuario'), ondelete='SET NULL (anulado_por_id)'),
    sa.ForeignKeyConstraint(['colegio_id', 'creado_por_id'], ['usuario.colegio_id', 'usuario.id'], name=op.f('fk_evento_calendario_colegio_id_creado_por_id_usuario'), ondelete='SET NULL (creado_por_id)'),
    sa.ForeignKeyConstraint(['colegio_id'], ['colegio.id'], name=op.f('fk_evento_calendario_colegio_id_colegio'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evento_calendario')),
    sa.UniqueConstraint('colegio_id', 'id', name=op.f('uq_evento_calendario_colegio_id_id'))
    )
    op.create_index('ix_evento_calendario_colegio_fechas', 'evento_calendario', ['colegio_id', 'inicio', 'fin'], unique=False)
    op.create_index(op.f('ix_evento_calendario_colegio_id'), 'evento_calendario', ['colegio_id'], unique=False)
    op.create_table('destino_evento',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('evento_id', sa.Integer(), nullable=False),
    sa.Column('nivel_id', sa.Integer(), nullable=True),
    sa.Column('seccion_id', sa.Integer(), nullable=True),
    sa.Column('colegio_id', sa.Integer(), nullable=False),
    sa.CheckConstraint('(nivel_id IS NULL) <> (seccion_id IS NULL)', name=op.f('ck_destino_evento_un_destino')),
    sa.ForeignKeyConstraint(['colegio_id', 'evento_id'], ['evento_calendario.colegio_id', 'evento_calendario.id'], name=op.f('fk_destino_evento_colegio_id_evento_id_evento_calendario'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['colegio_id', 'nivel_id'], ['nivel.colegio_id', 'nivel.id'], name=op.f('fk_destino_evento_colegio_id_nivel_id_nivel'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['colegio_id', 'seccion_id'], ['seccion.colegio_id', 'seccion.id'], name=op.f('fk_destino_evento_colegio_id_seccion_id_seccion'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['colegio_id'], ['colegio.id'], name=op.f('fk_destino_evento_colegio_id_colegio'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_destino_evento')),
    sa.UniqueConstraint('colegio_id', 'evento_id', 'nivel_id', name=op.f('uq_destino_evento_colegio_id_evento_id_nivel_id')),
    sa.UniqueConstraint('colegio_id', 'evento_id', 'seccion_id', name=op.f('uq_destino_evento_colegio_id_evento_id_seccion_id'))
    )
    op.create_index(op.f('ix_destino_evento_colegio_id'), 'destino_evento', ['colegio_id'], unique=False)

    # Aviso "calendario": va a cada apoderado, como los del cuaderno y de cobro.
    _tipos_cola("'ingreso', 'tarde', 'salida', 'falta', 'cuenta', 'cuaderno', 'cobro', 'calendario'",
                "'cuenta', 'cuaderno', 'cobro', 'calendario'")
    op.alter_column('colegio', 'avisos_tipos', server_default=sa.text(AVISOS_AHORA))
    # Prendido para cuando se use (solo sale con el módulo encendido); se apaga en Configuración › Avisos.
    op.execute("""UPDATE colegio SET avisos_tipos = avisos_tipos || '{"calendario": true}'::jsonb""")
    # Se contrata aparte (no entra en los colegios que ya existen); la demo lo trae encendido.
    op.execute("""
        UPDATE colegio SET modulos_contratados = (modulos_contratados - 'calendario') || '["calendario"]'::jsonb,
                           modulos_apagados = modulos_apagados - 'calendario'
        WHERE es_demo
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
        UPDATE colegio SET modulos_contratados = modulos_contratados - 'calendario',
                           modulos_apagados = modulos_apagados - 'calendario',
                           avisos_tipos = avisos_tipos - 'calendario'
    """)
    op.execute("DELETE FROM permiso_rol WHERE modulo = 'calendario'")
    op.execute("""DELETE FROM entrega_aviso WHERE aviso_id IN (SELECT id FROM cola_aviso WHERE tipo = 'calendario')""")
    op.execute("DELETE FROM cola_aviso WHERE tipo = 'calendario'")
    _tipos_cola("'ingreso', 'tarde', 'salida', 'falta', 'cuenta', 'cuaderno', 'cobro'",
                "'cuenta', 'cuaderno', 'cobro'")
    op.alter_column('colegio', 'avisos_tipos', server_default=sa.text(AVISOS_ANTES))
    op.drop_index(op.f('ix_destino_evento_colegio_id'), table_name='destino_evento')
    op.drop_table('destino_evento')
    op.drop_index(op.f('ix_evento_calendario_colegio_id'), table_name='evento_calendario')
    op.drop_index('ix_evento_calendario_colegio_fechas', table_name='evento_calendario')
    op.drop_table('evento_calendario')
