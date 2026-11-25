# 0010. Temporal hosting

- Status: Proposed (decide before Sprint 7)
- Date: 2026-11-25
- Spec references: §2.1, §18

## Context

Spec §18 leaves Temporal hosting open: managed Temporal Cloud or self-hosted on AWS. Local development and CI don't need the decision. AWS environments do from Sprint 7.

## Decision (so far)

- Local: the official `temporalio/temporal` dev server (`compose.yaml`).
- CI: the Temporal SDK's time-skipping test server.
- AWS: compare before Sprint 7.
  - **Temporal Cloud:** no cluster to operate, mTLS or API-key auth, pay per action.
  - **Self-hosted on ECS:** RDS-backed, full control, but adds upgrades, scaling and on-call.
- Current recommendation: **Temporal Cloud** for the pilot, because there is no operations team, unless data-residency or cost review rules it out.

## Consequences

- Application code is the same either way. Only the connection settings change.
- This ADR moves to Accepted once the product owner confirms.
