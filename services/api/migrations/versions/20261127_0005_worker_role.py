"""worker database role, and column-level update grants on document versions

The worker (execution plane) scans and processes documents. It acts through `workforce_worker`,
which is subject to row-level security like the API: every workflow sets the tenant context
from its input.

Both roles may update only the columns their job needs. Neither can change what a version *is*
(its checksum, size, storage location, uploader). Those are fixed at creation.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

API_VERSION_COLUMNS = "status, uploaded_at, updated_at"
WORKER_VERSION_COLUMNS = "status, scanned_at, scan_result, processed_at, updated_at"


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'workforce_worker') THEN
            CREATE ROLE workforce_worker NOLOGIN;
          END IF;
        END $$;
    """)
    op.execute("GRANT USAGE ON SCHEMA public TO workforce_worker")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app_current_organisation_id(), app_current_user_id() "
        "TO workforce_worker"
    )

    # API: narrow its update on versions to the columns it actually changes.
    op.execute("REVOKE UPDATE ON document_versions FROM workforce_app")
    op.execute(f"GRANT UPDATE ({API_VERSION_COLUMNS}) ON document_versions TO workforce_app")

    # Worker: read what it processes, record results, audit, emit events. Never delete.
    op.execute("GRANT SELECT ON project_documents TO workforce_worker")
    op.execute("GRANT SELECT ON document_versions TO workforce_worker")
    op.execute(f"GRANT UPDATE ({WORKER_VERSION_COLUMNS}) ON document_versions TO workforce_worker")
    op.execute("GRANT SELECT, INSERT, UPDATE ON document_processing_runs TO workforce_worker")
    op.execute("GRANT SELECT, INSERT ON audit_events TO workforce_worker")
    op.execute("GRANT INSERT ON outbox_events TO workforce_worker")


def downgrade() -> None:
    op.execute("REVOKE ALL ON outbox_events FROM workforce_worker")
    op.execute("REVOKE ALL ON audit_events FROM workforce_worker")
    op.execute("REVOKE ALL ON document_processing_runs FROM workforce_worker")
    op.execute("REVOKE ALL ON document_versions FROM workforce_worker")
    op.execute("REVOKE ALL ON project_documents FROM workforce_worker")
    op.execute(
        "REVOKE EXECUTE ON FUNCTION app_current_organisation_id(), app_current_user_id() "
        "FROM workforce_worker"
    )
    op.execute("REVOKE USAGE ON SCHEMA public FROM workforce_worker")
    op.execute(f"REVOKE UPDATE ({API_VERSION_COLUMNS}) ON document_versions FROM workforce_app")
    op.execute("GRANT UPDATE ON document_versions TO workforce_app")
