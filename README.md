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
back to plaintext SQLite. Applications remain responsible for obtaining,
storing, and rotating their encryption keys.

### SQLCipher pragmas

Additional connection credentials are applied as SQLCipher pragmas after the
key is set. This permits necessary SQLCipher tuning, but it is also a foot-gun:
key-management pragmas such as `key`, `rekey`, and `hexkey`, plus `cipher_*`
settings, can alter the database's encryption configuration. Only supply extra
pragmas when your application deliberately owns that configuration.

## Supported Python versions

Requires Python 3.11+.
