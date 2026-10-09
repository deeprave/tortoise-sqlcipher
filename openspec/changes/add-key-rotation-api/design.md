# Design

## Context

The client validates and stores its configured 32-byte key while creating an
SQLCipher connection.  Native rekey support currently appears only in
test-local driver code, so consumers would otherwise need to import the driver
or issue SQLCipher-specific SQL.  See `proposal.md` and the
`sqlcipher-key-rotation` delta for the required public behaviour.

## Goals / Non-Goals

**Goals:**

- Add an asynchronous `rotate_key(replacement_key: bytes)` client operation.
- Retain the bytes-only, exactly-32-byte validation boundary.
- Perform rekeying under the maintenance coordination boundary and return only
  after a fresh connection verifies the replacement key.
- Support rotation only for persistent file-backed databases.

**Non-Goals:**

- Generate, store, distribute, or recover database keys.
- Accept passphrases or text encodings as key material.
- Provide application-level re-encryption policy beyond SQLCipher rekeying.
- Rotate databases without backing files, including in-memory and temporary
  databases.

## Decisions

### Use the SQLCipher driver's native rekey operation

The backend will extend its narrow driver protocol with sqlcipher3's native
`reset_key` method and invoke it on the aiosqlite worker thread through its
private `_execute` bridge. It will not build `PRAGMA rekey` text or expose
SQLCipher connection objects to callers.

Native rekey avoids SQL construction and preserves the binary-key contract.
The narrow private aiosqlite dependency keeps the synchronous driver call on
the connection-owning thread. Public raw SQL or a caller-supplied callback
would expose driver behaviour and make secret handling inconsistent.

The worker bridge receives a zero-argument closure that captures the
replacement key instead of accepting it as an argument. This prevents
aiosqlite's debug representation of queued operations from rendering the key.

### Rotate under the existing maintenance boundary

`rotate_key` will validate its replacement key before entering
`_maintenance_connection`, then retain that boundary through native rekeying
and any reconciliation. It will not introduce another lock or expose the
maintenance helper as a public synchronisation API.

Rekeying changes the database's encryption state, so normal queries,
transactions, overlapping maintenance operations, and externally requested
client closure must remain excluded until the client has a usable, reconciled
connection state.

### Validate before exclusive access and keep secrets out of diagnostics

`rotate_key` rejects non-bytes values and any length other than 32 bytes before
acquiring the maintenance boundary.  Logging names only the operation and
database identifier; no value derived from either key is formatted.

Early validation avoids disrupting normal work for invalid input.  Redacting
after constructing SQL or error messages is weaker than never rendering key
material.

Rotation checks SQLite's public `PRAGMA database_list` result after acquiring
the maintenance connection. An empty `main` database filename identifies a
database without a backing file, including SQLite memory URIs. The same
reusable check is exposed through the public client API for applications that
schedule maintenance work. Rotation rejects these databases before native rekey
or connection closure, because reopening them would create a new database and
could discard the caller's data.

### Complete the native transition before reporting cancellation

Before invoking native rekey, cancellation can abort with no key change. Once
the native call begins, the maintenance boundary remains held until its result
is known. After native rekey reports success, the client closes its existing
connection and reconnects with the replacement key before returning. The
stored key follows that verified, fresh connection. If that verification fails,
the client retains no key and remains deliberately disconnected; it does not
assume that the former key is still valid.

After a native error or post-start cancellation, the client closes its existing
connection and reconnects with the replacement key first, then the former key
if needed. If a replacement-key reconnect verifies that rotation completed
despite a native error, the operation returns normally and emits a warning that
identifies the operation and verified outcome without rendering either key or
the raw driver error.

The client clears its connection reference before attempting close and still
attempts reconciliation if close raises. If reconciliation cannot verify either
candidate key, it clears its stored key and raises a translated backend error
chained from the reconnect failure.

If the caller cancelled after native rekey began, that cancellation is
re-raised only after reconciliation has refreshed the client connection. The
original standard `CancelledError` carries a non-secret note identifying key
rotation and whether the replacement or former key was retained. The caller
must re-read database state before proceeding.

If neither key can reopen the database during reconciliation, the client is
left disconnected and the operation raises a translated backend error instead
of cancellation. In that case the package cannot report a usable outcome.

### Return no success payload and document caller key handling

`rotate_key` returns `None` after a normally completed and verified rotation.
Applications retain responsibility for generating and storing key material, and
must persist their external replacement key only after normal return. The
user-facing documentation will describe post-start cancellation as a signal to
read its non-secret detail and re-read state through the client.
For an `OperationalError`, applications must retain both key records until a
fresh client verifies database access.

A result type is unnecessary because normal return already means the
replacement key is active. The cancellation and error paths provide the
additional context required for uncertain execution outcomes.

Letting cancellation interrupt the await without resolving the native call
could leave the in-memory configured key and on-disk key divergent.  Treating
an unknown result as success is rejected for the same reason.

## Risks / Trade-offs

- [Native rekey outcome is ambiguous after a driver or task interruption] →
  Reopen using the candidate key before reporting an outcome and retain the
  maintenance boundary until reconciliation completes.
- [Error messages may contain sensitive values] → Translate driver exceptions
  without logging raw exception text if it can include SQLCipher key material.
- [Rotation blocks ordinary work] → Use the shared maintenance boundary and
  document that rotation is exclusive.

## Migration Plan

This is an additive API.  Consumers can replace direct driver and PRAGMA usage
with `rotate_key`; application keyring recovery remains their responsibility.
If native rekey fails, the backend reports the reconciled outcome and does not
silently update configuration.
