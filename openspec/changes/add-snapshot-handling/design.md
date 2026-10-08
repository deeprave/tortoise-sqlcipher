# Design

## Context

The package currently opens SQLCipher databases through `aiosqlite` and has
only test-local direct SQLCipher backup usage.  A public snapshot feature must
replace that test-only driver handling with a client-owned lifecycle while
preserving encrypted storage and Tortoise state.  See `proposal.md` and the
`sqlcipher-snapshot-handling` delta for the behavioural contract.

## Goals / Non-Goals

**Goals:**

- Provide `backup(destination)` and `restore(snapshot)` asynchronous client
  operations with path-like inputs.
- Use SQLCipher's native backup mechanism for database content, rather than
  copying a live database and its sidecars.
- Stage and validate restore data before replacing the active database, then
  recreate the client's connection state.

**Non-Goals:**

- Backup retention, scheduling, remote storage, or application-level recovery
  policy.
- Implicit migration, readiness repair, or schema upgrade after restore.
- Cross-process coordination for other clients opening the same database file.

## Decisions

### Use caller-selected file paths and native encrypted backup

The public API accepts a destination or source path so applications retain
storage-policy control while the backend owns database-specific handling.  It
will use SQLCipher's native backup facility with the configured binary key for
both endpoints, creating one self-contained encrypted database rather than a
database-plus-sidecars file set.

Copying files and sidecars is rejected because it is unsafe while SQLite has
live WAL state.  A stream abstraction is deferred: the database and recovery
semantics require an on-disk candidate before replacement, and a path keeps
the first API small.

### Run snapshot work inside the shared maintenance boundary

Backup and restore acquire the maintenance coordination boundary before
quiescing or changing client state.  Restore closes the active connection only
after its candidate is fully opened and validated with the configured key.

Operating on a concurrently used connection risks a partial view; closing the
active database before validation would make an invalid snapshot destructive.

### Stage restore replacement and reconstruct client state

Restore copies the candidate to a same-filesystem staging location, validates
it, and uses an atomic replacement where the platform supports it.  It retains
a recoverable original or staged candidate until replacement is known to have
succeeded.  Afterwards it clears connection and schema-derived state so
Tortoise reconnects to the restored database rather than cached metadata.

Replacing directly would make interrupted writes destructive.  Running
migrations would conceal the restored database's actual state and violates the
feature contract.

### Define cancellation around durable transitions

Cancellation before exclusive access or before the candidate is accepted
causes no live replacement.  During native backup or filesystem replacement,
the implementation completes cleanup and determines which database is usable
before re-raising cancellation.  The caller must re-read state before
proceeding rather than infer whether the request completed.

Returning immediately on cancellation could abandon a partial staged or live
file transition with no safe recovery path.

## Risks / Trade-offs

- [Platform replacement semantics vary] → Exercise filesystem-failure paths
  and keep a recoverable original/candidate until completion is confirmed.
- [Large backups hold exclusive access for longer] → Document serialisation and
  avoid additional work while the maintenance boundary is held.
- [Tortoise caches database state beyond the connection] → Characterise native
  migration/readiness behaviour with a restored older-schema fixture.

## Migration Plan

This adds public client methods without changing existing configuration.
Consumers can replace their direct file-copy code after release.  If a restore
fails, retain the recoverable database selected by the operation and surface a
translated error rather than attempting implicit repair.
