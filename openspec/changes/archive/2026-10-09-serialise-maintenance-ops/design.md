# Design

## Context

`SqlCipherClient` currently relies on Tortoise's connection and transaction
locks for ordinary access.  That protects connection acquisition, but it does
not express an exclusive lifecycle for future public operations that rekey,
copy, close, or replace the database.  See `proposal.md` and the
`sqlcipher-maintenance-coordination` delta for the required behaviour.

## Goals / Non-Goals

**Goals:**

- Give every public maintenance operation a single client-owned exclusive
  lifecycle boundary shared with normal connection use.
- Release that boundary reliably after ordinary errors and task cancellation.
- Make the boundary reusable by independent key-rotation and snapshot changes.

**Non-Goals:**

- Add an application-visible locking API or application-specific activity
  counters.
- Coordinate separate `SqlCipherClient` instances that point to the same file.
- Detect or prevent applications from configuring multiple Tortoise aliases
  for the same database file.
- Define key-rotation or snapshot semantics themselves.

## Decisions

### Extend the client-owned connection boundary for maintenance

Maintenance work will use the same client-level exclusion mechanism that
protects ordinary connection acquisition, then perform its complete connection
lifecycle while that access is exclusive.  This means it can safely close and
recreate the connection without a query using the former connection.

An independent maintenance-only lock would leave a gap between query access
and maintenance access.  Requiring callers to acquire a lock would recreate
the consumer lifecycle helpers this package is intended to remove.

### Make maintenance an internal async context boundary

The backend will expose an internal async context helper for public
maintenance methods.  It will acquire exclusive access, establish or close
connections as required by the operation, and release access in a `finally`
path.  Public APIs remain feature-specific; the helper is not exported as a
general-purpose synchronisation primitive.

Embedding lock handling separately in each future public method duplicates
cancellation cleanup and risks inconsistent ordering.

### Reject maintenance inside an active transaction

The maintenance context will detect an active transaction on the same client
and raise Tortoise's transaction-management error before it waits for the
connection boundary.  It will not attempt re-entrant locking or defer the
operation until transaction completion.

The transaction already owns the non-reentrant connection lock, so waiting
would deadlock.  Running maintenance inside it would also make a rollback's
meaning ambiguous for a rekey, backup, or filesystem replacement.

Normal reads and transactions started by other tasks are not rejected.  They
wait on the same client boundary while maintenance owns it, then acquire the
usable connection that maintenance leaves behind.

### Coordinate externally requested connection closure

The client will make externally requested connection closure acquire the same
boundary as maintenance.  Maintenance code that already owns the boundary will
use a private non-reentrant close primitive instead.

Tortoise's inherited close operation does not acquire the client lock.  Leaving
it unchanged would permit application shutdown to close a connection while a
maintenance operation is using it; attempting to reacquire the lock internally
would deadlock.

### Document duplicate aliases instead of detecting them

This change coordinates a single `SqlCipherClient`.  It will document that an
application must not configure multiple Tortoise aliases for the same database
file, rather than attempt path-keyed process-wide detection or locking.

Multiple aliases already have independent SQLite connections and transaction
lifecycles, so the configuration is a general Tortoise/SQLite foot-gun.  A
registry would add policy and still not coordinate another process.

### Treat state-changing phases as cancellation boundaries

Cancellation before exclusive access is acquired aborts without changing the
database.  Once an operation begins a non-interruptible native or filesystem
state transition, it must finish determining the resulting client state before
cancellation is surfaced.  Feature-specific designs define the exact outcome
that is reported.

For key rotation and restore, cancellation after the state-changing phase
begins is cleaned up and then the original standard `CancelledError` is
re-raised with a non-secret note identifying the operation and reconciled
outcome. Callers must re-read through the client before proceeding.

Allowing a task to abandon the operation at that point could release access
while an executor thread or filesystem operation still changes the database.

## Risks / Trade-offs

- [An ordinary query waits behind a long backup or restore] → Make the
  serialisation explicit in API documentation and keep exclusive sections as
  small as the database safety boundary permits.
- [Tortoise changes its private connection-lock lifecycle] → Characterise the
  relevant Tortoise version in tests and confine integration to the client
  subclass.
- [Cancellation races native work] → Test cancellation before and during the
  exclusive state-changing phase, including subsequent client use.
- [Multiple aliases target the same file] → Document the unsupported
  configuration rather than adding incomplete in-process detection.

## Migration Plan

This is an additive internal coordination layer.  Release it with the first
public maintenance API, retain ordinary Tortoise configuration compatibility,
and roll back by removing only unpublished public maintenance methods if the
new lifecycle proves incompatible.
