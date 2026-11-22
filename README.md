# tortoise-sqlcipher

[![Build Status](https://img.shields.io/github/actions/workflow/status/deeprave/tortoise-sqlcipher/test.yaml?branch=main&label=tests&logo=github)](https://github.com/deeprave/tortoise-sqlcipher/actions/workflows/test.yaml)
[![Maintenance](https://img.shields.io/badge/maintenance-active-brightgreen.svg)](https://github.com/deeprave/tortoise-sqlcipher)
[![PyPI version](https://img.shields.io/pypi/v/tortoise-sqlcipher.svg?logo=pypi&logoColor=white)](https://pypi.org/project/tortoise-sqlcipher/)
[![PyPI downloads](https://img.shields.io/pypi/dm/tortoise-sqlcipher.svg?logo=pypi&logoColor=white)](https://pypi.org/project/tortoise-sqlcipher/)
[![Python versions](https://img.shields.io/pypi/pyversions/tortoise-sqlcipher.svg?logo=python&logoColor=white)](https://pypi.org/project/tortoise-sqlcipher/)

`tortoise-sqlcipher` is a drop-in encrypted SQLite backend for Tortoise ORM.
It replaces Tortoise's standard SQLite connector with SQLCipher while retaining
the Tortoise SQLite experience: models, queries, relations, transactions, and
native migrations continue to work through the normal Tortoise APIs.

Use it when an application needs a local encrypted database without giving up
the functionality Tortoise provides with SQLite. SQLCipher-specific operations
for backup, restore, and key rotation are available in addition to that
baseline.

## Use with Tortoise

Configure Tortoise with the `tortoise_sqlcipher.sqlite_sqlcipher` engine and a
32-byte encryption key:

```python
{
    "connections": {
        "default": {
            "engine": "tortoise_sqlcipher.sqlite_sqlcipher",
            "credentials": {
                "file_path": "encrypted.sqlite3",
                "encryption_key": encryption_key,
            },
        }
    }
}
```

The engine validates that the supplied key is exactly 32 bytes and never falls
back to plaintext SQLite. Applications remain responsible for generating and
storing their encryption keys.

## Tortoise compatibility

The backend follows Tortoise's SQLite behaviour, so application code uses the
same Tortoise models and APIs it would use with an unencrypted SQLite database.
This includes normal query and relation handling, transactions, and Tortoise's
native SQLite migration workflow. The difference is that the database files
and their SQLite sidecars are opened through SQLCipher.

## SQLCipher additions

### Encrypted backup and restore

Create a complete encrypted snapshot at a persistent filesystem path, then
restore it through the configured Tortoise client:

```python
client = Tortoise.get_connection("default")
await client.backup("encrypted.snapshot.sqlite")
await client.restore("encrypted.snapshot.sqlite")
```

`backup` uses SQLCipher's native copy operation to produce a self-contained,
encrypted snapshot without the application having to manage SQLite WAL or
shared-memory sidecars. It supports file-backed, temporary, and in-memory
source databases.

`restore` validates the snapshot before replacing a file-backed database and
keeps recovery material if replacement fails. Restoring into a temporary or
in-memory database is also supported: it replaces the contents of the existing
live connection without replacing a database file or closing the client.

Applications can determine whether the current database is in memory when
their own maintenance policy needs that distinction:

```python
if await client.is_mem_db():
    # For example, choose a file-backed destination for a durable backup.
    ...
```

### Key rotation

Rotate an existing database through the configured client with a replacement
32-byte `bytes` key:

```python
client = Tortoise.get_connection("default")
await client.rotate_key(replacement_key)
```

`rotate_key` returns only after it has reopened the database with the
replacement key. Persist the replacement in external key storage only after
that normal return.

Key rotation requires a persistent file-backed database; in-memory databases,
including SQLite memory URIs, and temporary databases are unsupported. If it
raises `OperationalError`, do not discard either key until a fresh client
verifies database access. If cancellation occurs after rotation begins, the
client first reconciles its connection and then re-raises `asyncio.CancelledError`
with non-secret outcome detail; re-read database state before further work.

### SQLCipher pragmas

Additional connection credentials are applied as SQLCipher pragmas after the
key is set. This permits necessary SQLCipher tuning, but it is also a foot-gun:
key-management pragmas such as `key`, `rekey`, and `hexkey`, plus `cipher_*`
settings, can alter the database's encryption configuration. Only supply extra
pragmas when your application deliberately owns that configuration.

## Supported Python versions

Requires Python 3.11+.
