"""baseline schema

Revision ID: 46850f2d1a15
Revises:
Create Date: 2026-04-22 23:23:49.321159

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "46850f2d1a15"
down_revision = None
branch_labels = None
depends_on = None


def table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def column_names(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def has_unique_constraint(inspector, table_name, expected_columns):
    expected = list(expected_columns)
    for constraint in inspector.get_unique_constraints(table_name):
        if constraint.get("column_names") == expected:
            return True
    return False


def dedupe_single_column_table(connection, table_name, column_name):
    rows = connection.execute(
        sa.text(
            f"""
            SELECT {column_name}
            FROM {table_name}
            GROUP BY {column_name}
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    for row in rows:
        value = row[0]
        duplicate_ids = connection.execute(
            sa.text(
                f"""
                SELECT id
                FROM {table_name}
                WHERE {column_name} = :value
                ORDER BY id DESC
                """
            ),
            {"value": value},
        ).fetchall()
        for duplicate_id in duplicate_ids[1:]:
            connection.execute(
                sa.text(f"DELETE FROM {table_name} WHERE id = :id"),
                {"id": duplicate_id[0]},
            )


def dedupe_user_answers(connection):
    rows = connection.execute(
        sa.text(
            """
            SELECT user_id, question_id
            FROM user_answers
            GROUP BY user_id, question_id
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    for user_id, question_id in rows:
        duplicate_ids = connection.execute(
            sa.text(
                """
                SELECT id
                FROM user_answers
                WHERE user_id = :user_id AND question_id = :question_id
                ORDER BY id DESC
                """
            ),
            {"user_id": user_id, "question_id": question_id},
        ).fetchall()
        for duplicate_id in duplicate_ids[1:]:
            connection.execute(
                sa.text("DELETE FROM user_answers WHERE id = :id"),
                {"id": duplicate_id[0]},
            )


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not table_exists(inspector, "users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("email", sa.String(length=120), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("verification_code", sa.String(length=6), nullable=True),
            sa.Column("verification_code_expires_at", sa.DateTime(), nullable=True),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("is_anonymous", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
        )
    else:
        user_columns = column_names(inspector, "users")
        with op.batch_alter_table("users", schema=None) as batch_op:
            if "verification_code_expires_at" not in user_columns:
                batch_op.add_column(
                    sa.Column("verification_code_expires_at", sa.DateTime(), nullable=True)
                )
            if "verified_at" not in user_columns:
                batch_op.add_column(sa.Column("verified_at", sa.DateTime(), nullable=True))
            if "password_hash" in user_columns:
                batch_op.alter_column(
                    "password_hash",
                    existing_type=sa.String(length=128),
                    type_=sa.String(length=255),
                )

    inspector = sa.inspect(bind)

    if not table_exists(inspector, "questions"):
        op.create_table(
            "questions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("text", sa.String(length=255), nullable=False),
            sa.Column("option_a", sa.String(length=100), nullable=False),
            sa.Column("option_b", sa.String(length=100), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if not table_exists(inspector, "profiles"):
        op.create_table(
            "profiles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("first_name", sa.String(length=50), nullable=False),
            sa.Column("last_name", sa.String(length=50), nullable=False),
            sa.Column("profile_pic", sa.String(length=255), nullable=True),
            sa.Column("gender", sa.String(length=20), nullable=False),
            sa.Column("orientation", sa.String(length=20), nullable=False),
            sa.Column("year_of_study", sa.String(length=20), nullable=False),
            sa.Column("department", sa.String(length=50), nullable=False),
            sa.Column("bio", sa.Text(), nullable=True),
            sa.Column("relationship_goal", sa.String(length=50), nullable=False),
            sa.Column("contact_info", sa.String(length=100), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )
    else:
        profile_columns = column_names(inspector, "profiles")
        if "contact_info" not in profile_columns:
            with op.batch_alter_table("profiles", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column("contact_info", sa.String(length=100), nullable=True)
                )
            bind.execute(
                sa.text(
                    """
                    UPDATE profiles
                    SET contact_info = 'Contact hidden'
                    WHERE contact_info IS NULL
                    """
                )
            )
            with op.batch_alter_table("profiles", schema=None) as batch_op:
                batch_op.alter_column("contact_info", existing_type=sa.String(length=100), nullable=False)
        dedupe_single_column_table(bind, "profiles", "user_id")
        inspector = sa.inspect(bind)
        if not has_unique_constraint(inspector, "profiles", ["user_id"]):
            with op.batch_alter_table("profiles", schema=None) as batch_op:
                batch_op.create_unique_constraint("uq_profiles_user_id", ["user_id"])

    inspector = sa.inspect(bind)

    if not table_exists(inspector, "preferences"):
        op.create_table(
            "preferences",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("pref_gender", sa.String(length=20), nullable=False),
            sa.Column("pref_year", sa.String(length=20), nullable=False),
            sa.Column("pref_vibe", sa.String(length=50), nullable=False),
            sa.Column("pref_hobbies", sa.String(length=100), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )
    else:
        preference_columns = column_names(inspector, "preferences")
        if "pref_hobbies" not in preference_columns:
            with op.batch_alter_table("preferences", schema=None) as batch_op:
                batch_op.add_column(sa.Column("pref_hobbies", sa.String(length=100), nullable=True))
        dedupe_single_column_table(bind, "preferences", "user_id")
        inspector = sa.inspect(bind)
        if not has_unique_constraint(inspector, "preferences", ["user_id"]):
            with op.batch_alter_table("preferences", schema=None) as batch_op:
                batch_op.create_unique_constraint("uq_preferences_user_id", ["user_id"])

    inspector = sa.inspect(bind)

    if not table_exists(inspector, "user_answers"):
        op.create_table(
            "user_answers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("question_id", sa.Integer(), nullable=False),
            sa.Column("my_answer", sa.String(length=100), nullable=False),
            sa.Column("preferred_partner_answer", sa.String(length=100), nullable=False),
            sa.Column("importance_level", sa.Integer(), nullable=False, server_default="5"),
            sa.ForeignKeyConstraint(["question_id"], ["questions.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "question_id", name="uq_user_answers_user_question"),
        )
    else:
        dedupe_user_answers(bind)
        inspector = sa.inspect(bind)
        if not has_unique_constraint(inspector, "user_answers", ["user_id", "question_id"]):
            with op.batch_alter_table("user_answers", schema=None) as batch_op:
                batch_op.create_unique_constraint(
                    "uq_user_answers_user_question", ["user_id", "question_id"]
                )

    inspector = sa.inspect(bind)

    if not table_exists(inspector, "matches"):
        op.create_table(
            "matches",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("sender_id", sa.Integer(), nullable=False),
            sa.Column("receiver_id", sa.Integer(), nullable=False),
            sa.Column("compatibility_score", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["receiver_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["sender_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if table_exists(inspector, "matches"):
        op.drop_table("matches")

    inspector = sa.inspect(bind)
    if table_exists(inspector, "user_answers"):
        op.drop_table("user_answers")

    inspector = sa.inspect(bind)
    if table_exists(inspector, "preferences"):
        op.drop_table("preferences")

    inspector = sa.inspect(bind)
    if table_exists(inspector, "profiles"):
        op.drop_table("profiles")

    inspector = sa.inspect(bind)
    if table_exists(inspector, "questions"):
        op.drop_table("questions")

    inspector = sa.inspect(bind)
    if table_exists(inspector, "users"):
        op.drop_table("users")
