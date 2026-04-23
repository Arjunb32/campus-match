"""add match pair key

Revision ID: f3a8a0d9a4e2
Revises: 9c4f4c0c7d21
Create Date: 2026-04-23 00:22:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "f3a8a0d9a4e2"
down_revision = "9c4f4c0c7d21"
branch_labels = None
depends_on = None


def column_names(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def build_pair_key(sender_id, receiver_id):
    first_id, second_id = sorted((int(sender_id), int(receiver_id)))
    return f"{first_id}:{second_id}"


def row_priority(row):
    status_rank = {
        "blocked": 4,
        "matched": 3,
        "pending": 2,
        "rejected": 1,
    }
    return (status_rank.get(row.status, 0), row.id)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    match_columns = column_names(inspector, "matches")

    if "pair_key" not in match_columns:
        with op.batch_alter_table("matches", schema=None) as batch_op:
            batch_op.add_column(sa.Column("pair_key", sa.String(length=64), nullable=True))

    rows = bind.execute(
        sa.text(
            """
            SELECT id, sender_id, receiver_id, status
            FROM matches
            ORDER BY id ASC
            """
        )
    ).fetchall()

    grouped = {}
    for row in rows:
        pair_key = build_pair_key(row.sender_id, row.receiver_id)
        grouped.setdefault(pair_key, []).append(row)

    rows_to_delete = []
    for pair_key, group in grouped.items():
        keeper = max(group, key=row_priority)
        bind.execute(
            sa.text("UPDATE matches SET pair_key = :pair_key WHERE id = :id"),
            {"pair_key": pair_key, "id": keeper.id},
        )
        for row in group:
            if row.id != keeper.id:
                rows_to_delete.append(row.id)

    for row_id in rows_to_delete:
        bind.execute(sa.text("DELETE FROM matches WHERE id = :id"), {"id": row_id})

    for row in rows:
        if row.id in rows_to_delete:
            continue
        bind.execute(
            sa.text(
                """
                UPDATE matches
                SET pair_key = :pair_key
                WHERE id = :id AND pair_key IS NULL
                """
            ),
            {
                "pair_key": build_pair_key(row.sender_id, row.receiver_id),
                "id": row.id,
            },
        )

    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.alter_column("pair_key", existing_type=sa.String(length=64), nullable=False)
        batch_op.create_unique_constraint("uq_matches_pair_key", ["pair_key"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    match_columns = column_names(inspector, "matches")

    if "pair_key" not in match_columns:
        return

    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.drop_constraint("uq_matches_pair_key", type_="unique")
        batch_op.drop_column("pair_key")
