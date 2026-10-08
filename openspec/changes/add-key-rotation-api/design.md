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
- Perform rekeying under the maintenance coordination boundary and update the
  client's configured key only after native SQLCipher reports success.

**Non-Goals:**

- Generate, store, distribute, or recover database keys.
- Accept passphrases or text encodings as key material.
- Provide application-level re-encryption policy beyond SQLCipher rekeying.

## Decisions

### Use the SQLCipher driver's native rekey operation

The backend will extend its narrow driver protocol with the native rekey method
and invoke it through the asynchronous connection boundary.  It will not build
`PRAGMA rekey` text or expose SQLCipher connection objects to callers.

Native rekey avoids SQL construction and preserves the binary-key contract.
Public raw SQL or a caller-supplied callback would expose driver behaviour and
make secret handling inconsistent.

### Validate before exclusive access and keep secrets out of diagnostics

`rotate_key` rejects non-bytes values and any length other than 32 bytes before
acquiring the maintenance boundary.  Logging names only the operation and
database identifier; no value derived from either key is formatted.

Early validation avoids disrupting normal work for invalid input.  Redacting
after constructing SQL or error messages is weaker than never rendering key
material.

### Complete the native transition before reporting cancellation

Before invoking native rekey, cancellation can abort with no key change.  Once
the native call begins, the maintenance boundary remains held until its result
is known.  On success, the stored key is replaced; on failure, the key state
is reconciled through a reconnect check.  If the caller cancelled after native
rekey began, cleanup completes and that cancellation is re-raised in either
case, requiring the caller to re-read state before proceeding.

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
