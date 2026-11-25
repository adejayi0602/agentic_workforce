# 0003. Tenancy and data isolation

- Status: Accepted
- Date: 2026-11-25
- Spec references: FR-025, §5.2, §13, §18 (single-organisation pilot, multi-tenant ready)

## Context

The pilot serves one organisation, but the platform must be multi-tenant ready. Cross-tenant leakage is a top risk (spec §17), and application-level filtering alone fails as soon as one query forgets a `WHERE` clause.

## Decision

- Shared database, shared schema. Every tenant-owned table has a non-null `organisation_id`.
- PostgreSQL row-level security is enabled on every tenant-owned table, in the migration that creates it. Policies compare `organisation_id` with the session setting `app.organisation_id`.
- The API sets `app.organisation_id` at the start of every transaction, from the authenticated membership. The application role cannot bypass RLS. Migrations run under a separate owner role.
- S3 keys are prefixed `org/{organisation_id}/project/{project_id}/…`, and presigned URLs are scoped to a single key.
- Search queries always carry an organisation filter, applied by the retrieval layer, never by the caller.
- Temporal workflow IDs and every task envelope carry `organisation_id`. Activities re-check it before touching data.
- Tests include a cross-tenant suite: data created as organisation A must be invisible to organisation B through every API.

## Consequences

- A forgotten filter returns no rows instead of another tenant's rows.
- Background jobs must set tenant context explicitly. There is no "global" session for application code.
- Moving a large tenant to its own database later remains possible, because tenant ownership is explicit on every row.
