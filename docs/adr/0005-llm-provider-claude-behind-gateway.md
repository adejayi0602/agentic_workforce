# 0005. LLM provider: Claude behind a gateway

- Status: Accepted
- Date: 2026-11-25
- Spec references: §2 (LLM gateway), §8, §13, §17, §18, FR-026. Supersedes the spec v1.1 §18 default of OpenAI.

## Context

Spec v1.1 proposed OpenAI as the default provider. The product owner has chosen Anthropic Claude as the supported provider. The spec also requires a provider abstraction, token budgets, recorded model versions and no credentials in prompts.

## Decision

- All model calls go through one **LLM gateway** inside the platform. Agents never call a provider SDK directly.
- The supported provider is **Anthropic Claude**, through the official Anthropic SDK. The model is configured per agent version, so it is recorded with each execution (spec §13).
- The gateway interface is provider-neutral (messages, tool definitions, structured output, usage). Adding a provider later means adding an adapter, not changing agents.
- A **fake provider** returns scripted, schema-valid responses. It is the default for local runs and all automated tests, so tests are deterministic and need no API key.
- The gateway enforces per-project budgets before each call and records input and output tokens, model and cost after it (FR-026).
- Structured outputs are validated against the agent's Pydantic result contract. Invalid output counts as a retryable failure, never as a result.
- Credentials and sensitive data are redacted from context before it is sent (spec §13).
- The API key lives in AWS Secrets Manager and is read only by the gateway's process.

## Consequences

- One place to enforce budgets, redaction, logging and retries.
- Tests never depend on a live model.
- Spec v1.1 §18 is updated to name Claude as the provider.
