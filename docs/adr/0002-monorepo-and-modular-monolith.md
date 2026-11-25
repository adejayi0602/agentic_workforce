# 0002. Monorepo and modular monolith

- Status: Accepted
- Date: 2026-11-25
- Spec references: §2, §2.1

## Context

The spec calls for a FastAPI modular monolith, Temporal workers, a Next.js app and shared typed contracts. These change together, especially the contracts between API, workers and web.

## Decision

- One repository with `apps/web`, `services/api`, `services/workers`, `packages/contracts` and `infra/terraform`.
- Python packages form a single uv workspace with one lock file.
- The API is a modular monolith: modules (projects, documents, requirements, manifests, approvals, audit and so on) live in one deployable but communicate through explicit service interfaces, not each other's tables.
- Shared payload definitions live in `packages/contracts` as Pydantic models. TypeScript types for the web app are generated from their JSON Schema, starting in Sprint 1.

## Consequences

- One pull request can change a contract and every consumer at once, with one CI run.
- The API and workers deploy as separate images from the same repo, so they scale independently (spec §4 Scalability).
- Module boundaries are enforced by convention and review, not by the network. A module can be extracted into its own service later if load requires it.
