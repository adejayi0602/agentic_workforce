"""let a validated token find its own user row

The API resolves a bearer token to a user before it knows the user's id. This migration lets
the users_select policy also match the row whose (identity_issuer, identity_subject) equals the
transaction-local `app.identity_issuer` / `app.identity_subject`, which the API sets only from a
token that has passed signature, issuer, audience and expiry checks.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION app_current_identity_issuer() RETURNS text
        LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.identity_issuer', true), '') $$
    """)
    op.execute("""
        CREATE FUNCTION app_current_identity_subject() RETURNS text
        LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.identity_subject', true), '') $$
    """)
    op.execute(
        "GRANT EXECUTE ON FUNCTION app_current_identity_issuer(), app_current_identity_subject() "
        "TO workforce_app"
    )
    op.execute("DROP POLICY users_select ON users")
    op.execute("""
        CREATE POLICY users_select ON users FOR SELECT USING (
          id = app_current_user_id()
          OR (identity_issuer = app_current_identity_issuer()
              AND identity_subject = app_current_identity_subject())
          OR EXISTS (SELECT 1 FROM organisation_members m
                     WHERE m.user_id = users.id
                       AND m.organisation_id = app_current_organisation_id())
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY users_select ON users")
    op.execute("""
        CREATE POLICY users_select ON users FOR SELECT USING (
          id = app_current_user_id()
          OR EXISTS (SELECT 1 FROM organisation_members m
                     WHERE m.user_id = users.id
                       AND m.organisation_id = app_current_organisation_id())
        )
    """)
    op.execute("DROP FUNCTION app_current_identity_subject()")
    op.execute("DROP FUNCTION app_current_identity_issuer()")
