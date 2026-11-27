# 0013. Local and CI object storage: SeaweedFS replaces MinIO

- Status: Accepted
- Date: 2026-11-27
- Spec references: §12 (S3); affects ADR-0012's "MinIO locally"

## Context

The local stack and CI used MinIO as an S3 stand-in. MinIO has withdrawn its community images:
`docker pull minio/minio` now fails with "pull access denied", and the quay.io copy requires an
account and is frozen at a 2025 release with a known, unpatched vulnerability. Our first CI run
of the full document stack failed on exactly this.

## Decision

- Use **SeaweedFS** (`chrislusf/seaweedfs`, version pinned) as the S3 stand-in, in both
  `compose.yaml` and the CI end-to-end job, so local and CI behave the same.
- Buckets are created with the AWS CLI image locally and boto3 in CI. Versioning is requested
  and tolerated if unsupported. Local storage only.
- Local S3 doesn't enforce credentials and allows browser uploads from any origin. That's
  acceptable on a developer machine and in CI, never anywhere else.
- AWS environments use Amazon S3 itself. Nothing in the application depends on which S3
  implementation is behind the endpoint, and the API verifies every upload's size and SHA-256
  itself (ADR-0012), so storage behaviour differences can't weaken that check.

## Consequences

- `make up` works again on a clean machine.
- If SeaweedFS ever lags behind S3 on a feature we need, only the local stack and CI are
  affected, and the stand-in can be swapped without application changes.
