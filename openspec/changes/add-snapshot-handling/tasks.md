# Tasks

## 1. Snapshot API and driver boundary

- [x] 1.1 Extend the internal SQLCipher protocol only with the native backup operations needed by the public API.
- [x] 1.2 Add asynchronous `backup(destination)` and `restore(snapshot)` client operations with path-like input validation and no public driver exposure; verify focused API tests pass.
- [x] 1.3 Integrate both operations with the shared maintenance coordination boundary, use `is_mem_db()` to select the restore path, permit backup from memory databases, and verify ordinary queries cannot use the connection during snapshot lifecycle work.

## 2. Safe backup and restore lifecycle

- [x] 2.1 Implement a complete encrypted native backup that does not require caller sidecar handling, and verify the output reopens with the configured key and data.
- [x] 2.2 Implement candidate validation, staged same-filesystem restore for file-backed databases, and recoverable replacement, and verify invalid or incomplete snapshots leave the live database unchanged.
- [x] 2.3 Implement memory-database restore by copying into the live connection with an operation-local rollback candidate, and verify failure or cancellation restores the original database.
- [x] 2.4 Refresh file-backed connections and preserve memory connections after successful restore without applying migrations, and verify restored data is observed through Tortoise.
- [x] 2.5 Define and implement cancellation and filesystem-failure cleanup so a usable database remains recoverable and post-start cancellation is re-raised with non-secret outcome detail after cleanup, and verify failure-injection tests pass.

## 3. Integration coverage and verification

- [x] 3.1 Add integration tests for live encrypted backup, memory-source backup, file-backed and memory-destination restore, invalid restore preservation, sidecar handling, and restored data access through Tortoise.
- [x] 3.2 Add cancellation and replacement-failure tests for both restore paths that exercise the documented recovery boundary and verify a subsequent client operation succeeds.
