"""Named libraries + source→library mapping (#450)

Adds scan_roots.name and scan_roots.is_writable (a "library" is a named,
writable scan root that import can move files into), and the
import_source_mappings table (source root path → destination library).

create_all handles fresh DBs; this migration brings already-stamped DBs to the
same schema. All steps are inspector-guarded so the revision is idempotent and
safe to re-run.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    root_cols = {c["name"] for c in inspector.get_columns("scan_roots")}
    if "name" not in root_cols:
        op.add_column("scan_roots", sa.Column("name", sa.String(), nullable=True))
    if "is_writable" not in root_cols:
        op.add_column(
            "scan_roots",
            sa.Column("is_writable", sa.Boolean(), nullable=False, server_default="0"),
        )

    if "import_source_mappings" not in inspector.get_table_names():
        op.create_table(
            "import_source_mappings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_path", sa.String(), nullable=False),
            sa.Column(
                "library_id",
                sa.Integer(),
                sa.ForeignKey("scan_roots.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("source_path", name="uq_import_source_mappings_source_path"),
        )


def downgrade() -> None:
    op.drop_table("import_source_mappings")
    op.drop_column("scan_roots", "is_writable")
    op.drop_column("scan_roots", "name")
