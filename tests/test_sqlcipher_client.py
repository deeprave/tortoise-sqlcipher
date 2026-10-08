"""Tests for the SQLCipher Tortoise client."""

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
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


class RotationClientFixture:
    """Provide a real client and controlled native-call outcomes for rotation tests."""

    def __init__(
        self, client: SqlCipherClient, original_key: bytes, replacement_key: bytes, monkeypatch: pytest.MonkeyPatch
    ):
        self.client = client
        self.original_key = original_key
        self.replacement_key = replacement_key
        self._monkeypatch = monkeypatch

    async def replace_native_call(self, handler: Callable[..., Awaitable[object]]) -> None:
        """Inject one native rotation outcome while restoring the real worker bridge afterwards."""
        connection = self.client._connection
        assert connection is not None
        original_execute = connection._execute

        async def injected_call(operation: Callable[..., object], *args: object, **kwargs: object) -> object:
            if getattr(operation, "__name__", None) != "reset_key":
                return await original_execute(operation, *args, **kwargs)
            self._monkeypatch.setattr(connection, "_execute", original_execute)
            return await handler(original_execute, operation, *args, **kwargs)

        self._monkeypatch.setattr(connection, "_execute", injected_call)


@pytest.fixture
async def rotation_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[RotationClientFixture]:
    """Create and close a file-backed client for public rotation behaviour tests."""
    original_key = bytes.fromhex("10" * 32)
    replacement_key = bytes.fromhex("11" * 32)
    client = SqlCipherClient(str(tmp_path / "rotation.sqlite"), original_key, connection_name="default")
    await client.create_connection(with_db=True)
    try:
        yield RotationClientFixture(client, original_key, replacement_key, monkeypatch)
    finally:
        await client.close()


def test_client_rejects_a_key_that_is_not_32_bytes() -> None:
    """The client fails before attempting a connection for an invalid key."""
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        SqlCipherClient("encrypted.sqlite", b"too-short")


def test_client_rejects_a_non_bytes_key() -> None:
    """Configuration values must be binary key material."""
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        SqlCipherClient("encrypted.sqlite", cast(bytes, "0" * 32))


@pytest.mark.anyio
@pytest.mark.parametrize("replacement_key", [b"too-short", cast(bytes, "not-bytes")])
async def test_client_rotation_rejects_an_invalid_replacement_key(replacement_key: bytes) -> None:
    """Rotation validates replacement key material before opening a connection."""
    client = SqlCipherClient("encrypted.sqlite", b"o" * 32, connection_name="default")

    with pytest.raises(ValueError, match="exactly 32 bytes"):
        await client.rotate_key(replacement_key)

    assert client._connection is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    "file_path",
    [
        ":memory:",
        "",
        "file:rotation-memory?mode=memory&cache=shared",
        "file::memory:?cache=shared",
    ],
)
async def test_client_rotation_rejects_databases_without_backing_files(file_path: str) -> None:
    """Rotation leaves SQLite data intact when its database has no backing file."""
    client = SqlCipherClient(file_path, bytes.fromhex("09" * 32), connection_name="default")
    try:
        await client.create_connection(with_db=True)
        assert await client.is_mem_db()
        await client.execute_script("CREATE TABLE records (value TEXT)")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["preserved"])

        with pytest.raises(OperationalError, match="persistent database"):
            await client.rotate_key(bytes.fromhex("0a" * 32))

        assert await client.execute_query_dict("SELECT value FROM records") == [{"value": "preserved"}]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_reports_a_file_backed_database(tmp_path: Path) -> None:
    """Applications can distinguish a persistent database through the public client API."""
    client = SqlCipherClient(str(tmp_path / "persistent.sqlite"), bytes.fromhex("0b" * 32), connection_name="default")
    try:
        assert not await client.is_mem_db()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_backup_creates_an_encrypted_file_snapshot(tmp_path: Path) -> None:
    """A file-backed client creates a readable encrypted snapshot without closing itself."""
    key = bytes.fromhex("0c" * 32)
    client = SqlCipherClient(str(tmp_path / "source.sqlite"), key, connection_name="default")
    snapshot = tmp_path / "snapshot.sqlite"
    try:
        await client.execute_script("CREATE TABLE records (value TEXT)")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["snapshot"])

        assert await client.backup(snapshot) is None
        assert await client.execute_query_dict("SELECT value FROM records") == [{"value": "snapshot"}]
    finally:
        await client.close()

    restored = SqlCipherClient(str(snapshot), key, connection_name="snapshot")
    try:
        assert await restored.execute_query_dict("SELECT value FROM records") == [{"value": "snapshot"}]
    finally:
        await restored.close()


