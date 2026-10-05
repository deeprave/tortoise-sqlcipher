# Design

## Context

The source ADR is scoped to an authentication-provider persistence proof. See
proposal.md for why the library needs a separate record; this design confines
the documentation to reusable package behavior and consumer responsibilities.

## Goals / Non-Goals

**Goals:**
- Preserve the evidence and decisions that make the Tortoise/SQLCipher adapter
  supportable for downstream users.
- Explain encrypted SQLite scope without implying secret-management or
  application-key policy.

**Non-Goals:**
- Recreate the authentication-provider architecture or its administration
  workflows.
- Claim every supported-platform proof before the package suite supplies it.

## Decisions

- Create a library-owned ADR under `openspec/adr/` rather than copying the
  provider ADR verbatim. It will describe the selected Tortoise integration,
  SQLCipher connector boundary, SQLite migration requirement, and known
  platform evidence. This avoids presenting provider-specific key lifecycle as
  library functionality.
- Separate evidence from guarantees. The ADR will describe what encrypted
  database/WAL testing establishes, while clearly assigning key acquisition,
  rotation policy, backup retention, and recovery operations to consuming
  applications.
- Preserve distribution and notice obligations. The ADR will retain the
  sqlcipher3/SQLCipher licensing discussion and require consumers to evaluate
  their product-notice obligations.

## Risks / Trade-offs

- Copying proof claims before this repository executes them → label them as
  source evidence and link follow-up proof coverage.
- Users infer that an encrypted database solves secret management → explicitly
  exclude key generation, storage, and lifecycle policy.
- Tortoise internals change → record the SQLite migration-selection dependency
  and keep the compatibility suite as the release guard.

## Migration Plan

Add the ADR and README cross-reference without changing application data or
requiring consumer migration. Keep provider-specific ADR history in
`auth-guide` as the original source record.
