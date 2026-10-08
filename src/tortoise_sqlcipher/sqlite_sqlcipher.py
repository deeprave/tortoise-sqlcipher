"""SQLCipher-backed SQLite client for Tortoise ORM."""

import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from functools import wraps
from importlib import import_module
from typing import Any, ParamSpec, Protocol, TypeVar, cast

import aiosqlite
from tortoise.backends.base.client import ConnectionWrapper, NestedTransactionContext, TransactionContext
from tortoise.backends.sqlite.client import SqliteClient, SqliteTransactionContext, SqliteTransactionWrapper
from tortoise.connection import get_connections
from tortoise.exceptions import ConfigurationError, IntegrityError, OperationalError, TransactionManagementError

Parameters = ParamSpec("Parameters")
Result = TypeVar("Result")


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


sqlcipher = cast(SqlCipherDBAPI, import_module("sqlcipher3.dbapi2"))
sqlcipher.register_adapter(Decimal, str)


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
        if not isinstance(encryption_key, bytes) or len(encryption_key) != 32:
            msg = "SQLCipher keys must contain exactly 32 bytes"
            raise ValueError(msg)
        super().__init__(file_path, **kwargs)
        self._encryption_key = encryption_key

    @translate_sqlcipher_exceptions
    async def create_connection(self, with_db: bool) -> None:
        del with_db
        if self._connection:
            return

        def connector() -> sqlite3.Connection:
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
        if self._connection:
            await self._connection.close()
            self.log.debug(
                "Closed connection %s for filename=%s",
                self._connection,
                self.filename,
            )
            self._connection = None

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
