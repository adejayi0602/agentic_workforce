# Notes for AI coding agents working in this repo

- Read `README.md` and `CONTRIBUTING.md` first. The standards there apply to agent-written code too.
- The source of truth for behaviour is Engineering Specification v1.1. Architecture decisions are in `docs/adr/`. If a change conflicts with an ADR, stop and raise it. Don't work around it.
- Run `make check` before declaring work done. Unit tests must pass without network or Docker.
- Never add credentials, tokens or real customer data to the repo, tests or fixtures.
- Control-plane logic (task state machine, policy engine, manifest compiler, Evidence Verifier) must stay deterministic and must never call an LLM.
- Keep changes scoped to one sprint backlog item per pull request where possible.
