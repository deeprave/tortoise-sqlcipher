"""Reusable configuration helpers for SQLCipher integration tests."""

from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast

from tortoise import Tortoise

TEST_KEY = bytes.fromhex("01" * 32)


class SqlCipherConnection(Protocol):
    """Native SQLCipher operations used only by integration tests."""

    def set_key(self, key: bytes) -> None: ...

    def reset_key(self, key: bytes) -> None: ...

    def backup(self, target: "SqlCipherConnection") -> None: ...

    def execute(self, statement: str) -> Any: ...

    def close(self) -> None: ...


class SqlCipherDBAPI(Protocol):
    """The direct driver surface used for native rekey and backup operations."""

    DatabaseError: type[Exception]
    InterfaceError: type[Exception]

    def connect(self, database: str) -> SqlCipherConnection: ...


sqlcipher = cast(SqlCipherDBAPI, import_module("sqlcipher3.dbapi2"))


def database_config(database_path: Path, encryption_key: bytes = TEST_KEY) -> dict[str, object]:
    """Build an isolated Tortoise configuration for an encrypted test database."""
    return {
        "connections": {
            "default": {
                "engine": "tortoise_sqlcipher.sqlite_sqlcipher",
                "credentials": {
                    "file_path": str(database_path),
                    "encryption_key": encryption_key,
                },
            }
        },
        "apps": {
            "models": {
                "models": ["tests.sqlcipher_models"],
                "default_connection": "default",
                "migrations": "tests.sqlcipher_migrations",
            }
        },
    }


def sqlite_database_config(database_path: Path) -> dict[str, object]:
    """Build an isolated stock SQLite configuration for limitation comparisons."""
    return {
        "connections": {
            "default": {
                "engine": "tortoise.backends.sqlite",
                "credentials": {"file_path": str(database_path)},
            }
        },
        "apps": {
            "models": {
                "models": ["tests.sqlcipher_models"],
                "default_connection": "default",
            }
        },
    }


def open_sqlcipher_database(database_path: Path, encryption_key: bytes) -> SqlCipherConnection:
    """Open a test database through SQLCipher's direct native API."""
    connection = sqlcipher.connect(str(database_path))
    connection.set_key(encryption_key)
    return connection


async def close_tortoise_connections() -> None:
    """Close global Tortoise connections after each integration test."""
    await Tortoise.close_connections()
