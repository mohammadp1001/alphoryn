# ADR 0002 — Single GCP service account

**Status:** Accepted

## Context

The execution agent is the only agent that should hold the Alpaca execution API key. Proper IAM isolation would use separate service accounts: one for the execution agent (with Secret Manager access to the execution secret) and one for everything else (no access). This makes the isolation enforceable at the infra level.

## Decision

A single GCP service account is used for the entire system. The execution secret is injected as environment variables by the coordinator harness at execution-agent spawn time. The key is never logged, stored on `PlanState`, or passed to other subagents — enforced by code convention, not IAM.

## Alternatives considered

**Separate service accounts per agent** — execution agent gets its own account with scoped IAM binding to the execution secret. All other agents cannot access that secret even if compromised. Rejected for demo scope: managing multiple service accounts, workload identity bindings, and least-privilege IAM policies is meaningful infra overhead that doesn't add learning value for a single-user paper trading system.

## Consequences

- Secret isolation is a code-level guarantee, not an infra-level one
- If the coordinator harness has a bug that logs env vars, the key leaks — mitigate with a log-scrubbing hook
- Upgrading to per-agent service accounts later requires only IAM changes, not code changes (the injection pattern stays the same)
