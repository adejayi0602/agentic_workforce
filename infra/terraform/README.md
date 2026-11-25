# Infrastructure (Terraform)

Empty until Sprint 1. Planned layout, following spec §12 and ADR-0007:

```
infra/terraform/
  modules/
    network/        VPC, private subnets, VPC endpoints, controlled egress
    data/           RDS PostgreSQL, ElastiCache Redis, S3 buckets (uploads, artefacts, evidence)
    compute/        ECS cluster, services for api and workers, ECR repositories
    sandbox/        separate ECS cluster and subnet for one-off execution tasks
    identity/       Cognito user pool, IAM roles, GitHub OIDC provider
    observability/  CloudWatch log groups, alarms, OpenTelemetry collector
  envs/
    dev/
    staging/
    prod/
```

Rules:

- State in S3 with locking, one state per environment and account.
- GitHub Actions authenticates to AWS through OIDC. No long-lived keys.
- Every `apply` beyond dev runs from a reviewed plan, and approval is bound to the plan digest (spec §11.3).
