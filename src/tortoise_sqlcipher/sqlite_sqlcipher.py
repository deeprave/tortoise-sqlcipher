"""SQLCipher-backed SQLite client for Tortoise ORM."""

import asyncio
import os
import sqlite3
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from functools import wraps
from importlib import import_module
from pathlib import Path
from typing import Any, ParamSpec, Protocol, TypeVar, cast

import aiosqlite
from tortoise.backends.base.client import ConnectionWrapper, NestedTransactionContext, TransactionContext
from tortoise.backends.sqlite.client import SqliteClient, SqliteTransactionContext, SqliteTransactionWrapper
from tortoise.connection import get_connections
from tortoise.exceptions import ConfigurationError, IntegrityError, OperationalError, TransactionManagementError

Parameters = ParamSpec("Parameters")
Result = TypeVar("Result")


@dataclass(frozen=True)
class KeyRotationOutcome:
    """The reconciled state of a completed key-rotation attempt."""

    native_error: Exception | None
    retained_key: bytes | None
    reconnect_error: Exception | None
    cancellation: asyncio.CancelledError | None


class SqlCipherDBAPI(Protocol):
    """The SQLCipher DB-API surface used by this backend."""

    OperationalError: type[Exception]
    IntegrityError: type[Exception]
    DatabaseError: type[Exception]
    Row: type[sqlite3.Row]

    def connect(self, _database: str, **_kwargs: object) -> sqlite3.Connection: ...

    def register_adapter(self, _type: type[Any], _adapter: Callable[[Any], str]) -> None: ...


class SqlCipherConnection(Protocol):
    """The SQLCipher-specific connection operation used during setup."""

    def set_key(self, _key: bytes) -> None: ...

    def reset_key(self, _key: bytes) -> None: ...

    def backup(self, _target: "SqlCipherConnection") -> None: ...

    def execute(self, _statement: str) -> Any: ...

    def close(self) -> None: ...


sqlcipher = cast(SqlCipherDBAPI, import_module("sqlcipher3.dbapi2"))
sqlcipher.register_adapter(Decimal, str)


def _validate_encryption_key(encryption_key: bytes) -> None:
    """Reject key values outside the package's binary 32-byte contract."""
    if not isinstance(encryption_key, bytes) or len(encryption_key) != 32:
        msg = "SQLCipher keys must contain exactly 32 bytes"
        raise ValueError(msg)


def _snapshot_path(path: str | os.PathLike[str], operation: str) -> Path:
    """Return a persistent filesystem path accepted by a snapshot operation."""
    raw_path = os.fspath(path)
    if not isinstance(raw_path, str):
        msg = f"SQLCipher {operation} path must be text"
        raise TypeError(msg)
    if not raw_path or raw_path == ":memory:" or raw_path.startswith("file:"):
        msg = f"SQLCipher {operation} requires a persistent filesystem path"
        raise ValueError(msg)
    return Path(raw_path)


def _temporary_database_path(directory: Path, operation: str) -> Path:
    """Reserve a same-filesystem path for an encrypted temporary database."""
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{operation}-", suffix=".sqlite", dir=directory)
    os.close(descriptor)
    path = Path(raw_path)
    path.unlink()
    return path


def _database_artifacts(path: Path) -> tuple[Path, Path, Path]:
    """Return the database file and its SQLite sidecars."""
    return path, Path(f"{path}-wal"), Path(f"{path}-shm")


def _move_database_artifacts(source: Path, destination: Path) -> None:
    """Move a database and any sidecars to a matching rollback location."""
    for source_artifact, destination_artifact in zip(
        _database_artifacts(source), _database_artifacts(destination), strict=True
    ):
        if source_artifact.exists():
            os.replace(source_artifact, destination_artifact)


def _remove_database_artifacts(path: Path) -> None:
    """Remove a database and its sidecars after their replacement is verified."""
    for artifact in _database_artifacts(path):
        artifact.unlink(missing_ok=True)


