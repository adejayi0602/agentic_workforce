# 0011. Web types generated from the API's OpenAPI document

- Status: Accepted
- Date: 2026-11-25
- Spec references: §6
- Refines: ADR-0002 (its "TypeScript types generated from the contracts' JSON Schema" bullet)

## Context

ADR-0002 planned to generate the web app's TypeScript types from the JSON Schema of the
`workforce-contracts` package. In practice most request and response shapes are API models
(projects, organisations, members, audit events). Exporting only the contracts package would
leave the web app hand-writing most types, and hand-written types drift.

## Decision

- The API's OpenAPI document is the contract. `services/api/scripts/export_openapi.py` writes
  it to `packages/contracts/openapi.json`, which is committed.
- The web app generates `src/lib/api-types.ts` from it with `openapi-typescript`
  (`npm run gen:api`). Both files are committed and regenerated together by `make contracts`.
- CI regenerates both and fails if either differs from the committed version.
- Shared Python models still live in `workforce-contracts`, and the API uses them, so they
  appear in the OpenAPI document too.
- The §6.2 error envelope is built by exception handlers, outside response models, so the web
  app keeps one hand-written mirror of it (`ApiErrorBody`).

## Consequences

- Changing an API model without updating the web app's types fails CI.
- Pull requests that change the API show the contract change as a readable JSON diff.
