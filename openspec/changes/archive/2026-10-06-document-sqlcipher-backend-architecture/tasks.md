# Tasks

## 1. Library decision record

- [x] 1.1 Adapt the source ADR into `ARCHITECTURE.md` with library-owned context, decision, alternatives, and consequences; verify it contains no auth-guide-specific API or key-store claim.
- [x] 1.2 Record the Tortoise/SQLCipher connection boundary, SQLite migration-selection constraint, and source-platform evidence; verify every claim is either a package contract or labeled source evidence.

## 2. Consumer-facing scope

- [x] 2.1 Document encrypted SQLite/WAL scope, explicit exclusions, and application-owned key lifecycle responsibilities; verify `ARCHITECTURE.md` distinguishes encryption-at-rest evidence from secret management.
- [x] 2.2 Add package-relevant repository badges to the README and distribution/licence notice guidance to `ARCHITECTURE.md`; verify Markdown links resolve and do not advertise an unimplemented feature.