@pytest.mark.anyio
async def test_client_backup_supports_memory_database_sources(tmp_path: Path) -> None:
    """A memory database can create a persistent encrypted snapshot without closing its connection."""
    key = bytes.fromhex("0d" * 32)
    client = SqlCipherClient(":memory:", key, connection_name="default")
    snapshot = tmp_path / "memory-snapshot.sqlite"
    try:
        await client.execute_script("CREATE TABLE records (value TEXT)")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["memory"])

        assert await client.backup(snapshot) is None
        assert await client.execute_query_dict("SELECT value FROM records") == [{"value": "memory"}]
    finally:
        await client.close()

    restored = SqlCipherClient(str(snapshot), key, connection_name="snapshot")
    try:
        assert await restored.execute_query_dict("SELECT value FROM records") == [{"value": "memory"}]
    finally:
        await restored.close()


@pytest.mark.anyio
async def test_client_restore_replaces_a_file_backed_database_with_its_snapshot(tmp_path: Path) -> None:
    """File-backed restore replaces later changes with the snapshot's contents."""
    key = bytes.fromhex("0e" * 32)
    client = SqlCipherClient(str(tmp_path / "source.sqlite"), key, connection_name="default")
    snapshot = tmp_path / "snapshot.sqlite"
    try:
        await client.execute_script("CREATE TABLE records (value TEXT)")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["snapshot"])
        await client.backup(snapshot)
        await client.execute_script("DELETE FROM records")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["changed"])

        assert await client.restore(snapshot) is None
        assert await client.execute_query_dict("SELECT value FROM records") == [{"value": "snapshot"}]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_restore_replaces_a_memory_database_with_its_snapshot(tmp_path: Path) -> None:
    """Memory restore copies a snapshot into its existing client connection."""
    key = bytes.fromhex("0f" * 32)
    client = SqlCipherClient(":memory:", key, connection_name="default")
    snapshot = tmp_path / "memory-snapshot.sqlite"
    try:
        await client.execute_script("CREATE TABLE records (value TEXT)")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["snapshot"])
        await client.backup(snapshot)
        await client.execute_script("DELETE FROM records")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["changed"])

        assert await client.restore(snapshot) is None
        assert await client.execute_query_dict("SELECT value FROM records") == [{"value": "snapshot"}]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_rejects_invalid_snapshot_paths(tmp_path: Path) -> None:
    """Snapshot operations reject paths that cannot represent persistent database files."""
    client = SqlCipherClient(str(tmp_path / "source.sqlite"), bytes.fromhex("10" * 32), connection_name="default")
    try:
        with pytest.raises(TypeError, match="must be text"):
            await client.backup(cast(os.PathLike[str], b"snapshot.sqlite"))
        with pytest.raises(ValueError, match="persistent filesystem path"):
            await client.backup(":memory:")
        with pytest.raises(ValueError, match="persistent filesystem path"):
            await client.backup("file:snapshot?mode=memory")
        with pytest.raises(ValueError, match="existing file"):
            await client.restore(tmp_path / "missing.sqlite")
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_rejects_backup_over_its_active_file(tmp_path: Path) -> None:
    """Backup does not overwrite the active database through a second native connection."""
    database = tmp_path / "source.sqlite"
    client = SqlCipherClient(str(database), bytes.fromhex("11" * 32), connection_name="default")
    try:
        with pytest.raises(ValueError, match="must differ"):
            await client.backup(database)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_memory_restore_recovers_after_a_copy_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed memory restore copies the pre-restore database back into its live connection."""
    key = bytes.fromhex("12" * 32)
    client = SqlCipherClient(":memory:", key, connection_name="default")
    snapshot = tmp_path / "snapshot.sqlite"
    try:
        await client.execute_script("CREATE TABLE records (value TEXT)")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["snapshot"])
        await client.backup(snapshot)
        await client.execute_script("DELETE FROM records")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["original"])
        original_copy = client._copy_path_to_connection
        calls = 0

        async def copy_then_fail(
            source_path: Path, destination: sqlite_sqlcipher.aiosqlite.Connection, encryption_key: bytes
        ) -> None:
            nonlocal calls
            calls += 1
            await original_copy(source_path, destination, encryption_key)
            if calls == 1:
                raise RuntimeError("restore copy failed")

        monkeypatch.setattr(client, "_copy_path_to_connection", copy_then_fail)
        with pytest.raises(RuntimeError, match="restore copy failed"):
            await client.restore(snapshot)

        assert await client.execute_query_dict("SELECT value FROM records") == [{"value": "original"}]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_memory_restore_reports_failed_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecoverable memory restore reports the rollback failure as its cause."""
    key = bytes.fromhex("13" * 32)
    client = SqlCipherClient(":memory:", key, connection_name="default")
    snapshot = tmp_path / "snapshot.sqlite"
    try:
        await client.execute_script("CREATE TABLE records (value TEXT)")
        await client.backup(snapshot)

        async def fail_copy(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("copy failed")

        monkeypatch.setattr(client, "_copy_path_to_connection", fail_copy)
        with pytest.raises(OperationalError, match="could not recover") as error:
            await client.restore(snapshot)

        assert isinstance(error.value.__cause__, RuntimeError)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_file_restore_recovers_after_reconnect_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed file restore restores the original database before reporting the error."""
    key = bytes.fromhex("14" * 32)
    client = SqlCipherClient(str(tmp_path / "source.sqlite"), key, connection_name="default")
    snapshot = tmp_path / "snapshot.sqlite"
    try:
        await client.execute_script("CREATE TABLE records (value TEXT)")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["snapshot"])
        await client.backup(snapshot)
        await client.execute_script("DELETE FROM records")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["original"])
        original_create = client.create_connection
        calls = 0

        async def fail_once(with_db: bool) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("reconnect failed")
            await original_create(with_db)

        monkeypatch.setattr(client, "create_connection", fail_once)
        with pytest.raises(RuntimeError, match="reconnect failed"):
            await client.restore(snapshot)

        assert await client.execute_query_dict("SELECT value FROM records") == [{"value": "original"}]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_file_restore_recovers_after_partial_artifact_staging_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A staging failure restores every moved original database artifact."""
    key = bytes.fromhex("1d" * 32)
    database = tmp_path / "source.sqlite"
    client = SqlCipherClient(str(database), key, connection_name="default")
    snapshot = tmp_path / "snapshot.sqlite"
    try:
        await client.execute_script("CREATE TABLE records (value TEXT)")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["snapshot"])
        await client.backup(snapshot)
        await client.execute_script("DELETE FROM records")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["original"])
        original_move = sqlite_sqlcipher._move_database_artifacts
        failed = False

        def move_primary_artifact_then_fail(source: Path, destination: Path) -> None:
            nonlocal failed
            if not failed:
                failed = True
                sqlite_sqlcipher.os.replace(source, destination)
                raise OSError("artifact staging failed")
            original_move(source, destination)

        monkeypatch.setattr(sqlite_sqlcipher, "_move_database_artifacts", move_primary_artifact_then_fail)
        with pytest.raises(OSError, match="artifact staging failed"):
            await client.restore(snapshot)

        assert await client.execute_query_dict("SELECT value FROM records") == [{"value": "original"}]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_file_restore_reports_failed_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecoverable file restore preserves the recovery failure as its cause."""
    key = bytes.fromhex("15" * 32)
    client = SqlCipherClient(str(tmp_path / "source.sqlite"), key, connection_name="default")
    snapshot = tmp_path / "snapshot.sqlite"
    try:
        await client.execute_script("CREATE TABLE records (value TEXT)")
        await client.backup(snapshot)

        async def fail_reconnect(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("reconnect failed")

        monkeypatch.setattr(client, "create_connection", fail_reconnect)
        with pytest.raises(OperationalError, match="could not recover") as error:
            await client.restore(snapshot)

        assert isinstance(error.value.__cause__, RuntimeError)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_client_restore_cancellation_reports_after_file_restore_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation waits for a file-backed restore to leave the snapshot usable."""
    key = bytes.fromhex("16" * 32)
    client = SqlCipherClient(str(tmp_path / "source.sqlite"), key, connection_name="default")
    snapshot = tmp_path / "snapshot.sqlite"
    started = asyncio.Event()
    release = asyncio.Event()
    try:
        await client.execute_script("CREATE TABLE records (value TEXT)")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["snapshot"])
        await client.backup(snapshot)
        await client.execute_script("DELETE FROM records")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["changed"])
        original_copy = client._copy_path_to_path

        async def delayed_copy(source: Path, destination: Path, encryption_key: bytes) -> None:
            started.set()
            await release.wait()
            await original_copy(source, destination, encryption_key)

        monkeypatch.setattr(client, "_copy_path_to_path", delayed_copy)
        operation = asyncio.create_task(client.restore(snapshot))
        await asyncio.wait_for(started.wait(), timeout=1)
        operation.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError) as cancellation:
            await operation

        assert getattr(cancellation.value, "__notes__", ()) == ["SQLCipher restore completed; re-read database state"]
        assert await client.execute_query_dict("SELECT value FROM records") == [{"value": "snapshot"}]
    finally:
        release.set()
        await client.close()


