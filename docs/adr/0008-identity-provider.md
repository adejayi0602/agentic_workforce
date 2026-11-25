# 0008. Identity provider

- Status: Accepted
- Date: 2026-11-25
- Spec references: §2 (identity integration), §12, §18

## Context

Human users need authentication. Approvals must be bound to authenticated identities (spec §10.3). The platform must not lock itself to one vendor.

## Decision

- **Amazon Cognito** user pools for the pilot, with MFA required for approver roles.
- The platform integrates only through **standard OIDC** (authorisation code flow with PKCE; JWT validation against the issuer's JWKS). Entra ID, Okta or Auth0 can replace Cognito without code changes beyond configuration.
- The identity provider authenticates. **The platform authorises**: roles and memberships live in `organisation_members`, and RBAC is enforced by the API.
- `users.identity_subject` stores the OIDC `sub` claim. Email is informational, not an identifier.
- Agents are not users. They have their own registry identities and never hold human tokens.

## Consequences

- Swapping identity providers later is a configuration change.
- Local development uses a dev-only token issuer, enabled only when `WORKFORCE_ENV=local`.
