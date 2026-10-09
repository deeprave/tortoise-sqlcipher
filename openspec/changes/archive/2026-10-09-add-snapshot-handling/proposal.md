# Proposal

## Why

Applications cannot safely create or restore an encrypted SQLite database by
copying its database and live sidecar files themselves.  The package needs a
public snapshot API that owns SQLCipher, SQLite, connection, and filesystem
lifecycle details.

## What Changes

- Add asynchronous public backup and restore operations for databases managed
  by the SQLCipher Tortoise client.
- Produce complete, self-consistent encrypted backups without exposing key
  material or requiring callers to manage WAL or shared-memory sidecars.
- Validate restore candidates before changing the live database and define
  recoverable behaviour for failures and cancellation.
- Recreate client state after a successful restore so later Tortoise work sees
  the restored database's actual schema and migration state, without applying
  migrations implicitly.

## Capabilities

### New Capabilities

- `sqlcipher-snapshot-handling`: Create and restore complete encrypted
  SQLCipher database snapshots through the public client API.

### Modified Capabilities

None.

## Impact

- Affects the SQLCipher client, its connection lifecycle, and integration test
  support.
- Depends on the maintenance-coordination contract when operations overlap
  normal Tortoise work.
- Removes the need for consumers to manipulate encrypted database files and
  SQLite sidecars directly.
