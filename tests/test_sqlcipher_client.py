"""Tests for the SQLCipher Tortoise client."""

import asyncio
from collections.abc import Awaitable
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar, cast
from unittest.mock import AsyncMock

import pytest
from tortoise import Tortoise, fields
from tortoise.context import TortoiseContext
from tortoise.exceptions import IntegrityError, OperationalError, TransactionManagementError
from tortoise.models import Model
from tortoise.transactions import in_transaction

from tortoise_sqlcipher import sqlite_sqlcipher
from tortoise_sqlcipher.sqlite_sqlcipher import (
    SqlCipherClient,
    SqlCipherTransactionContext,
    SqlCipherTransactionWrapper,
    translate_sqlcipher_exceptions,
)

Result = TypeVar("Result")


class ConfiguredRecord(Model):
    """A model used to verify Tortoise engine configuration."""

    value = fields.CharField(max_length=32)


class DecimalRecord(Model):
    """A model used to verify DecimalField persistence through SQLCipher."""

    value = fields.DecimalField(max_digits=10, decimal_places=2)


class ObservingConnectionWrapper(sqlite_sqlcipher.SqlCipherConnectionWrapper):
    """Record when normal work has acquired the client's connection boundary."""

    async def __aenter__(self) -> Any:
        connection = await super().__aenter__()
        cast(Any, self.client).connection_acquired.set()
        return connection


class ObservingTransactionContext(SqlCipherTransactionContext):
    """Record transaction attempts and successful boundary acquisition."""

    async def __aenter__(self) -> SqlCipherTransactionWrapper:
        client = self.connection._parent
        client.transaction_attempted.set()
        connection = await super().__aenter__()
        client.transaction_acquired.set()
        return connection


