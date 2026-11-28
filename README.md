# Agentic IT Project Management Workforce

A manifest-driven, multi-agent IT delivery platform. Project inputs (SRS documents, briefs) become structured, traceable requirements, then an approved plan and a pinned workflow manifest. Specialist agents run under deterministic policy, approval and evidence controls, from requirements through release.

The build specification is **Engineering Specification v1.1** (kept in the Claude project alongside this repo). The decisions taken from it are recorded in [`docs/adr/`](docs/adr/).

> Status: **Sprint 0 – runnable skeleton.** Nothing here is production-ready, security-certified or deployed.

**LLM provider:** Anthropic Claude, behind the provider abstraction in the LLM gateway (ADR-0005).
**Delivery model:** Claude writes the code, and the product owner reviews and merges every pull request (ADR-0001).

## Repository layout

| Path | What it is |
| --- | --- |
| `apps/web` | Next.js + TypeScript web app (dashboard, Manifest Studio, approval centre) |
| `services/api` | FastAPI modular monolith: business APIs, tenant context, validation |
| `services/workers` | Temporal workers: durable workflows and activities |
| `packages/contracts` | Shared Pydantic models (error model, IDs, later: requirement, task, manifest and agent contracts) |
| `infra/terraform` | AWS infrastructure (from Sprint 1 onward) |
| `docs/adr` | Architecture decision records |
| `docs/threat-model.md` | Threat model draft for the Sprint 0 workshop |
| `compose.yaml` | Local stack: PostgreSQL, Temporal dev server, MinIO (S3), Redis |

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22+ and npm
- Docker with Compose v2 (for the local stack)

## Quick start

```bash
cp .env.example .env
make setup          # install Python and web dependencies
make up             # start Postgres, Temporal, MinIO and Redis
make migrate        # apply database migrations (as the schema owner)
make api            # FastAPI on http://localhost:8000  (docs at /docs)
make worker         # Temporal worker on task queue "workforce-main"
make web            # Next.js on http://localhost:3000
```

Temporal UI: http://localhost:8233 · MinIO console: http://localhost:9001

## Checks

```bash
make lint           # ruff + mypy + web lint/typecheck
make test           # pytest unit tests (no network or Docker needed)
make test-integration  # database and Temporal tests (needs `make up`, or CI)
make e2e               # browser tests: sign-in → organisation → projects → audit (needs `make up && make migrate`)
make check          # everything CI runs
```

## Ground rules

These come straight from the spec and are non-negotiable in code review:

1. LLM output is untrusted input. Validate it against typed schemas before acting on it.
2. Agents never hold credentials. Every external action goes through the Tool Gateway.
3. Only the task state service changes task status, and only along the §10.1 transition table.
4. A task completes only when the Evidence Verifier passes every acceptance criterion.
5. Every tenant-owned row carries `organisation_id` and is protected by row-level security.
6. No secrets in code, manifests, logs, prompts or artefacts.

See [CONTRIBUTING.md](CONTRIBUTING.md) for coding standards.
