"""Tests for the SQLCipher Tortoise client."""

from collections.abc import Awaitable
from pathlib import Path
from typing import TypeVar, cast

import pytest
from tortoise import Tortoise, fields
from tortoise.exceptions import IntegrityError, OperationalError
from tortoise.models import Model
from tortoise.transactions import in_transaction

from tortoise_sqlcipher import sqlite_sqlcipher
from tortoise_sqlcipher.sqlite_sqlcipher import SqlCipherClient, translate_sqlcipher_exceptions

Result = TypeVar("Result")


class ConfiguredRecord(Model):
    """A model used to verify Tortoise engine configuration."""

    value = fields.CharField(max_length=32)


def test_client_rejects_a_key_that_is_not_32_bytes() -> None:
    """The client fails before attempting a connection for an invalid key."""
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        SqlCipherClient("encrypted.sqlite", b"too-short")


def test_client_rejects_a_non_bytes_key() -> None:
    """Configuration values must be binary key material."""
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        SqlCipherClient("encrypted.sqlite", cast(bytes, "0" * 32))


@pytest.mark.anyio
async def test_client_runs_sqlcipher_queries_with_a_valid_key(tmp_path: Path) -> None:
    """The backend creates an encrypted SQLCipher connection for Tortoise operations."""
    client = SqlCipherClient(
        str(tmp_path / "encrypted.sqlite"),
        bytes.fromhex("01" * 32),
        connection_name="default",
    )
    try:
        await client.create_connection(with_db=True)
        await client.create_connection(with_db=True)
        await client.execute_script("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")

        assert await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["first"]) == 1
        await client.execute_many(
            "INSERT INTO records(value) VALUES (?)",
            [["second"], ["third"]],
        )
        count, rows = await client.execute_query("SELECT value FROM records ORDER BY id")

        assert count == 3
        assert [row["value"] for row in rows] == ["first", "second", "third"]
        assert await client.execute_query_dict("SELECT value FROM records WHERE id = ?", [1]) == [{"value": "first"}]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_closes_a_connection_after_invalid_pragma_setup(tmp_path: Path) -> None:
    """A setup failure does not prevent a later valid connection attempt."""
    client = SqlCipherClient(
        str(tmp_path / "invalid-pragma.sqlite"),
        bytes.fromhex("03" * 32),
        connection_name="default",
        **{"invalid-pragma": "ON"},
    )

    with pytest.raises(ValueError, match="Invalid SQLite pragma"):
        await client.create_connection(with_db=True)

    del client.pragmas["invalid-pragma"]
    try:
        await client.create_connection(with_db=True)
        assert (await client.execute_query("SELECT 1"))[0] == 1
    finally:
        await client.close()


@pytest.mark.anyio
async def test_tortoise_loads_the_sqlcipher_engine_from_configuration(tmp_path: Path) -> None:
    """The engine remains discoverable as a SQLite backend through Tortoise config."""
    config = {
        "connections": {
            "default": {
                "engine": "tortoise_sqlcipher.sqlite_sqlcipher",
                "credentials": {
                    "file_path": str(tmp_path / "configured.sqlite"),
                    "encryption_key": bytes.fromhex("02" * 32),
                },
            }
        },
        "apps": {"models": {"models": [__name__], "default_connection": "default"}},
    }

    await Tortoise.init(config=config)
    try:
        await Tortoise.generate_schemas()
        await ConfiguredRecord.create(value="configured")

        async with in_transaction() as connection:
            await connection.execute_script("CREATE TABLE transaction_records (id INTEGER PRIMARY KEY, value TEXT)")
            assert await connection.execute_insert("INSERT INTO transaction_records(value) VALUES (?)", ["first"]) == 1
            await connection.execute_many("INSERT INTO transaction_records(value) VALUES (?)", [["second"]])
            assert (await connection.execute_query("SELECT value FROM transaction_records"))[0] == 2
            assert await connection.execute_query_dict("SELECT value FROM transaction_records") == [
                {"value": "first"},
                {"value": "second"},
            ]
            await connection.savepoint()
            await connection.savepoint_rollback()
            await connection.savepoint()
            await connection.release_savepoint()
            with pytest.raises(RuntimeError, match="rollback"):
                async with in_transaction():
                    raise RuntimeError("rollback")

        with pytest.raises(RuntimeError, match="rollback"):
            async with in_transaction():
                raise RuntimeError("rollback")

        with pytest.raises(OperationalError):
            async with in_transaction() as connection:
                await connection.execute_query("SELECT missing_column")

        assert await ConfiguredRecord.filter(value="configured").count() == 1
    finally:
        await Tortoise.close_connections()


def translated_operation(error: Exception) -> Awaitable[None]:
    """Build an operation that raises a selected SQLCipher exception."""

    @translate_sqlcipher_exceptions
    async def operation() -> None:
        raise error

    return operation()


@pytest.mark.parametrize(
    ("source_error", "expected_error"),
    [
        (sqlite_sqlcipher.sqlcipher.OperationalError, OperationalError),
        (sqlite_sqlcipher.sqlcipher.IntegrityError, IntegrityError),
    ],
)
@pytest.mark.anyio
async def test_exception_translation_preserves_tortoise_error_types(
    source_error: type[Exception], expected_error: type[Exception]
) -> None:
    """SQLCipher errors use the matching exception type from Tortoise."""
    with pytest.raises(expected_error):
        await translated_operation(source_error("database failure"))
