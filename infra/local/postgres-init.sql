-- Runs once, when the local Postgres volume is first created.
-- Local-only credentials. In AWS these roles are created by Terraform with secrets from
-- Secrets Manager.
--
-- workforce      schema owner (POSTGRES_USER), used only by Alembic
-- workforce_app  group role the API acts through; owns nothing, subject to RLS
-- workforce_api  the API's login role, a member of workforce_app

CREATE ROLE workforce_app NOLOGIN;
CREATE ROLE workforce_api LOGIN PASSWORD 'workforce_api' IN ROLE workforce_app;

-- The local superuser created by the image is also the schema owner, and superusers bypass
-- row-level security. That is acceptable for migrations only: the API never connects as it.

-- workforce_worker  group role the Temporal workers act through; subject to RLS
-- workforce_worker_login  the workers' login role
CREATE ROLE workforce_worker NOLOGIN;
CREATE ROLE workforce_worker_login LOGIN PASSWORD 'workforce_worker' IN ROLE workforce_worker;
