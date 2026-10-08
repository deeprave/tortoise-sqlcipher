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
  the former key no longer opens the database

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
- **THEN** the operation reconciles its client state, re-raises cancellation,
  and requires the caller to re-read the database state before proceeding