@pytest.mark.anyio
async def test_client_restore_cancellation_reports_after_memory_restore_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation waits for an in-memory restore to leave the snapshot usable."""
    key = bytes.fromhex("17" * 32)
    client = SqlCipherClient(":memory:", key, connection_name="default")
    snapshot = tmp_path / "snapshot.sqlite"
    started = asyncio.Event()
    release = asyncio.Event()
    try:
        await client.execute_script("CREATE TABLE records (value TEXT)")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["snapshot"])
        await client.backup(snapshot)
        await client.execute_script("DELETE FROM records")
        await client.execute_insert("INSERT INTO records(value) VALUES (?)", ["changed"])
        original_copy = client._copy_path_to_connection

        async def delayed_copy(
            source: Path, destination: sqlite_sqlcipher.aiosqlite.Connection, encryption_key: bytes
        ) -> None:
            started.set()
            await release.wait()
            await original_copy(source, destination, encryption_key)

        monkeypatch.setattr(client, "_copy_path_to_connection", delayed_copy)
        operation = asyncio.create_task(client.restore(snapshot))
        await asyncio.wait_for(started.wait(), timeout=1)
        operation.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError) as cancellation:
            await operation

        assert getattr(cancellation.value, "__notes__", ()) == ["SQLCipher restore completed; re-read database state"]
        assert await client.execute_query_dict("SELECT value FROM records") == [{"value": "snapshot"}]
    finally:
        release.set()
        await client.close()


@pytest.mark.anyio
async def test_client_snapshot_cancellation_is_reported_after_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation waits for a dispatched backup to produce its encrypted snapshot."""
    key = bytes.fromhex("18" * 32)
    client = SqlCipherClient(str(tmp_path / "source.sqlite"), key, connection_name="default")
    snapshot = tmp_path / "snapshot.sqlite"
    started = asyncio.Event()
    release = asyncio.Event()
    original_copy = client._copy_connection_to_path

    async def delayed_copy(
        connection: sqlite_sqlcipher.aiosqlite.Connection, destination: Path, encryption_key: bytes
    ) -> None:
        started.set()
        await release.wait()
        await original_copy(connection, destination, encryption_key)

    monkeypatch.setattr(client, "_copy_connection_to_path", delayed_copy)
    operation = asyncio.create_task(client.backup(snapshot))
    query: asyncio.Task[tuple[int, Sequence[dict[str, Any]]]] | None = None
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        query = asyncio.create_task(client.execute_query("SELECT 1"))
        await asyncio.sleep(0)
        assert not query.done()
        operation.cancel()
        await asyncio.sleep(0)
        operation.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError) as cancellation:
            await operation

        assert getattr(cancellation.value, "__notes__", ()) == ["SQLCipher backup completed; re-read database state"]
        restored = SqlCipherClient(str(snapshot), key, connection_name="snapshot")
        try:
            assert (await restored.execute_query("SELECT 1"))[0] == 1
        finally:
            await restored.close()
        assert (await query)[0] == 1
    finally:
        release.set()
        if not operation.done():
            operation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await operation
        if query is not None and not query.done():
            query.cancel()
            with pytest.raises(asyncio.CancelledError):
                await query
        await client.close()


