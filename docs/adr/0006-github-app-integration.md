# 0006. GitHub App integration

- Status: Accepted
- Date: 2026-11-25
- Spec references: §11.1, FR-016, FR-017

## Context

Engineering agents must inspect repositories, create branches and open pull requests, without broad or long-lived credentials and without ever seeing a token.

## Decision

- Integrate through a **GitHub App** installed per organisation. No personal access tokens.
- Default permissions are read-only (contents, metadata, pull requests, checks). Write access to contents and pull requests is requested only for workflows whose approved manifest allows it.
- The Tool Gateway mints short-lived installation tokens per action. Tokens are never placed in prompts, logs or artefacts.
- Agents work only on task-scoped branches named `workforce/{task_key}`. Pushing to protected branches and merging are denied by policy.
- Pull requests include requirement IDs, task IDs, a change summary, test evidence and risk notes.
- Webhooks are verified by signature before processing, and processing is idempotent by delivery ID.
- CI results are read from GitHub checks, not taken from the agent's own claims (spec §8.4).

## Consequences

- A leaked token is short-lived and scoped to one installation.
- Each customer organisation must install the App and grant repository access.
