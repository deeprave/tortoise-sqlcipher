# tortoise-sqlcipher

`tortoise-sqlcipher` will provide a Tortoise ORM-specific SQLite backend using
SQLCipher and `aiosqlite` for encrypted local databases.

## Status

This is the initial project-infrastructure release. The backend is not yet
implemented and this package does not yet expose database configuration or
encryption APIs.

The planned backend scope includes encrypted SQLite databases, Tortoise ORM
operations, transactions, migrations, rekeying, and encrypted backup/restore.
It does not provide a generic encryption abstraction, secret-management policy,
or PostgreSQL encryption support.

## Supported Python versions

Python 3.11, 3.12, and 3.13 are supported.

## Development

Install the project environment with `uv sync`, then run the repository checks
with `uv run pre-commit run --all-files`.
