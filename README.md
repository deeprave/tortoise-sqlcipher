# tortoise-sqlcipher

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
                "file_path": "encrypted.sqlite",
                "encryption_key": encryption_key,
            },
        }
    }
}
```

The engine validates that the supplied key is exactly 32 bytes and never falls
back to plaintext SQLite. Applications remain responsible for obtaining,
storing, and rotating their encryption keys.

### SQLCipher pragmas

Additional connection credentials are applied as SQLCipher pragmas after the
key is set. This permits necessary SQLCipher tuning, but it is also a foot-gun:
key-management pragmas such as `key`, `rekey`, and `hexkey`, plus `cipher_*`
settings, can alter the database's encryption configuration. Only supply extra
pragmas when your application deliberately owns that configuration.

## Supported Python versions

Python 3.11 and later are fully supported.

## Development

Install the project environment with `uv sync`, then run the repository checks
with `uv run pre-commit run --all-files`.

## Publishing

Releases are built through the manually dispatched GitHub Actions workflow.
Before the first production release, configure PyPI Trusted Publishing for
`deeprave/tortoise-sqlcipher` and its `pypi` GitHub Actions environment. No
PyPI token is stored in this repository.
