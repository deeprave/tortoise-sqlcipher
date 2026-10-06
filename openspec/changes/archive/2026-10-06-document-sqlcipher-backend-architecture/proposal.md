# Proposal

## Why

The source ADR records decisions for an authentication-provider proof, not a
reusable library. Users of this package need a standalone explanation of the
Tortoise integration, encrypted SQLite boundary, platform evidence, and the
responsibilities that remain with applications.

## What Changes

- Adapt the source SQLCipher persistence ADR into the library-owned
  `ARCHITECTURE.md` document.
- Describe the package's Tortoise-specific engine contract, why stock Tortoise
  SQLite cannot transparently use SQLCipher, and why the backend module keeps
  `sqlite` in its name.
- State encrypted SQLite/WAL guarantees evidenced by the proof and distinguish
  them from secret-management and application key-lifecycle responsibilities.
- Record distribution, licence-notice, platform-evidence, and out-of-scope
  constraints for package consumers.

## Capabilities

This is documentation-only and introduces no runtime requirement changes.

## Impact

Adds library architecture documentation and user-facing README badges. It does not
change code, runtime dependencies, or the public backend behaviour.
