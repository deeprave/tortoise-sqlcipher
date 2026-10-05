# Design

## Context

See proposal.md and the `sqlcipher-tortoise-backend` delta for motivation and
behavior. The source proof subclasses Tortoise's SQLite client, wraps a
sqlcipher3 connector in aiosqlite, and relies on a module name containing
`sqlite` for native migration schema-editor selection.

## Goals / Non-Goals

**Goals:**
- Move the reusable engine into a Python 3.11-compatible package module.
- Preserve Tortoise SQLite-client behavior while replacing only the underlying
  DB-API connection.

**Non-Goals:**
- Design application key acquisition or rotation policy.
- Expose backup/rekey helpers as library API in this change.

## Decisions

- Place the engine in `tortoise_sqlcipher.sqlite_sqlcipher`. The `sqlite`
  module segment is intentional: Tortoise uses the client module name to choose
  its SQLite migration schema editor.
- Keep the source client's narrow override: create an aiosqlite connection
  around `sqlcipher3.dbapi2`, set the SQLCipher key before other operations,
  replay SQLite pragmas, then use Tortoise's normal post-connect behavior.
  This avoids an ORM patch or a separate persistence abstraction.
- Replace the source's Python 3.12 type-parameter syntax with
  `ParamSpec`/`TypeVar`, retaining the exception-translating decorator under
  the Python 3.11 baseline.
- Declare `tortoise-orm>=1.1.8`, `aiosqlite>=0.22.1`, and `sqlcipher3>=0.6.3`
  as runtime dependencies. These are the proof's known-compatible floors;
  wider compatibility is not claimed without tests.

## Risks / Trade-offs

- Tortoise internal behavior changes across releases → keep lower bounds from
  the proof and let the proof-suite change establish supported versions.
- SQLCipher import or binary availability fails on a platform → surface the
  normal import/install error rather than silently falling back to plaintext
  SQLite.
- A key literal is mishandled → construct it only from the validated 32-byte
  value and apply it before database access.

## Migration Plan

Add the engine and dependencies without changing the bootstrap package API.
Consumers opt in by selecting the engine in Tortoise configuration; rollback is
removing that configuration and package version.
