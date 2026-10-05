# Proposal

## Why

The extracted backend needs a portable, behavior-focused integration test suite.
The source exploration established the essential test cases, but the package
must now own tests that specify and regress its implementation behavior.

## What Changes

- Adapt the disposable model, migration fixture, and SQLCipher helpers into
  package-owned test fixtures.
- Verify round-trip behavior for every built-in Tortoise data field and
  relation variant supported by the SQLite backend, including the date/time
  and duration values that cross the DB-API binding boundary; record known
  upstream limitations such as TimeField rather than treating them as backend
  failures.
- Verify every database and WAL/journal sidecar created through the engine is
  SQLCipher-encrypted: neither model schema nor values appear in plaintext,
  and ordinary SQLite cannot query the database.
- Verify native migration, transaction rollback, and concurrent ORM writes.
- Verify SQLCipher rekeying invalidates the former key and native encrypted
  backup/restore opens with the replacement key.
- Document the native-platform test matrix without treating generic CI as
  evidence for all SQLCipher platforms.

## Capabilities

### New Capabilities
- `sqlcipher-backend-tests`: Regression coverage for SQLCipher Tortoise
  backend behavior, encryption, and edge cases.

### Modified Capabilities
- None.

## Impact

Adds integration-test dependencies and tests after the backend change is
available. It depends on `extract-sqlcipher-tortoise-backend` for the engine
module and runtime dependencies, but does not alter its production API.