def _open_snapshot_connection(path: Path, encryption_key: bytes) -> SqlCipherConnection:
    """Open an encrypted database for a native SQLCipher copy operation."""
    connection = cast(SqlCipherConnection, sqlcipher.connect(str(path), isolation_level=None))
    connection.set_key(encryption_key)
    return connection


async def is_mem_db(connection: aiosqlite.Connection) -> bool:
    """Return whether SQLite reports its main database without a backing file."""
    cursor = await connection.execute("PRAGMA database_list")
    try:
        database = next(iter(await cursor.fetchall()))
        return database[2] == ""
    finally:
        await cursor.close()


def translate_sqlcipher_exceptions(
    operation: Callable[Parameters, Awaitable[Result]],
) -> Callable[Parameters, Awaitable[Result]]:
    """Map SQLCipher DB-API errors to the exceptions Tortoise expects."""

    @wraps(operation)
    async def translated(*args: Parameters.args, **kwargs: Parameters.kwargs) -> Result:
        try:
            return await operation(*args, **kwargs)
        except sqlcipher.OperationalError as error:
            raise OperationalError(error) from error
        except sqlcipher.IntegrityError as error:
            raise IntegrityError(error) from error
        except sqlcipher.DatabaseError as error:
            raise OperationalError(error) from error

    return translated


class SqlCipherQueryMixin:
    """Apply SQLCipher exception translation to Tortoise query operations."""

    @translate_sqlcipher_exceptions
    async def execute_insert(self, query: str, values: list[Any]) -> int:
        return await cast(Any, super()).execute_insert(query, values)

    @translate_sqlcipher_exceptions
    async def execute_many(self, query: str, values: list[list[Any]]) -> None:
        await cast(Any, super()).execute_many(query, values)

    @translate_sqlcipher_exceptions
    async def execute_query(self, query: str, values: list[Any] | None = None) -> tuple[int, Sequence[dict[str, Any]]]:
        return await cast(Any, super()).execute_query(query, values)

    @translate_sqlcipher_exceptions
    async def execute_query_dict(self, query: str, values: list[Any] | None = None) -> list[dict[str, Any]]:
        return await cast(Any, super()).execute_query_dict(query, values)

    @translate_sqlcipher_exceptions
    async def execute_script(self, query: str) -> None:
        await cast(Any, super()).execute_script(query)


class SqlCipherConnectionWrapper(ConnectionWrapper[aiosqlite.Connection]):
    """Release an acquired lock when opening a SQLCipher connection fails."""

    async def __aenter__(self) -> aiosqlite.Connection:
        await self._lock.acquire()
        try:
            self.connection = self.client._connection
            await self.ensure_connection()
            return self.connection
        except BaseException:
            self._lock.release()
            raise


class SqlCipherTransactionContext(SqliteTransactionContext):
    """Release the transaction lock if connection setup or BEGIN fails."""

    async def __aenter__(self) -> "SqlCipherTransactionWrapper":
        await self._trxlock.acquire()
        token_set = False
        try:
            await self.ensure_connection()
            self.token = get_connections().set(self.connection_name, self.connection)
            token_set = True
            await self.connection.begin()
            return self.connection
        except BaseException:
            if token_set:
                get_connections().reset(self.token)
            self._trxlock.release()
            raise


