# 0001. Record decisions; Claude builds, owner reviews

- Status: Accepted
- Date: 2026-11-25
- Spec references: §18, §20

## Context

The platform is built by Claude (as an AI coding agent) for a product owner, who reviews and merges the work. There is no wider human engineering team at this stage. Decisions made in chat are lost unless they're written down next to the code, and an agent starting a new session needs the same context a new engineer would.

## Decision

- Significant architecture decisions are recorded as ADRs in `docs/adr/`.
- Claude implements each sprint backlog item on its own branch and opens a pull request. The product owner reviews and merges. Claude never merges its own pull requests.
- CI must pass before a pull request is merged. `main` is protected.
- `CLAUDE.md` at the repo root holds standing instructions for any agent working in the repo.
- When a request conflicts with an ADR, the agent stops and raises it rather than working around it.

## Consequences

- The product owner is the approval gate for code, mirroring the platform's own human-accountability principle.
- ADRs stay short. Ceremony is kept low because there is one reviewer.
- If other engineers join later, this ADR is superseded with a team review process.
