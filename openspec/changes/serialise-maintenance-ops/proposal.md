# Proposal

## Why

The backend currently serialises ordinary Tortoise access to its connection,
but it has no public lifecycle contract for operations that change or replace
that database.  Key rotation and snapshots need package-owned coordination so
applications cannot observe a rekeyed, closed, or partly replaced connection.

## What Changes

- Define the concurrency and recovery contract for public SQLCipher maintenance
  operations and ordinary Tortoise work on the same client.
- Require maintenance operations to have deterministic non-interleaving
  behaviour without caller-provided counters, locks, or lifecycle guards.
- Require internal coordination to be released after successful, failed, or
  cancelled operations so later valid work remains possible.

## Capabilities

### New Capabilities

- `sqlcipher-maintenance-coordination`: Coordinate normal Tortoise access with
  public database-maintenance operations safely and deterministically.

### Modified Capabilities

None.

## Impact

- Affects the SQLCipher client's connection lifecycle and the public
  maintenance APIs introduced by key rotation and snapshot handling.
- Adds concurrency and cancellation regression coverage around client
  operations.
- Does not add application-level policy, key storage, or consumer-specific
  lifecycle helpers.
