# Architecture

`tortoise-sqlcipher` is a Tortoise ORM database engine for SQLCipher-encrypted
SQLite files. It is deliberately narrow: it adapts Tortoise's SQLite lifecycle
to SQLCipher without changing the application's models, query API, or migration
workflow.

## Backend boundary

Applications configure `tortoise_sqlcipher.sqlite_sqlcipher` as their Tortoise
engine. The backend subclasses Tortoise's SQLite client and uses `aiosqlite`
with the `sqlcipher3` DB-API connector instead of the standard-library
`sqlite3` connector. It applies the required 32-byte key through the SQLCipher
connection API before Tortoise issues database operations.

Stock Tortoise SQLite cannot transparently open SQLCipher databases because it
uses the standard SQLite connector. The backend module retains `sqlite` in its
name so that Tortoise selects its native SQLite migration behaviour.

## Tortoise compatibility

The backend preserves Tortoise's SQLite-oriented connection, query,
transaction, and migration behaviour. SQLCipher DB-API operational and integrity
errors are translated to the corresponding Tortoise exceptions. Connection and
transaction setup release their locks when initialisation fails so a failed
attempt does not block a later retry.

Configure one Tortoise alias for each encrypted database file. Multiple aliases
for the same file have independent SQLite connections and transaction
lifecycles; package maintenance operations coordinate only the client that
owns the operation and cannot make that configuration safe.

## Encryption boundary

The backend requires a 32-byte key and does not fall back to plaintext SQLite.
Its integration suite verifies that databases and live WAL sidecars created by
the engine do not expose its disposable schema or record values in plaintext,
and that an ordinary SQLite connection cannot query the encrypted database.

That evidence concerns the database files produced by this package. It is not a
claim that an application has solved all secret-management or recovery risks.
Windows support is not yet fully validated; the package does not make a Windows
compatibility claim until the SQLCipher/WAL behaviour has been investigated.

## Maintenance operations

Key rotation is available only for databases with a backing file because it
must close and reopen the client connection to verify the replacement key.
`is_mem_db()` exposes SQLite's runtime determination for applications that
need that distinction.

Snapshots use SQLCipher's native copy operation. Backup can copy either a
file-backed or memory database into a persistent encrypted snapshot. Restore
uses an atomic file replacement with a rollback copy for file-backed databases;
for memory databases it copies into the existing live connection and keeps an
encrypted operation-local rollback snapshot.

## Evidence and support status

Package regression coverage exercises Tortoise models, native migrations,
transactions, concurrent writes, rekeying, and encrypted backups. This evidence
is not a platform support contract: supported Python versions are declared in
package metadata, and platform support is established only by package-owned
validation.

## Application responsibilities

Applications own key acquisition, storage, rotation policy, backup retention,
and recovery procedures. Do not store the database key in the database itself.

Extra SQLCipher pragmas are available through Tortoise credentials for
application-owned tuning, but they can change encryption behaviour. In
particular, key-management pragmas (`key`, `rekey`, and `hexkey`) and
`cipher_*` settings require deliberate application-level ownership.

## Distribution and notices

This package is MIT-licensed. It depends on `sqlcipher3`, `aiosqlite`, and
Tortoise ORM. Consumers distributing an application should review the licence
and notice obligations of SQLCipher, its cryptographic provider, and the
selected dependency distributions alongside their own product notices.