@pytest.mark.anyio
async def test_client_rotation_leaves_no_unverified_key_after_replacement_reconnect_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful native rekey does not retain an unverified client key after reconnect failure."""
    original_key = bytes.fromhex("0b" * 32)
    replacement_key = bytes.fromhex("0c" * 32)
    client = SqlCipherClient(
        str(tmp_path / "rotation-reconnect-failure.sqlite"), original_key, connection_name="default"
    )
    await client.create_connection(with_db=True)

    async def fail_reconnect(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("temporarily unavailable")

    monkeypatch.setattr(client, "create_connection", fail_reconnect)
    with pytest.raises(OperationalError, match="could not restore a usable connection") as error:
        await client.rotate_key(replacement_key)

    assert isinstance(error.value.__cause__, OperationalError)
    assert client._connection is None
    assert client._encryption_key is None


@pytest.mark.anyio
async def test_client_rotation_translates_unexpected_replacement_reconnect_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unexpected reconnect errors leave the client disconnected behind a backend error."""
    client = SqlCipherClient(
        str(tmp_path / "rotation-unexpected-reconnect.sqlite"), bytes.fromhex("0d" * 32), connection_name="default"
    )
    await client.create_connection(with_db=True)

    async def fail_reconnect(*_args: object, **_kwargs: object) -> None:
        raise ValueError("unexpected reconnect failure")

    monkeypatch.setattr(client, "create_connection", fail_reconnect)
    with pytest.raises(OperationalError, match="could not restore a usable connection") as error:
        await client.rotate_key(bytes.fromhex("0e" * 32))

    assert isinstance(error.value.__cause__, ValueError)
    assert client._connection is None
    assert client._encryption_key is None


