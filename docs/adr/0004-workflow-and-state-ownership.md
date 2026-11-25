# 0004. Workflow and state ownership

- Status: Accepted
- Date: 2026-11-25
- Spec references: §2.2, §5.2, §9, §10.1, §8.4

## Context

Temporal and PostgreSQL both hold state. If both can decide what a task's status is, they will drift apart, and replays or retries could duplicate side effects.

## Decision

- **Temporal owns progression**: what runs next, timers, retries, waiting for approvals and clarifications.
- **PostgreSQL owns business state**: requirements, manifests, tasks and their status, approvals, evidence and audit. It is the system of record, and the dashboard reads only from it.
- **Only the task state service changes task status**, and only along the spec §10.1 transition table. Workflow code calls it through an activity. Each change writes a `task_transitions` row and an audit event in the same transaction.
- **Only the Evidence Verifier moves a task out of VERIFYING** (spec §8.4).
- Domain events leave PostgreSQL through a transactional outbox. Consumers are idempotent.
- Workflow code is deterministic. All I/O happens in activities with idempotency keys. External effects (GitHub, AWS) use idempotency keys or reconciliation.
- A running workflow pins its manifest version and checksum at start.
- Redis is never a source of truth.

## Consequences

- If Temporal history is lost, business state survives. Workflows can be reconciled from PostgreSQL.
- Every status change is explainable from `task_transitions`.
- A little more code: status changes go through an activity rather than a direct write.
