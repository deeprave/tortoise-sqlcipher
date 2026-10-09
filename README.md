# tortoise-sqlcipher

[![Build Status](https://img.shields.io/github/actions/workflow/status/deeprave/tortoise-sqlcipher/test.yaml?branch=main&label=tests&logo=github)](https://github.com/deeprave/tortoise-sqlcipher/actions/workflows/test.yaml)
[![Maintenance](https://img.shields.io/badge/maintenance-active-brightgreen.svg)](https://github.com/deeprave/tortoise-sqlcipher)
[![PyPI version](https://img.shields.io/pypi/v/tortoise-sqlcipher.svg?logo=pypi&logoColor=white)](https://pypi.org/project/tortoise-sqlcipher/)
[![PyPI downloads](https://img.shields.io/pypi/dm/tortoise-sqlcipher.svg?logo=pypi&logoColor=white)](https://pypi.org/project/tortoise-sqlcipher/)
[![Python versions](https://img.shields.io/pypi/pyversions/tortoise-sqlcipher.svg?logo=python&logoColor=white)](https://pypi.org/project/tortoise-sqlcipher/)

`tortoise-sqlcipher` provides a Tortoise ORM-specific SQLite backend using
SQLCipher and `aiosqlite` for encrypted local databases.

## Configuration

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

If a caller cancels rotation after the native operation has begun,
`asyncio.CancelledError` is re-raised only after the client has reconciled its
connection. Its non-secret note says whether the replacement or former key was
retained. In that case, re-read database state before changing external key
storage or issuing further application work.

Key rotation requires a persistent file-backed database; in-memory databases,
including SQLite memory URIs, and temporary databases are unsupported. If it
raises `OperationalError`, do not discard either key until a fresh client
verifies database access.

Applications can check the current database before scheduling maintenance:

```python
if await client.is_mem_db():
    # Key rotation requires a persistent database.
    ...
```

### Snapshots

Create an encrypted, self-contained snapshot at a persistent filesystem path,
then restore it through the configured client:

```python
await client.backup("encrypted.snapshot.sqlite")
await client.restore("encrypted.snapshot.sqlite")
```

Snapshots use SQLCipher's native copy operation. Backing up an in-memory
database is supported; restoring into one replaces its live contents without
closing the client connection.

### SQLCipher pragmas

Additional connection credentials are applied as SQLCipher pragmas after the
key is set. This permits necessary SQLCipher tuning, but it is also a foot-gun:
key-management pragmas such as `key`, `rekey`, and `hexkey`, plus `cipher_*`
settings, can alter the database's encryption configuration. Only supply extra
pragmas when your application deliberately owns that configuration.

## Supported Python versions

Requires Python 3.11+.
