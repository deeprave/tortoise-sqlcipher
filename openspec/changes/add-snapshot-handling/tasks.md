# Tasks

## 1. Snapshot API and driver boundary

- [ ] 1.1 Extend the internal SQLCipher protocol only with the native backup operations needed by the public API, and verify static type checks pass.
- [ ] 1.2 Add asynchronous `backup(destination)` and `restore(snapshot)` client operations with path-like input validation and no public driver exposure; verify focused API tests pass.
- [ ] 1.3 Integrate both operations with the shared maintenance coordination boundary, and verify ordinary queries cannot use the connection during snapshot lifecycle work.

## 2. Safe backup and restore lifecycle

- [ ] 2.1 Implement a complete encrypted native backup that does not require caller sidecar handling, and verify the output reopens with the configured key and data.
- [ ] 2.2 Implement candidate validation, staged same-filesystem restore, and recoverable replacement, and verify invalid or incomplete snapshots leave the live database unchanged.
- [ ] 2.3 Clear and recreate connection and database-derived state after a successful restore without applying migrations, and verify an older-schema snapshot retains its actual pending-migration state.
- [ ] 2.4 Define and implement cancellation and filesystem-failure cleanup so a usable database remains recoverable and cancellation is re-raised after cleanup, and verify failure-injection tests pass.

## 3. Integration coverage and verification

- [ ] 3.1 Add integration tests for live encrypted backup, valid restore, invalid restore preservation, sidecar handling, and restored data access through Tortoise.
- [ ] 3.2 Add cancellation and replacement-failure tests that exercise the documented recovery boundary and verify a subsequent client operation succeeds.
- [ ] 3.3 Run `uv run ruff check .`, `uv run ty check`, and `uv run pytest` and verify all checks pass.
