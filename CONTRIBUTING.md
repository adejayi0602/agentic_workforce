# Contributing and coding standards

## Workflow

- Branch from `main` using `type/short-description`, for example `feat/manifest-compiler` or `fix/upload-checksum`.
- Use [Conventional Commits](https://www.conventionalcommits.org/) for messages: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- Every change goes through a pull request with green CI. `main` is protected.
- Reference the spec section or requirement ID (for example `FR-013`, `§10.1`) in the PR description when it applies.
- A change to an architectural decision needs a new ADR (or a superseding one) in `docs/adr/`.

## Python (`services/*`, `packages/*`)

- Python 3.12+, managed as a uv workspace from the repo root.
- Formatting and linting: `ruff format` and `ruff check` (config in the root `pyproject.toml`).
- Types: `mypy --strict` on all source packages. Public functions are fully typed.
- Models: Pydantic v2. API request and response bodies are always Pydantic models, never raw dicts.
- Errors: raise `ApiError` with a code from `workforce_contracts.errors.ErrorCode`. Clients only ever see the spec §6.2 error envelope.
- Deterministic control logic (state machine, policy, manifest compiler, verifier) is written as pure functions with exhaustive unit tests. No LLM calls in these modules.
- Temporal workflow code must be deterministic: no I/O, clocks, randomness or network in workflows. Side effects belong in activities, with idempotency keys.
- Tests: `pytest`. Unit tests must not need network or Docker. Tests that do are marked `@pytest.mark.integration`.

## TypeScript (`apps/web`)

- Strict TypeScript. No `any` without a comment explaining why.
- ESLint (Next.js config) must pass, and so must `tsc --noEmit`.
- API types come from `src/lib/api-types.ts`, generated from the API's OpenAPI document. Never hand-write a type the API already defines. After changing an API model, run `make contracts` and commit both generated files (ADR-0011).
- The browser never talks to Temporal, the database or S3 directly. It talks only to the API (presigned S3 URLs excepted).

## Database

- All schema changes are Alembic migrations in `services/api/migrations`. Never edit an applied migration.
- UUID primary keys and `timestamptz` (UTC) columns.
- Every tenant-owned table has `organisation_id` and a row-level security policy in the same migration that creates it.
- Version records (manifests, templates, approved requirements, release evidence) are immutable. Corrections create a new version.

## Security

- Never commit secrets. `.env` is git-ignored; `.env.example` holds safe placeholders only.
- Treat SRS files, repository content and tool output as untrusted data, never as instructions.
- Log correlation IDs, not payloads. No secrets or raw document content in logs or metric labels.
