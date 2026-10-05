# Tasks

## 1. Library decision record

- [ ] 1.1 Adapt the source ADR into `openspec/adr/` with library-owned context, decision, alternatives, and consequences; verify it contains no auth-guide-specific API or key-store claim.
- [ ] 1.2 Record the Tortoise/SQLCipher connection boundary, SQLite migration-selection constraint, and source-platform evidence; verify every claim is either a package contract or labeled source evidence.

## 2. Consumer-facing scope

- [ ] 2.1 Document encrypted SQLite/WAL scope, explicit exclusions, and application-owned key lifecycle responsibilities; verify the ADR distinguishes encryption-at-rest evidence from secret management.
- [ ] 2.2 Add a README cross-reference to the ADR and distribution/licence notice guidance; verify Markdown links resolve and do not advertise an unimplemented feature.
