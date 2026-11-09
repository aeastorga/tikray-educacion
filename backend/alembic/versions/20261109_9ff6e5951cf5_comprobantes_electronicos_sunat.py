"""Comprobantes electrónicos SUNAT: configuración por colegio (token cifrado), series con correlativo,
comprobantes de los pagos y cola de emisión y anulación.

Revision ID: 9ff6e5951cf5
Revises: bedf1d4d0ad5
Create Date: 2026-11-09 00:00:14.822542

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9ff6e5951cf5'
down_revision: Union[str, Sequence[str], None] = 'bedf1d4d0ad5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('config_facturacion',
    sa.Column('colegio_id', sa.Integer(), nullable=False),
    sa.Column('emite', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('ruc', sa.String(length=11), nullable=True),
    sa.Column('razon_social', sa.String(length=200), nullable=True),
    sa.Column('serie_boleta', sa.String(length=4), server_default='B001', nullable=False),
    sa.Column('serie_factura', sa.String(length=4), server_default='F001', nullable=False),
    sa.Column('proveedor', sa.String(length=30), server_default='ninguno', nullable=False),
    sa.Column('token_cifrado', sa.Text(), nullable=True),
    sa.CheckConstraint("ruc IS NULL OR ruc ~ '^[0-9]{11}$'", name=op.f('ck_config_facturacion_ruc_valido')),
    sa.CheckConstraint("serie_boleta ~ '^B[0-9A-Z]{3}$'", name=op.f('ck_config_facturacion_serie_boleta_valida')),
    sa.CheckConstraint("serie_factura ~ '^F[0-9A-Z]{3}$'", name=op.f('ck_config_facturacion_serie_factura_valida')),
    sa.CheckConstraint('NOT emite OR (ruc IS NOT NULL AND razon_social IS NOT NULL)', name=op.f('ck_config_facturacion_emite_con_datos')),
    sa.ForeignKeyConstraint(['colegio_id'], ['colegio.id'], name=op.f('fk_config_facturacion_colegio_id_colegio'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('colegio_id', name=op.f('pk_config_facturacion'))
    )
    op.create_table('serie_comprobante',
    sa.Column('colegio_id', sa.Integer(), nullable=False),
    sa.Column('serie', sa.String(length=4), nullable=False),
    sa.Column('ultimo', sa.Integer(), server_default='0', nullable=False),
    sa.CheckConstraint('ultimo >= 0', name=op.f('ck_serie_comprobante_ultimo_no_negativo')),
    sa.ForeignKeyConstraint(['colegio_id'], ['colegio.id'], name=op.f('fk_serie_comprobante_colegio_id_colegio'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('colegio_id', 'serie', name=op.f('pk_serie_comprobante'))
    )
    op.create_table('comprobante',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('pago_id', sa.BigInteger(), nullable=False),
    sa.Column('tipo', sa.String(length=10), nullable=False),
    sa.Column('serie', sa.String(length=4), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('cliente_tipo_documento', sa.String(length=4), nullable=False),
    sa.Column('cliente_numero_documento', sa.String(length=20), nullable=False),
    sa.Column('cliente_nombre', sa.String(length=200), nullable=False),
    sa.Column('gravado', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('inafecto', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('igv', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('total', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('estado', sa.String(length=10), server_default='pendiente', nullable=False),
    sa.Column('respuesta', sa.Text(), nullable=True),
    sa.Column('enlace_pdf', sa.String(length=500), nullable=True),
    sa.Column('enlace_xml', sa.String(length=500), nullable=True),
    sa.Column('enlace_cdr', sa.String(length=500), nullable=True),
    sa.Column('intentos', sa.Integer(), server_default='0', nullable=False),
    sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('anulado_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('colegio_id', sa.Integer(), nullable=False),
    sa.CheckConstraint("estado IN ('pendiente', 'enviado', 'aceptado', 'rechazado', 'anulado')", name=op.f('ck_comprobante_estado_valido')),
    sa.CheckConstraint("tipo <> 'factura' OR (cliente_tipo_documento = 'RUC' AND cliente_numero_documento ~ '^[0-9]{11}$')", name=op.f('ck_comprobante_factura_con_ruc')),
    sa.CheckConstraint("tipo IN ('boleta', 'factura')", name=op.f('ck_comprobante_tipo_valido')),
    sa.CheckConstraint('gravado >= 0 AND inafecto >= 0 AND igv >= 0', name=op.f('ck_comprobante_montos_no_negativos')),
    sa.CheckConstraint('intentos >= 0', name=op.f('ck_comprobante_intentos_no_negativos')),
    sa.CheckConstraint('numero > 0', name=op.f('ck_comprobante_numero_positivo')),
    sa.CheckConstraint('total = gravado + inafecto + igv', name=op.f('ck_comprobante_total_cuadra')),
    sa.ForeignKeyConstraint(['colegio_id', 'pago_id'], ['pago.colegio_id', 'pago.id'], name=op.f('fk_comprobante_colegio_id_pago_id_pago'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['colegio_id'], ['colegio.id'], name=op.f('fk_comprobante_colegio_id_colegio'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_comprobante')),
    sa.UniqueConstraint('colegio_id', 'id', name=op.f('uq_comprobante_colegio_id_id')),
    sa.UniqueConstraint('colegio_id', 'pago_id', name=op.f('uq_comprobante_colegio_id_pago_id')),
    sa.UniqueConstraint('colegio_id', 'serie', 'numero', name=op.f('uq_comprobante_colegio_id_serie_numero'))
    )
    op.create_index(op.f('ix_comprobante_colegio_id'), 'comprobante', ['colegio_id'], unique=False)
    op.create_table('cola_comprobante',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('comprobante_id', sa.BigInteger(), nullable=False),
    sa.Column('accion', sa.String(length=10), nullable=False),
    sa.Column('motivo', sa.String(length=200), nullable=True),
    sa.Column('estado', sa.String(length=10), server_default='pendiente', nullable=False),
    sa.Column('intentos', sa.Integer(), server_default='0', nullable=False),
    sa.Column('procesar_desde', sa.DateTime(timezone=True), nullable=False),
    sa.Column('procesado_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.Column('datos', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('colegio_id', sa.Integer(), nullable=False),
    sa.CheckConstraint("(accion = 'anular') = (motivo IS NOT NULL)", name=op.f('ck_cola_comprobante_anular_con_motivo')),
    sa.CheckConstraint("accion IN ('emitir', 'anular')", name=op.f('ck_cola_comprobante_accion_valida')),
    sa.CheckConstraint("estado IN ('pendiente', 'hecho', 'error')", name=op.f('ck_cola_comprobante_estado_valido')),
    sa.ForeignKeyConstraint(['colegio_id', 'comprobante_id'], ['comprobante.colegio_id', 'comprobante.id'], name=op.f('fk_cola_comprobante_colegio_id_comprobante_id_comprobante'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['colegio_id'], ['colegio.id'], name=op.f('fk_cola_comprobante_colegio_id_colegio'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cola_comprobante')),
    sa.UniqueConstraint('colegio_id', 'comprobante_id', 'accion', name=op.f('uq_cola_comprobante_colegio_id_comprobante_id_accion')),
    sa.UniqueConstraint('colegio_id', 'id', name=op.f('uq_cola_comprobante_colegio_id_id'))
    )
    op.create_index(op.f('ix_cola_comprobante_colegio_id'), 'cola_comprobante', ['colegio_id'], unique=False)
    op.create_index('ix_cola_comprobante_pendientes', 'cola_comprobante', ['procesar_desde'], unique=False, postgresql_where=sa.text("estado = 'pendiente'"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_cola_comprobante_pendientes', table_name='cola_comprobante', postgresql_where=sa.text("estado = 'pendiente'"))
    op.drop_index(op.f('ix_cola_comprobante_colegio_id'), table_name='cola_comprobante')
    op.drop_table('cola_comprobante')
    op.drop_index(op.f('ix_comprobante_colegio_id'), table_name='comprobante')
    op.drop_table('comprobante')
    op.drop_table('serie_comprobante')
    op.drop_table('config_facturacion')