class SqlCipherClient(SqlCipherQueryMixin, SqliteClient):
    """Use SQLCipher through aiosqlite while retaining Tortoise SQLite semantics."""

    def __init__(self, file_path: str, encryption_key: bytes, **kwargs: object) -> None:
        _validate_encryption_key(encryption_key)
        super().__init__(file_path, **kwargs)
        self._encryption_key: bytes | None = encryption_key

    @translate_sqlcipher_exceptions
    async def create_connection(self, with_db: bool) -> None:
        del with_db
        if self._connection:
            return

        def connector() -> sqlite3.Connection:
            if self._encryption_key is None:
                msg = "SQLCipher connection has no verified encryption key"
                raise OperationalError(msg)
            connection = sqlcipher.connect(self.filename, isolation_level=None)
            cast(SqlCipherConnection, connection).set_key(self._encryption_key)
            return connection

        connection = aiosqlite.Connection(connector, iter_chunk_size=64)
        initialized = False
        try:
            await connection
            connection.row_factory = sqlcipher.Row
            for pragma, value in self.pragmas.items():
                if not pragma.isidentifier():
                    msg = f"Invalid SQLite pragma name: {pragma}"
                    raise ValueError(msg)
                cursor = await connection.execute("SELECT quote(?)", (value,))
                quoted_value = cast(str, cast(sqlite3.Row, await cursor.fetchone())[0])
                await cursor.close()
                cursor = await connection.execute("".join(("PRAGMA ", pragma, "=", quoted_value)))
                await cursor.close()
            await self._post_connect()
            self._connection = connection
            initialized = True
            self.log.debug("Created SQLCipher connection for filename=%s", self.filename)
        finally:
            if not initialized:
                await connection.close()

    def _in_transaction(self) -> TransactionContext:
        return SqlCipherTransactionContext(SqlCipherTransactionWrapper(self), self._lock)

    def acquire_connection(self) -> SqlCipherConnectionWrapper:
        return SqlCipherConnectionWrapper(self._lock, self)

    def _has_active_transaction(self) -> bool:
        """Return whether this task holds a transaction for this client."""
        try:
            current_connection = get_connections().get(self.connection_name)
        except (ConfigurationError, RuntimeError):
            return False
        return isinstance(current_connection, SqlCipherTransactionWrapper) and current_connection._parent is self

    @asynccontextmanager
    async def _maintenance_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Acquire exclusive client access for a database maintenance operation."""
        if self._has_active_transaction():
            msg = "Database maintenance cannot run inside an active transaction"
            raise TransactionManagementError(msg)
        async with self.acquire_connection() as connection:
            yield connection

    async def _close_connection(self) -> None:
        """Close the current connection while the caller owns the client boundary."""
        connection = self._connection
        if connection:
            self._connection = None
            try:
                await connection.close()
            finally:
                self._connection = None
            self.log.debug(
                "Closed connection %s for filename=%s",
                connection,
                self.filename,
            )

    async def _reopen_after_key_rotation(
        self, replacement_key: bytes, former_key: bytes, native_error: Exception | None
    ) -> KeyRotationOutcome:
        """Reconnect with a verified key after SQLCipher reports a rotation outcome."""
        reconnect_error: Exception | None = None
        try:
            await self._close_connection()
        except Exception as error:
            reconnect_error = error

        candidate_keys = (replacement_key,) if native_error is None else (replacement_key, former_key)
        for encryption_key in candidate_keys:
            self._encryption_key = encryption_key
            try:
                await self.create_connection(with_db=True)
            except Exception as error:
                reconnect_error = error
                continue
            return KeyRotationOutcome(native_error, encryption_key, reconnect_error, None)
        self._encryption_key = None
        return KeyRotationOutcome(native_error, None, reconnect_error, None)

    async def _complete_key_rotation(
        self, connection: aiosqlite.Connection, replacement_key: bytes, former_key: bytes
    ) -> KeyRotationOutcome:
        """Run native rotation and reconcile the client with a usable database key."""
        native_connection = cast(SqlCipherConnection, connection._conn)
        native_error: Exception | None = None
        try:

            def reset_key() -> None:
                native_connection.reset_key(replacement_key)

            await connection._execute(reset_key)
        except Exception as error:
            native_error = error
        return await self._reopen_after_key_rotation(replacement_key, former_key, native_error)

    async def _complete_key_rotation_after_cancellation(
        self, connection: aiosqlite.Connection, replacement_key: bytes, former_key: bytes
    ) -> KeyRotationOutcome:
        """Finish a dispatched rotation before reporting any caller cancellation."""
        completion = asyncio.create_task(self._complete_key_rotation(connection, replacement_key, former_key))
        cancellation: asyncio.CancelledError | None = None
        while not completion.done():
            try:
                await asyncio.shield(completion)
            except asyncio.CancelledError as error:
                if cancellation is None:
                    cancellation = error
        return replace(completion.result(), cancellation=cancellation)

    async def _copy_connection_to_path(
        self, connection: aiosqlite.Connection, destination: Path, encryption_key: bytes
    ) -> None:
        """Copy the active SQLCipher database into an encrypted filesystem path."""
        source = cast(SqlCipherConnection, connection._conn)

        def copy_database() -> None:
            target = _open_snapshot_connection(destination, encryption_key)
            try:
                source.backup(target)
            finally:
                target.close()

        await connection._execute(copy_database)

    async def _copy_path_to_connection(
        self, source_path: Path, destination: aiosqlite.Connection, encryption_key: bytes
    ) -> None:
        """Copy an encrypted filesystem snapshot into the active SQLCipher connection."""
        target = cast(SqlCipherConnection, destination._conn)

        def copy_database() -> None:
            source = _open_snapshot_connection(source_path, encryption_key)
            try:
                source.execute("PRAGMA schema_version")
                source.backup(target)
            finally:
                source.close()

        await destination._execute(copy_database)

    async def _copy_path_to_path(self, source: Path, destination: Path, encryption_key: bytes) -> None:
        """Create and validate an encrypted restore candidate from a snapshot file."""

        def copy_database() -> None:
            source_connection = _open_snapshot_connection(source, encryption_key)
            try:
                source_connection.execute("PRAGMA schema_version")
                target_connection = _open_snapshot_connection(destination, encryption_key)
                try:
                    source_connection.backup(target_connection)
                finally:
                    target_connection.close()
            finally:
                source_connection.close()

        await asyncio.to_thread(copy_database)

    async def _restore_memory_database(
        self, connection: aiosqlite.Connection, snapshot: Path, encryption_key: bytes
    ) -> None:
        """Restore a snapshot into memory while retaining an encrypted rollback copy."""
        rollback = _temporary_database_path(Path(tempfile.gettempdir()), "tortoise-sqlcipher-rollback")
        await self._copy_connection_to_path(connection, rollback, encryption_key)
        try:
            await self._copy_path_to_connection(snapshot, connection, encryption_key)
        except BaseException:
            try:
                await self._copy_path_to_connection(rollback, connection, encryption_key)
            except BaseException as recovery_error:
                msg = "SQLCipher memory restore could not recover the original database"
                raise OperationalError(msg) from recovery_error
            raise
        finally:
            _remove_database_artifacts(rollback)

    async def _restore_file_database(
        self, connection: aiosqlite.Connection, snapshot: Path, encryption_key: bytes
    ) -> None:
        """Restore a snapshot through a staged candidate and recoverable file replacement."""
        database = Path(self.filename)
        candidate = _temporary_database_path(database.parent, "tortoise-sqlcipher-restore")
        rollback = _temporary_database_path(database.parent, "tortoise-sqlcipher-rollback")
        await self._copy_path_to_path(snapshot, candidate, encryption_key)
        try:
            await self._close_connection()
            _move_database_artifacts(database, rollback)
            os.replace(candidate, database)
            await self.create_connection(with_db=True)
        except BaseException:
            try:
                await self._close_connection()
                _remove_database_artifacts(database)
                _move_database_artifacts(rollback, database)
                await self.create_connection(with_db=True)
            except BaseException as recovery_error:
                msg = "SQLCipher restore could not recover the original database"
                raise OperationalError(msg) from recovery_error
            raise
        else:
            _remove_database_artifacts(rollback)
        finally:
            _remove_database_artifacts(candidate)

    async def _complete_snapshot_operation(self, operation: Awaitable[None], name: str) -> None:
        """Finish a dispatched snapshot operation before reporting caller cancellation."""
        completion = asyncio.ensure_future(operation)
        cancellation: asyncio.CancelledError | None = None
        while not completion.done():
            try:
                await asyncio.shield(completion)
            except asyncio.CancelledError as error:
                if cancellation is None:
                    cancellation = error
        completion.result()
        if cancellation is not None:
            cancellation.add_note(f"SQLCipher {name} completed; re-read database state")
            raise cancellation

    @translate_sqlcipher_exceptions
    async def is_mem_db(self) -> bool:
        """Return whether this client currently uses a database without a backing file."""
        async with self.acquire_connection() as connection:
            return await is_mem_db(connection)

    @translate_sqlcipher_exceptions
    async def backup(self, destination: str | os.PathLike[str]) -> None:
        """Create an encrypted snapshot at a persistent filesystem destination."""
        destination_path = _snapshot_path(destination, "backup")
        async with self._maintenance_connection() as connection:
            if not await is_mem_db(connection) and destination_path.resolve() == Path(self.filename).resolve():
                msg = "SQLCipher backup destination must differ from the active database"
                raise ValueError(msg)
            encryption_key = cast(bytes, self._encryption_key)
            await self._complete_snapshot_operation(
                self._copy_connection_to_path(connection, destination_path, encryption_key), "backup"
            )

    @translate_sqlcipher_exceptions
    async def restore(self, snapshot: str | os.PathLike[str]) -> None:
        """Restore an encrypted snapshot while retaining a recoverable database state."""
        snapshot_path = _snapshot_path(snapshot, "restore")
        if not snapshot_path.is_file():
            msg = "SQLCipher restore snapshot must be an existing file"
            raise ValueError(msg)
        async with self._maintenance_connection() as connection:
            encryption_key = cast(bytes, self._encryption_key)
            operation = (
                self._restore_memory_database(connection, snapshot_path, encryption_key)
                if await is_mem_db(connection)
                else self._restore_file_database(connection, snapshot_path, encryption_key)
            )
            await self._complete_snapshot_operation(operation, "restore")

    @translate_sqlcipher_exceptions
    async def rotate_key(self, replacement_key: bytes) -> None:
        """Replace the database key and reconnect with the verified replacement."""
        _validate_encryption_key(replacement_key)
        async with self._maintenance_connection() as connection:
            if await is_mem_db(connection):
                msg = "SQLCipher key rotation requires a persistent database"
                raise OperationalError(msg)
            # A maintenance connection can only exist after create_connection
            # has verified and applied this key.
            former_key = cast(bytes, self._encryption_key)
            outcome = await self._complete_key_rotation_after_cancellation(connection, replacement_key, former_key)

            if outcome.retained_key is None:
                msg = "SQLCipher key rotation could not restore a usable connection"
                raise OperationalError(msg) from outcome.reconnect_error

            if outcome.cancellation is not None:
                retained = "replacement" if outcome.retained_key == replacement_key else "former"
                outcome.cancellation.add_note(
                    f"SQLCipher key rotation retained the {retained} key; re-read database state"
                )
                raise outcome.cancellation

            if outcome.native_error is not None:
                if outcome.retained_key == replacement_key:
                    self.log.warning(
                        "SQLCipher key rotation retained the verified replacement key after a native error for filename=%s",
                        self.filename,
                    )
                    return
                raise outcome.native_error

            return

    async def close(self) -> None:
        """Close the client connection without racing maintenance operations."""
        if self._has_active_transaction():
            msg = "Database connection cannot close inside an active transaction"
            raise TransactionManagementError(msg)
        async with self._lock:
            await self._close_connection()


class SqlCipherTransactionWrapper(SqlCipherQueryMixin, SqliteTransactionWrapper):
    """Translate SQLCipher errors from Tortoise transaction operations."""

    def _in_transaction(self) -> TransactionContext:
        return NestedTransactionContext(SqlCipherTransactionWrapper(self))

    async def begin(self) -> None:
        try:
            await self._connection.commit()
            await self._connection.execute("BEGIN")
        except sqlcipher.OperationalError as error:
            raise TransactionManagementError(error) from error

    @translate_sqlcipher_exceptions
    async def rollback(self) -> None:
        await super().rollback()

    @translate_sqlcipher_exceptions
    async def commit(self) -> None:
        await super().commit()

    @translate_sqlcipher_exceptions
    async def savepoint(self) -> None:
        await super().savepoint()

    @translate_sqlcipher_exceptions
    async def savepoint_rollback(self) -> None:
        await super().savepoint_rollback()

    @translate_sqlcipher_exceptions
    async def release_savepoint(self) -> None:
        await super().release_savepoint()


client_class = SqlCipherClient
