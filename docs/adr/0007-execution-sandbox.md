# 0007. Execution sandbox

- Status: Accepted
- Date: 2026-11-25
- Spec references: §12.1, §12.2, §18

## Context

Repository code written or changed by agents is untrusted. It must never run inside the API or a shared, privileged worker.

## Decision

- **Pilot:** each sandbox run is a one-off ECS Fargate task in a dedicated cluster and private subnet.
  - Read-only base image from ECR, pinned by digest. Ephemeral storage only.
  - CPU, memory and wall-clock limits from the manifest. Automatic teardown.
  - No host Docker socket, no instance metadata credentials beyond a minimal task role.
  - Egress allow-listed to the Git provider and package registries only.
  - Short-lived credentials scoped to one repository and one task. No production credentials or data are reachable.
- Sandbox results (test reports, scan output) are written to the evidence bucket and recorded as `test_runs`. The verifier reads them from there.
- **Production / higher risk:** move to microVM-based runners or a dedicated AWS account, decided before handling customer production code.
- Locally, the sandbox runner is replaced by a Docker-based runner with the same interface.

## Consequences

- Strong isolation without managing hosts.
- Fargate start-up adds tens of seconds per run. That is acceptable for test and scan jobs.