@pytest.mark.anyio
async def test_client_rotation_reconciles_after_connection_close_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A close error does not prevent reconnection with the verified replacement key."""
    replacement_key = bytes.fromhex("10" * 32)
    client = SqlCipherClient(
        str(tmp_path / "rotation-close-failure.sqlite"), bytes.fromhex("0f" * 32), connection_name="default"
    )
    await client.create_connection(with_db=True)
    connection = client._connection
    assert connection is not None
    original_close = connection.close

    async def fail_close() -> None:
        raise RuntimeError("close failed")

    monkeypatch.setattr(connection, "close", fail_close)
    try:
        assert await client.rotate_key(replacement_key) is None
        assert client._encryption_key == replacement_key
        assert (await client.execute_query("SELECT 1"))[0] == 1
    finally:
        monkeypatch.setattr(connection, "close", original_close)
        await connection.close()
        await client.close()


@pytest.mark.anyio
async def test_client_rotation_verifies_the_replacement_after_a_native_error(
    rotation_client: RotationClientFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """A driver error after rekeying is harmless only after a fresh replacement-key connection works."""
    client = rotation_client.client

    async def reset_then_report_error(
        original_execute: Callable[..., Awaitable[object]], operation: Callable[..., object], *args: object
    ) -> object:
        await original_execute(operation, *args)
        raise sqlite_sqlcipher.sqlcipher.OperationalError("native reset reported an error")

    await rotation_client.replace_native_call(reset_then_report_error)
    with caplog.at_level("WARNING"):
        assert await client.rotate_key(rotation_client.replacement_key) is None

    assert client._encryption_key == rotation_client.replacement_key
    assert "verified replacement key" in caplog.text
    assert rotation_client.original_key.hex() not in caplog.text
    assert rotation_client.replacement_key.hex() not in caplog.text
    assert "native reset reported an error" not in caplog.text
    assert (await client.execute_query("SELECT 1"))[0] == 1


@pytest.mark.anyio
async def test_client_rotation_restores_the_former_connection_after_a_native_failure(
    rotation_client: RotationClientFixture,
) -> None:
    """A failed rekey reports Tortoise's error type after restoring the former usable connection."""
    client = rotation_client.client

    async def report_error(*_args: object) -> None:
        raise sqlite_sqlcipher.sqlcipher.OperationalError("native reset failed")

    await rotation_client.replace_native_call(report_error)
    with pytest.raises(OperationalError) as error:
        await client.rotate_key(rotation_client.replacement_key)

    assert isinstance(error.value.__cause__, sqlite_sqlcipher.sqlcipher.OperationalError)
    assert client._encryption_key == rotation_client.original_key
    assert (await client.execute_query("SELECT 1"))[0] == 1


