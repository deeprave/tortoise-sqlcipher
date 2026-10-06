# sqlcipher-tortoise-backend Specification

## Purpose

Provide a reusable encrypted SQLite connection engine that Tortoise
applications can select without changing their ordinary ORM lifecycle.

## Requirements

### Requirement: Encrypted Tortoise connection
The package SHALL provide a Tortoise-compatible SQLite engine that opens an
SQLCipher database through an asynchronous connection and applies the supplied
encryption key before database operations occur.

#### Scenario: Application configures an encrypted connection
- **WHEN** a Tortoise application selects the package engine with a database
  path and a 32-byte encryption key
- **THEN** normal Tortoise operations use the SQLCipher-encrypted database

#### Scenario: Application supplies an invalid key length
- **WHEN** an application configures an encryption key that is not 32 bytes
- **THEN** engine initialisation raises a value error before opening the
  database

### Requirement: Tortoise error compatibility
The engine SHALL expose SQLCipher operational and integrity failures as the
corresponding Tortoise exception types.

#### Scenario: SQLCipher operation fails
- **WHEN** a database operation raises a SQLCipher operational or integrity
  error
- **THEN** the caller receives Tortoise's matching operational or integrity
  exception

### Requirement: SQLite migration compatibility
The engine SHALL remain recognisable as a SQLite engine to Tortoise's native
migration support.

#### Scenario: Application runs a native migration
- **WHEN** Tortoise executes a native migration using the package engine
- **THEN** it selects its SQLite schema behaviour and creates a compatible
  migration recorder
