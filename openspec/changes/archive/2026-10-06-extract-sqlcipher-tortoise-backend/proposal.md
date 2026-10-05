# Proposal

## Why

The proven SQLCipher client remains coupled to the reference authentication
provider. A reusable Tortoise package needs to provide that client and its
runtime contract independently, while retaining the proven encryption and ORM
compatibility boundaries.

## What Changes

- Extract the SQLCipher-backed Tortoise SQLite client into
  `tortoise_sqlcipher`.
- Add the required runtime dependencies: Tortoise ORM, aiosqlite, and
  sqlcipher3, with the versions established by the source proof as lower
  bounds.
- Preserve key-length validation, SQLCipher connection setup, SQLite-client
  behavior, Tortoise exception translation, and the SQLite-containing module
  name required by Tortoise native migrations.
- Make the distribution buildable as an independently installable package.

## Capabilities

### New Capabilities
- `sqlcipher-tortoise-backend`: A Tortoise-compatible SQLCipher SQLite engine
  with explicit encrypted-connection and exception-mapping behavior.

### Modified Capabilities
- None.

## Impact

Adds the package's first runtime dependencies and public backend module. The
reference provider is not changed by this proposal; secret storage, key
generation, backup/rekey workflows, and application-specific policy remain out
of scope.
