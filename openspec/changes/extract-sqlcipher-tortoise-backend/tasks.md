# Tasks

## 1. Runtime package contract

- [x] 1.1 Add Tortoise ORM, aiosqlite, and sqlcipher3 runtime dependencies at the proof-established lower bounds; verify `uv sync` resolves and `uv build` produces both artifacts.
- [x] 1.2 Add the SQLCipher Tortoise engine module under `tortoise_sqlcipher` and adapt its type annotations to Python 3.11; verify Ruff and ty pass.

## 2. Encrypted connection behavior

- [x] 2.1 Implement validated 32-byte key handling and SQLCipher connection initialization before database access; verify focused key-validation and connection tests pass.
- [x] 2.2 Preserve Tortoise SQLite pragmas, post-connect handling, result rows, and SQLite migration recognition; verify the engine is importable through a Tortoise configuration.
- [x] 2.3 Translate SQLCipher operational and integrity errors to Tortoise exceptions; verify focused exception-translation tests pass.

## 3. Package verification

- [x] 3.1 Export only the intended package surface and update package documentation for engine configuration prerequisites; verify the README makes no secret-management claim.

## 4. Accepted review follow-ups

- [x] 4.1 Translate SQLCipher failures during connection setup and transaction operations.
- [x] 4.2 Clear a failed connection setup so a later operation can retry cleanly.
- [x] 4.3 Reject non-bytes key values before connection setup.
- [x] 4.4 Use the driver's native key API and safely construct configurable SQLite pragmas.
