# Threat model (draft for the Sprint 0 workshop)

Status: draft. Review it with the product owner, then revisit at Sprint 9 (guard centre) and Sprint 13 (hardening).

## Assets

- Customer source documents (SRS, briefs) and extracted requirements
- Customer repositories and GitHub App installation access
- AWS deployment credentials and environments (especially production)
- Approval records and the audit trail
- LLM API key and model usage budget
- Tenant boundaries

## Trust boundaries

1. Browser → API (authenticated users)
2. API / workers → LLM provider (data leaves the platform)
3. Uploaded files, repository content and tool output → agents (untrusted content enters prompts)
4. Agents → Tool Gateway (agents request actions; the gateway decides)
5. Tool Gateway → GitHub / AWS (real side effects)
6. Sandbox → everything else (untrusted code runs here)
7. Tenant A ↔ Tenant B

## Top threats and planned controls

| # | Threat | Boundary | Control | Spec / ADR | Sprint |
| --- | --- | --- | --- | --- | --- |
| T1 | Prompt injection in an SRS or repo file makes an agent misuse a tool | 3, 4 | Content treated as data; tool use authorised outside the model by default-deny policy; agents hold no credentials | §13, §10.4, ADR-0006 | 4, 9 |
| T2 | Agent claims work is done when it isn't | 4 | Evidence Verifier re-reads evidence from the system of record; agents can't self-certify | §8.4 | 8, 11 |
| T3 | Approval reused for a different change | 1, 5 | Approval bound to action digest, commit SHA or plan digest, environment and expiry | §10.3 | 5, 9 |
| T4 | Cross-tenant data access | 7 | Row-level security, S3 prefixes, search filters, cross-tenant test suite | ADR-0003 | 1, 13 |
| T5 | Untrusted code escapes the sandbox or reaches production credentials | 6 | Dedicated Fargate cluster, egress allow-list, no production credentials reachable | ADR-0007, §12.2 | 11 |
| T6 | Leaked GitHub or AWS credentials | 5 | GitHub App short-lived tokens, OIDC to AWS, Secrets Manager, redaction in logs | ADR-0006, §11.3 | 10, 12 |
| T7 | Sensitive data sent to the model provider or logs | 2 | Redaction in the LLM gateway; no payloads in logs or metric labels; provider data settings reviewed | ADR-0005, §13 | 4 |
| T8 | Runaway agent loops exhaust budget | 2 | Per-project budgets enforced before each call; max attempts and rework cycles | FR-026, §7.2 | 4, 7 |
| T9 | Duplicate external actions on retry (two PRs, two deploys) | 5 | Idempotency keys, reconciliation, durable activity records | §9.2, ADR-0004 | 7, 10 |
| T10 | Malicious upload (malware, parser exploit) | 1 | Malware scan before parsing; isolated extraction worker; macros ignored | ADR-0009 | 2 |
| T11 | Tampering with the audit trail | all | Append-only audit table; database role without update/delete; CloudTrail | FR-022 | 1, 13 |
| T12 | Forged webhook triggers progression | 5 | Signature verification, idempotent by delivery ID | ADR-0006 | 10 |

## Workshop questions

1. Which data classifications will the pilot handle? Is any of it regulated?
2. Who are the approvers for plan, deployment and closure, and must they use MFA?
3. Which repositories will the pilot GitHub App be installed on?
4. Does the data sent to Anthropic need a zero-retention or regional arrangement?
