# SQLCipher Snapshot Handling Specification

## Purpose

Provide public backup and restore operations that preserve encrypted SQLite
data without making callers manage SQLCipher connections or SQLite sidecars.

## Requirements

### Requirement: Encrypted database backup
The SQLCipher client SHALL provide an asynchronous public backup operation that
creates a complete, self-consistent encrypted snapshot at a caller-selected
file-backed destination without exposing encryption-key material. Backup SHALL
support both persistent and memory databases as its source.

#### Scenario: Backup of a live encrypted database
- **WHEN** an application backs up an encrypted database containing committed
  Tortoise data
- **THEN** the resulting snapshot opens with the configured 32-byte key and
  contains that committed data

#### Scenario: Backup of a memory database
- **WHEN** an application backs up an in-memory or temporary database to a
  persistent destination
- **THEN** the resulting snapshot opens with the configured 32-byte key and
  contains the source database's committed data without closing the source
  client

### Requirement: Backend-owned snapshot lifecycle
The backend SHALL own connection quiescing, checkpointing, and SQLite sidecar
handling needed to create or restore a complete snapshot; callers SHALL not
need to copy, delete, or replace database, WAL, or shared-memory files.

#### Scenario: Database has live sidecars
- **WHEN** an application creates a snapshot while SQLite sidecars are present
- **THEN** the snapshot is complete without the caller handling those sidecars

### Requirement: Validated and recoverable restore
The SQLCipher client SHALL validate a restore candidate before replacing the
active database and SHALL use an atomic or recoverable replacement strategy
that preserves at least one usable database after a restore failure or
cancellation.

#### Scenario: Invalid snapshot is restored
- **WHEN** an application requests restore from a missing, incomplete, or
  invalid snapshot
- **THEN** restore fails without changing the live encrypted database

#### Scenario: Replacement fails
- **WHEN** a filesystem failure or cancellation occurs while replacing the
  live database with a validated snapshot
- **THEN** the backend leaves a usable live or candidate database recoverable
  by the client

#### Scenario: Restore is cancelled during replacement
- **WHEN** a caller cancels restore after its state-changing replacement phase
  begins
- **THEN** the backend completes recovery handling, re-raises the original
  standard cancellation with non-secret restore outcome detail, and requires
  the caller to re-read database state before proceeding

#### Scenario: Snapshot is restored into a memory database
- **WHEN** an application restores a validated persistent snapshot into an
  in-memory or temporary database
- **THEN** the backend copies the snapshot into the existing live connection
  without closing it or replacing a database file, and invalidates
  database-derived client state after success

#### Scenario: Memory-database restore fails
- **WHEN** a restore into an in-memory or temporary database fails or is
  cancelled after changing the destination
- **THEN** the backend recovers the original database from its operation-local
  rollback candidate before reporting the failure or cancellation

### Requirement: Restored state is observed without implicit migration
After a successful restore, the backend SHALL invalidate database-derived
connection and schema state so subsequent Tortoise work observes the restored
database's actual state. Restore SHALL NOT apply migrations implicitly.

#### Scenario: Older schema snapshot is restored
- **WHEN** an application restores an encrypted snapshot with an earlier native
  migration state
- **THEN** a later explicit migration or readiness inspection observes that
  state without restore having modified it
