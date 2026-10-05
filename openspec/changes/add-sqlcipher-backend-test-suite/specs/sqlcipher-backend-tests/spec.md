# Spec Delta

## Purpose

Define regression tests for the package backend's Tortoise behavior and its
encrypted SQLite database and sidecar boundaries.

## ADDED Requirements

### Requirement: SQLite-supported Tortoise field compatibility
The test suite SHALL verify round-trip persistence through the package engine
for every built-in Tortoise data field and standard relation variant supported
by the SQLite backend. The matrix SHALL include `TimeField` and `TimeDeltaField`
values that cross the DB-API binding boundary, and SHALL record documented
upstream SQLite limitations rather than misclassifying them as backend failures.

#### Scenario: Integration test persists a field matrix
- **WHEN** the integration suite writes and reloads values for the
  SQLite-supported Tortoise field and relation matrix
- **THEN** each persisted value and relation has the same behavior expected
  from Tortoise's SQLite backend

#### Scenario: TimeField uses its known upstream SQLite limitation
- **WHEN** the integration suite persists a TimeField value through the package
  engine
- **THEN** the test records the expected Tortoise SQLite limitation and verifies
  that SQLCipher does not introduce a different failure mode

### Requirement: Fully encrypted storage
The test suite SHALL verify that every database file and live WAL/journal
sidecar created through the engine is SQLCipher-encrypted: it SHALL not contain
the disposable model schema or record values in plaintext, and ordinary SQLite
SHALL not query the database.

#### Scenario: Test creates encrypted model data
- **WHEN** an integration test writes a disposable record through the package engine
- **THEN** the database and discovered live sidecar files do not contain the
  schema or record plaintext

#### Scenario: Ordinary SQLite opens the encrypted database
- **WHEN** ordinary SQLite queries the encrypted test database without a key
- **THEN** it raises a database error instead of returning the model table

### Requirement: ORM lifecycle regression coverage
The test suite SHALL verify native migration, transaction rollback, and
concurrent ORM writes through the package engine.

#### Scenario: Transaction is rolled back
- **WHEN** a test transaction raises after creating a disposable record
- **THEN** the record is absent after the transaction closes

#### Scenario: Concurrent writes complete
- **WHEN** integration tests create multiple records concurrently
- **THEN** all expected records are persisted

### Requirement: Rekey and backup regression coverage
The test suite SHALL verify that SQLCipher rekeying rejects the former key and
that an encrypted native backup opens with the replacement key.

#### Scenario: Key is replaced
- **WHEN** an integration test rekeys an encrypted database and creates a native backup
- **THEN** the former key fails and the replacement key reads both databases