@pytest.mark.anyio
async def test_client_rotation_leaves_the_client_disconnected_when_neither_key_reopens(
    rotation_client: RotationClientFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreconciled native failure reports a backend error rather than a usable outcome."""
    client = rotation_client.client

    async def report_error(*_args: object) -> None:
        raise sqlite_sqlcipher.sqlcipher.OperationalError("native reset failed")

    async def fail_reconnect(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("reconnect failed")

    await rotation_client.replace_native_call(report_error)
    monkeypatch.setattr(client, "create_connection", fail_reconnect)

    with pytest.raises(OperationalError) as error:
        await client.rotate_key(rotation_client.replacement_key)

    assert isinstance(error.value.__cause__, OperationalError)
    assert client._connection is None
    assert client._encryption_key is None


@pytest.mark.anyio
async def test_client_rotation_rejects_an_unverified_native_success(
    rotation_client: RotationClientFixture,
) -> None:
    """A native success report is insufficient when the replacement key cannot reopen the database."""
    client = rotation_client.client

    async def report_success_without_rotation(*_args: object) -> None:
        return None

    await rotation_client.replace_native_call(report_success_without_rotation)
    with pytest.raises(OperationalError, match="could not restore a usable connection"):
        await client.rotate_key(rotation_client.replacement_key)

    assert client._encryption_key is None
    with pytest.raises(OperationalError, match="no verified encryption key"):
        await client.execute_query("SELECT 1")


@pytest.mark.anyio
async def test_client_rotation_blocks_normal_work_and_reports_post_start_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled rotation reconciles before reporting cancellation and releases normal work afterwards."""
    original_key = bytes.fromhex("14" * 32)
    replacement_key = bytes.fromhex("15" * 32)
    client = MaintenanceTestClient(str(tmp_path / "rotation-cancelled.sqlite"), original_key, connection_name="default")
    await client.create_connection(with_db=True)
    client.connection_acquired.clear()
    connection = client._connection
    assert connection is not None
    original_execute = connection._execute
    native_started = asyncio.Event()
    complete_native_reset = asyncio.Event()

    async def delayed_reset(operation: Callable[..., object], *args: object, **kwargs: object) -> object:
        if getattr(operation, "__name__", None) != "reset_key":
            return await original_execute(operation, *args, **kwargs)
        native_started.set()
        await complete_native_reset.wait()
        monkeypatch.setattr(connection, "_execute", original_execute)
        return await original_execute(operation, *args, **kwargs)

    monkeypatch.setattr(connection, "_execute", delayed_reset)
    rotation = asyncio.create_task(client.rotate_key(replacement_key))
    try:
        await asyncio.wait_for(native_started.wait(), timeout=1)
        client.connection_acquired.clear()
        query = asyncio.create_task(client.execute_query("SELECT 1"))
        await asyncio.sleep(0)
        assert not client.connection_acquired.is_set()

        rotation.cancel()
        await asyncio.sleep(0)
        rotation.cancel()
        complete_native_reset.set()
        with pytest.raises(asyncio.CancelledError) as cancellation:
            await rotation

        notes = getattr(cancellation.value, "__notes__", ())
        assert notes == ["SQLCipher key rotation retained the replacement key; re-read database state"]
        assert original_key.hex() not in "\n".join(notes)
        assert replacement_key.hex() not in "\n".join(notes)
        assert client._encryption_key == replacement_key
        assert (await query)[0] == 1
    finally:
        complete_native_reset.set()
        if not rotation.done():
            rotation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await rotation
        await client.close()


@pytest.mark.anyio
async def test_client_rotation_reports_a_backend_error_when_cancelled_rotation_cannot_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A post-start cancellation is superseded by a disconnected client with no usable key."""
    original_key = bytes.fromhex("1a" * 32)
    replacement_key = bytes.fromhex("1b" * 32)
    client = SqlCipherClient(
        str(tmp_path / "rotation-cancelled-unreconciled.sqlite"), original_key, connection_name="default"
    )
    await client.create_connection(with_db=True)
    connection = client._connection
    assert connection is not None
    original_execute = connection._execute
    native_started = asyncio.Event()
    complete_native_reset = asyncio.Event()

    async def delayed_reset(operation: Callable[..., object], *args: object, **kwargs: object) -> object:
        if getattr(operation, "__name__", None) != "reset_key":
            return await original_execute(operation, *args, **kwargs)
        native_started.set()
        await complete_native_reset.wait()
        monkeypatch.setattr(connection, "_execute", original_execute)
        return await original_execute(operation, *args, **kwargs)

    async def fail_reconnect(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("reconnect failed")

    monkeypatch.setattr(connection, "_execute", delayed_reset)
    monkeypatch.setattr(client, "create_connection", fail_reconnect)
    rotation = asyncio.create_task(client.rotate_key(replacement_key))
    try:
        await asyncio.wait_for(native_started.wait(), timeout=1)
        rotation.cancel()
        complete_native_reset.set()
        with pytest.raises(OperationalError, match="could not restore a usable connection"):
            await rotation
        assert client._connection is None
    finally:
        complete_native_reset.set()
        if not rotation.done():
            rotation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await rotation
        await client.close()


@pytest.mark.anyio
async def test_client_rotation_cancellation_before_exclusive_access_keeps_the_former_key(
    tmp_path: Path,
) -> None:
    """Cancellation before native rotation starts leaves the existing database state alone."""
    original_key = bytes.fromhex("16" * 32)
    client = MaintenanceTestClient(
        str(tmp_path / "rotation-pre-start-cancel.sqlite"), original_key, connection_name="default"
    )
    acquired = asyncio.Event()
    release = asyncio.Event()
    maintenance = asyncio.create_task(client.hold_maintenance(acquired, release))
    try:
        await asyncio.wait_for(acquired.wait(), timeout=1)
        rotation = asyncio.create_task(client.rotate_key(bytes.fromhex("17" * 32)))
        await asyncio.sleep(0)
        rotation.cancel()
        with pytest.raises(asyncio.CancelledError) as cancellation:
            await rotation

        assert not getattr(cancellation.value, "__notes__", ())
        assert client._encryption_key == original_key
        release.set()
        await maintenance
        assert (await client.execute_query("SELECT 1"))[0] == 1
    finally:
        release.set()
        if not maintenance.done():
            await maintenance
        await client.close()


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
