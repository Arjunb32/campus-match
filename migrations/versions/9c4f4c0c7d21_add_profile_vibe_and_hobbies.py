"""add profile vibe and hobbies

Revision ID: 9c4f4c0c7d21
Revises: 46850f2d1a15
Create Date: 2026-04-23 00:08:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "9c4f4c0c7d21"
down_revision = "46850f2d1a15"
branch_labels = None
depends_on = None


def column_names(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    profile_columns = column_names(inspector, "profiles")

    with op.batch_alter_table("profiles", schema=None) as batch_op:
        if "vibe" not in profile_columns:
            batch_op.add_column(sa.Column("vibe", sa.String(length=50), nullable=True))
        if "hobbies" not in profile_columns:
            batch_op.add_column(sa.Column("hobbies", sa.String(length=255), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    profile_columns = column_names(inspector, "profiles")

    with op.batch_alter_table("profiles", schema=None) as batch_op:
        if "hobbies" in profile_columns:
            batch_op.drop_column("hobbies")
        if "vibe" in profile_columns:
            batch_op.drop_column("vibe")
