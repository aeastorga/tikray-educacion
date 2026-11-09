"""Correcciones de caja y pensiones: casilla del rol para anular pagos y gastos pasados, responsable de pago
marcado en todos los alumnos y pensiones/caja contratados aparte (fuera de la demo).

Revision ID: bedf1d4d0ad5
Revises: 8319188332ef
Create Date: 2026-11-06 02:05:08.912560

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bedf1d4d0ad5'
down_revision: Union[str, Sequence[str], None] = '8319188332ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('rol', sa.Column('puede_anular_caja', sa.Boolean(), server_default='false', nullable=False))

    # Ningún alumno sin responsable de pago: el vínculo de apoderado_id menor.
    op.execute("""
        UPDATE alumno_apoderado v SET responsable_pago = true
        FROM (SELECT colegio_id, alumno_id, min(apoderado_id) AS apoderado_id
              FROM alumno_apoderado
              GROUP BY colegio_id, alumno_id
              HAVING NOT bool_or(responsable_pago)) p
        WHERE v.colegio_id = p.colegio_id AND v.alumno_id = p.alumno_id AND v.apoderado_id = p.apoderado_id
    """)

    # Pensiones y caja se contratan aparte: un colegio nuevo nace sin ellos.
    op.alter_column('colegio', 'modulos_contratados', server_default=sa.text(
        """'["asistencia", "cuaderno", "familias", "reuniones"]'::jsonb"""))
    op.execute("""
        UPDATE colegio SET modulos_contratados = modulos_contratados - 'pensiones' - 'caja',
                           modulos_apagados = modulos_apagados - 'pensiones' - 'caja'
        WHERE NOT es_demo
    """)
    # La demo los mantiene contratados y encendidos.
    op.execute("""
        UPDATE colegio SET
          modulos_contratados = (modulos_contratados - 'pensiones' - 'caja') || '["pensiones", "caja"]'::jsonb,
          modulos_apagados = modulos_apagados - 'pensiones' - 'caja'
        WHERE es_demo
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Vuelve al estado anterior: lo que no está contratado queda contratado pero apagado (lo que ya estaba
    # contratado no cambia). Las marcas de responsable de pago se quedan (son válidas en el esquema anterior).
    for m in ("pensiones", "caja"):
        op.execute(f"""
            UPDATE colegio SET modulos_contratados = modulos_contratados || '["{m}"]'::jsonb,
                               modulos_apagados = (modulos_apagados - '{m}') || '["{m}"]'::jsonb
            WHERE NOT (modulos_contratados ? '{m}')
        """)
    op.alter_column('colegio', 'modulos_contratados', server_default=sa.text(
        """'["asistencia", "cuaderno", "familias", "reuniones", "pensiones", "caja"]'::jsonb"""))
    op.drop_column('rol', 'puede_anular_caja')
