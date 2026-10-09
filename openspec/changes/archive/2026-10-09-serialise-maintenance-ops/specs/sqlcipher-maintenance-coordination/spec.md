# Spec Delta

## Purpose

Define safe, package-owned coordination between ordinary Tortoise use of an
encrypted database and public operations that maintain that database.

## ADDED Requirements

### Requirement: Exclusive maintenance access
The backend SHALL prevent ordinary Tortoise operations from using an encrypted
database connection while a public maintenance operation is changing its key,
creating a snapshot, or restoring a snapshot.

#### Scenario: Query overlaps maintenance
- **WHEN** a normal Tortoise query and a public maintenance operation target the
  same client concurrently
- **THEN** the query waits for maintenance to release the client boundary and
  does not observe a closed, partly restored, or rekeyed connection

#### Scenario: Transaction overlaps maintenance
- **WHEN** an application starts an ordinary Tortoise transaction while a
  public maintenance operation holds the client boundary
- **THEN** the transaction waits for maintenance to release the boundary and
  then acquires a usable connection

#### Scenario: Tortoise closes connections during maintenance
- **WHEN** Tortoise requests closure of the client connection while a public
  maintenance operation owns the client boundary
- **THEN** closure waits for maintenance to complete its connection lifecycle
  and does not close the connection during that operation

#### Scenario: Maintenance is requested within a transaction
- **WHEN** an application requests a public maintenance operation while the
  same client has an active Tortoise transaction
- **THEN** the operation raises Tortoise's transaction-management error before
  changing the database instead of waiting for the non-reentrant connection
  boundary

### Requirement: Deterministic maintenance serialisation
The backend SHALL give overlapping public maintenance operations on the same
client deterministic, non-interleaving behaviour without requiring a
caller-provided lock or lifecycle guard.

#### Scenario: Two maintenance operations overlap
- **WHEN** two public maintenance operations are requested concurrently for the
  same client
- **THEN** they run without interleaving their database or connection lifecycle
  effects

### Requirement: Recoverable operation lifecycle
The backend SHALL release its maintenance coordination after an operation
succeeds, fails, or is cancelled, and SHALL leave subsequent valid client work
able to acquire a usable connection.

#### Scenario: Maintenance operation fails
- **WHEN** a public maintenance operation raises an error after obtaining
  exclusive access
- **THEN** a later normal query or maintenance operation can complete using a
  usable client state

#### Scenario: Maintenance operation is cancelled before it changes state
- **WHEN** a caller cancels a public maintenance operation before its
  state-changing phase begins
- **THEN** the operation makes no database change and a later client operation
  can complete

#### Scenario: Maintenance operation is cancelled after it changes state
- **WHEN** a caller cancels a public maintenance operation after its
  state-changing phase begins
- **THEN** the operation completes reconciliation where possible, re-raises the
  original standard cancellation with non-secret operation and outcome detail,
  and requires the caller to re-read state through the client

### Requirement: Documented single-client ownership
The package documentation SHALL warn that public maintenance operations are
coordinated only within one SQLCipher client and that configuring multiple
Tortoise aliases for the same database file is unsafe.

#### Scenario: Application configures duplicate database aliases
- **WHEN** an application consults the package documentation before configuring
  multiple Tortoise aliases for one encrypted database file
- **THEN** it is warned that the package does not coordinate maintenance across
  those independent clients