class MaintenanceTestClient(SqlCipherClient):
    """Expose a controlled maintenance operation for client-lifecycle tests."""

    def __init__(self, file_path: str, encryption_key: bytes, **kwargs: object) -> None:
        super().__init__(file_path, encryption_key, **kwargs)
        self.connection_acquired = asyncio.Event()
        self.transaction_attempted = asyncio.Event()
        self.transaction_acquired = asyncio.Event()
        self.connection_close_started = asyncio.Event()

    def acquire_connection(self) -> ObservingConnectionWrapper:
        return ObservingConnectionWrapper(self._lock, self)

    def _in_transaction(self) -> ObservingTransactionContext:
        return ObservingTransactionContext(SqlCipherTransactionWrapper(self), self._lock)

    async def _close_connection(self) -> None:
        self.connection_close_started.set()
        await super()._close_connection()

    async def hold_maintenance(self, acquired: asyncio.Event, release: asyncio.Event) -> None:
        """Hold the package's internal maintenance boundary until released."""
        async with self._maintenance_connection():
            acquired.set()
            await release.wait()

    async def fail_maintenance(self) -> None:
        """Raise after obtaining exclusive access for failure-path tests."""
        async with self._maintenance_connection():
            raise RuntimeError("maintenance failed")


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
async def test_client_close_log_does_not_include_pragma_values(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Diagnostic closure logging must not expose configured SQLCipher key material."""
    client = SqlCipherClient(str(tmp_path / "close-log.sqlite"), b"l" * 32, connection_name="default")
    await client.create_connection(with_db=True)
    client.pragmas["key"] = "sensitive-key-material"

    with caplog.at_level("DEBUG"):
        await client.close()

    assert "sensitive-key-material" not in caplog.text


@pytest.mark.anyio
async def test_client_translates_a_wrong_key_failure(tmp_path: Path) -> None:
    """An encrypted database opened with another key uses Tortoise's error contract."""
    database = tmp_path / "wrong-key.sqlite"
    first_client = SqlCipherClient(str(database), bytes.fromhex("04" * 32), connection_name="default")
    try:
        await first_client.create_connection(with_db=True)
        await first_client.execute_script("CREATE TABLE records (value TEXT)")
    finally:
        await first_client.close()

    second_client = SqlCipherClient(str(database), bytes.fromhex("05" * 32), connection_name="default")
    try:
        with pytest.raises(OperationalError) as error:
            await second_client.create_connection(with_db=True)
        assert isinstance(error.value.__cause__, sqlite_sqlcipher.sqlcipher.DatabaseError)
    finally:
        await second_client.close()


@pytest.mark.anyio
async def test_client_retries_a_normal_operation_after_connection_setup_fails(tmp_path: Path) -> None:
    """A failed normal acquisition releases the lock for a later retry."""
    database = tmp_path / "missing" / "retry.sqlite"
    client = SqlCipherClient(str(database), bytes.fromhex("06" * 32), connection_name="default")
    try:
        with pytest.raises(OperationalError):
            await client.execute_query("SELECT 1")

        database.parent.mkdir()
        count, _ = await asyncio.wait_for(client.execute_query("SELECT 1"), timeout=1)
        assert count == 1
    finally:
        await client.close()


@pytest.mark.anyio
async def test_transaction_begin_translates_sqlcipher_operational_errors() -> None:
    """SQLCipher BEGIN failures retain Tortoise's transaction-management contract."""
    client = SqlCipherClient("encrypted.sqlite", bytes.fromhex("07" * 32), connection_name="default")
    transaction = SqlCipherTransactionWrapper(client)
    connection = AsyncMock()
    connection.execute.side_effect = sqlite_sqlcipher.sqlcipher.OperationalError("database is locked")
    transaction._connection = cast(Any, connection)

    context = SqlCipherTransactionContext(transaction, asyncio.Lock())
    async with TortoiseContext():
        with pytest.raises(TransactionManagementError) as error:
            await context.__aenter__()

        assert isinstance(error.value.__cause__, sqlite_sqlcipher.sqlcipher.OperationalError)
        with pytest.raises(TransactionManagementError):
            await asyncio.wait_for(context.__aenter__(), timeout=1)


@pytest.mark.anyio
async def test_transaction_retries_after_connection_setup_fails(tmp_path: Path) -> None:
    """A failed transaction entry releases its acquisition lock for a later retry."""
    database = tmp_path / "missing" / "transaction-retry.sqlite"
    client = SqlCipherClient(str(database), bytes.fromhex("08" * 32), connection_name="default")
    try:
        async with TortoiseContext():
            with pytest.raises(OperationalError):
                async with client._in_transaction():
                    pass

            database.parent.mkdir()
            async with client._in_transaction() as connection:
                count, _ = await connection.execute_query("SELECT 1")
            assert count == 1
    finally:
        await client.close()


@pytest.mark.anyio
async def test_normal_query_waits_for_maintenance_to_release_the_connection(tmp_path: Path) -> None:
    """Normal work waits for the maintenance boundary and uses its resulting connection."""
    client = MaintenanceTestClient(str(tmp_path / "maintenance-query.sqlite"), b"m" * 32, connection_name="default")
    acquired = asyncio.Event()
    release = asyncio.Event()
    try:
        maintenance = asyncio.create_task(client.hold_maintenance(acquired, release))
        await asyncio.wait_for(acquired.wait(), timeout=1)
        client.connection_acquired.clear()
        query_attempted = asyncio.Event()

        async def run_query() -> tuple[int, Any]:
            query_attempted.set()
            return await client.execute_query("SELECT 1")

        query = asyncio.create_task(run_query())

        await asyncio.wait_for(query_attempted.wait(), timeout=1)
        assert not client.connection_acquired.is_set()

        release.set()
        await maintenance
        assert (await query)[0] == 1
        assert client.connection_acquired.is_set()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_maintenance_requested_inside_transaction_fails_without_waiting(tmp_path: Path) -> None:
    """Maintenance cannot re-enter the connection boundary held by its transaction."""
    client = MaintenanceTestClient(
        str(tmp_path / "maintenance-transaction.sqlite"), b"t" * 32, connection_name="default"
    )
    acquired = asyncio.Event()
    release = asyncio.Event()
    try:
        async with TortoiseContext():
            async with client._in_transaction():
                with pytest.raises(TransactionManagementError):
                    await asyncio.wait_for(client.hold_maintenance(acquired, release), timeout=1)
        assert not acquired.is_set()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_close_inside_transaction_fails_without_waiting(tmp_path: Path) -> None:
    """Connection closure cannot re-enter the client boundary held by its transaction."""
    client = MaintenanceTestClient(
        str(tmp_path / "maintenance-close-transaction.sqlite"), b"z" * 32, connection_name="default"
    )
    try:
        async with TortoiseContext():
            async with client._in_transaction():
                with pytest.raises(TransactionManagementError):
                    await asyncio.wait_for(client.close(), timeout=1)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_close_waits_for_maintenance_to_release_the_connection(tmp_path: Path) -> None:
    """Connection shutdown does not close a connection while maintenance owns it."""
    client = MaintenanceTestClient(str(tmp_path / "maintenance-close.sqlite"), b"c" * 32, connection_name="default")
    acquired = asyncio.Event()
    release = asyncio.Event()
    try:
        maintenance = asyncio.create_task(client.hold_maintenance(acquired, release))
        await asyncio.wait_for(acquired.wait(), timeout=1)
        close_attempted = asyncio.Event()

        async def close_client() -> None:
            close_attempted.set()
            await client.close()

        close = asyncio.create_task(close_client())

        await asyncio.wait_for(close_attempted.wait(), timeout=1)
        assert not client.connection_close_started.is_set()

        release.set()
        await maintenance
        await close
        assert client.connection_close_started.is_set()
        assert client._connection is None
    finally:
        if client._connection is not None:
            await client.close()


@pytest.mark.anyio
async def test_transaction_waits_for_maintenance_to_release_the_connection(tmp_path: Path) -> None:
    """A transaction started elsewhere waits for a usable post-maintenance connection."""
    client = MaintenanceTestClient(
        str(tmp_path / "maintenance-transaction-wait.sqlite"), b"w" * 32, connection_name="default"
    )
    acquired = asyncio.Event()
    release = asyncio.Event()

    async def run_transaction() -> int:
        async with client._in_transaction() as connection:
            return (await connection.execute_query("SELECT 1"))[0]

    try:
        async with TortoiseContext():
            maintenance = asyncio.create_task(client.hold_maintenance(acquired, release))
            await asyncio.wait_for(acquired.wait(), timeout=1)
            transaction = asyncio.create_task(run_transaction())

            await asyncio.wait_for(client.transaction_attempted.wait(), timeout=1)
            assert not client.transaction_acquired.is_set()

            release.set()
            await maintenance
            assert await transaction == 1
            assert client.transaction_acquired.is_set()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_maintenance_operations_do_not_interleave(tmp_path: Path) -> None:
    """A second maintenance operation waits until the first releases the client."""
    client = MaintenanceTestClient(str(tmp_path / "maintenance-serial.sqlite"), b"s" * 32, connection_name="default")
    first_acquired = asyncio.Event()
    first_release = asyncio.Event()
    second_acquired = asyncio.Event()
    second_release = asyncio.Event()
    try:
        first = asyncio.create_task(client.hold_maintenance(first_acquired, first_release))
        await asyncio.wait_for(first_acquired.wait(), timeout=1)
        second = asyncio.create_task(client.hold_maintenance(second_acquired, second_release))

        await asyncio.sleep(0)
        assert not second_acquired.is_set()

        first_release.set()
        await first
        await asyncio.wait_for(second_acquired.wait(), timeout=1)
        second_release.set()
        await second
    finally:
        await client.close()


@pytest.mark.anyio
async def test_cancelling_maintenance_releases_the_connection_boundary(tmp_path: Path) -> None:
    """Cancellation before a durable operation leaves ordinary client work available."""
    client = MaintenanceTestClient(str(tmp_path / "maintenance-cancel.sqlite"), b"k" * 32, connection_name="default")
    acquired = asyncio.Event()
    release = asyncio.Event()
    try:
        maintenance = asyncio.create_task(client.hold_maintenance(acquired, release))
        await asyncio.wait_for(acquired.wait(), timeout=1)
        maintenance.cancel()
        with pytest.raises(asyncio.CancelledError):
            await maintenance

        assert (await client.execute_query("SELECT 1"))[0] == 1
    finally:
        await client.close()


@pytest.mark.anyio
async def test_failing_maintenance_releases_the_connection_boundary(tmp_path: Path) -> None:
    """A maintenance failure leaves ordinary client work available."""
    client = MaintenanceTestClient(str(tmp_path / "maintenance-failure.sqlite"), b"f" * 32, connection_name="default")
    try:
        with pytest.raises(RuntimeError, match="maintenance failed"):
            await client.fail_maintenance()

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
        await DecimalRecord.create(value=Decimal("12.34"))
        decimal_record = await DecimalRecord.filter(value=Decimal("12.34")).first()
        assert decimal_record is not None
        assert decimal_record.value == Decimal("12.34")

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
