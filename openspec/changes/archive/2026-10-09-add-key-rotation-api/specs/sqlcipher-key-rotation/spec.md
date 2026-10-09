# Spec Delta

## Purpose

Provide a public, asynchronous way for Tortoise applications to replace an
encrypted database's SQLCipher key without using SQLCipher driver APIs.

## ADDED Requirements

### Requirement: Public key rotation
The SQLCipher client SHALL provide an asynchronous public operation that
rotates its configured 32-byte SQLCipher key to a supplied replacement
32-byte key.

#### Scenario: Database key is rotated
- **WHEN** an application rotates an encrypted database through the public
  client API using a valid replacement key
- **THEN** existing data opens through the backend with the replacement key and
  the former key no longer opens the database, and the operation returns `None`
  only after its client connection has been refreshed

#### Scenario: Native rotation reports an error after applying the replacement key
- **WHEN** native SQLCipher rekeying reports an error but a fresh connection
  verifies that the replacement key opens the database
- **THEN** the operation returns `None` and writes a non-secret warning that
  identifies the verified rotation outcome without rendering key material or
  the raw driver error

#### Scenario: Connection-local database is rejected
- **WHEN** an application requests rotation for an in-memory database,
  including a SQLite memory URI, or a temporary database without a backing
  file
- **THEN** the operation raises a translated backend error before native rekey
  or connection closure, leaving existing data accessible

### Requirement: Memory database inspection
The SQLCipher client SHALL provide an asynchronous public operation that
reports whether its current main database has no backing file, using SQLite's
reported connection state rather than the configured filename.

#### Scenario: Application inspects a memory database
- **WHEN** an application inspects an in-memory, temporary, or SQLite memory
  URI database through the public client API
- **THEN** the operation returns `True`

#### Scenario: Application inspects a persistent database
- **WHEN** an application inspects a file-backed database through the public
  client API
- **THEN** the operation returns `False`

### Requirement: Binary key validation and confidentiality
The key-rotation operation SHALL accept only a `bytes` value containing exactly
32 bytes, SHALL reject other input before invoking SQLCipher, and SHALL NOT
write either key to diagnostic output.

#### Scenario: Replacement key is invalid
- **WHEN** an application supplies a replacement key that is not exactly
 32 bytes of binary data
- **THEN** the operation raises a value error before changing the database

#### Scenario: Rotation is logged
- **WHEN** a key rotation succeeds or fails
- **THEN** diagnostic output contains neither the former key nor the
 replacement key

### Requirement: Caller-managed external key storage
The package SHALL document that applications remain responsible for external
key generation and storage, and that they SHALL persist a replacement key only
after `rotate_key` returns normally.

#### Scenario: Application persists a replacement key
- **WHEN** an application uses `rotate_key` with externally stored key material
- **THEN** package documentation instructs it to update that external storage
  only after normal return, to re-read state after post-start cancellation, and
  to retain both key records after an operational error until a fresh client
  verifies database access

### Requirement: Defined rotation outcome
The operation SHALL either report successful use of the replacement key, raise
a translated backend error, or re-raise caller cancellation after reconciling
the key-rotation outcome.  Once its state-changing phase begins, it SHALL defer
caller cancellation until it has determined the key-rotation outcome.

#### Scenario: Cancellation before key rotation begins
- **WHEN** a caller cancels rotation before it obtains exclusive maintenance
  access
- **THEN** the database retains its former key and the client remains usable

#### Scenario: Cancellation during key rotation
- **WHEN** a caller cancels rotation after its state-changing phase begins
- **THEN** the operation reconciles and refreshes its client state, re-raises
  the original standard cancellation with non-secret key-rotation outcome
  detail, and requires the caller to re-read the database state before
  proceeding

#### Scenario: Rotation cannot be reconciled
- **WHEN** neither the replacement nor former key can reopen the database after
  a rotation failure or cancellation
- **THEN** the client remains disconnected and the operation raises a
  translated backend error instead of reporting a usable rotation outcome

#### Scenario: Successful native rotation cannot be verified
- **WHEN** native SQLCipher rekeying reports success but the replacement key
  cannot reopen the database
- **THEN** the client clears its stored key, remains disconnected, and raises a
  translated backend error chained from the reconnect failure
