"""SQLCipher-backed SQLite client for Tortoise ORM."""

import sqlite3
from collections.abc import Awaitable, Callable, Sequence
from functools import wraps
from importlib import import_module
from typing import Any, ParamSpec, Protocol, TypeVar, cast

import aiosqlite
from tortoise.backends.sqlite.client import SqliteClient
from tortoise.exceptions import IntegrityError, OperationalError

Parameters = ParamSpec("Parameters")
Result = TypeVar("Result")


class SqlCipherDBAPI(Protocol):
    """The SQLCipher DB-API surface used by this backend."""

    OperationalError: type[Exception]
    IntegrityError: type[Exception]
    Row: type[sqlite3.Row]

    def connect(self, _database: str, **_kwargs: object) -> sqlite3.Connection: ...


sqlcipher = cast(SqlCipherDBAPI, import_module("sqlcipher3.dbapi2"))


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

    return translated


class SqlCipherClient(SqliteClient):
    """Use SQLCipher through aiosqlite while retaining Tortoise SQLite semantics."""

    def __init__(self, file_path: str, encryption_key: bytes, **kwargs: object) -> None:
        if len(encryption_key) != 32:
            msg = "SQLCipher keys must contain exactly 32 bytes"
            raise ValueError(msg)
        super().__init__(file_path, **kwargs)
        self._encryption_key = encryption_key

    async def create_connection(self, with_db: bool) -> None:
        del with_db
        if self._connection:
            return

        key_literal = self._encryption_key.hex()

        def connector() -> sqlite3.Connection:
            connection = sqlcipher.connect(self.filename, isolation_level=None)
            connection.execute(f"PRAGMA key = \"x'{key_literal}'\"")
            return connection

        connection = aiosqlite.Connection(connector, iter_chunk_size=64)
        self._connection = await connection
        self._connection.row_factory = sqlcipher.Row
        for pragma, value in self.pragmas.items():
            cursor = await self._connection.execute(f"PRAGMA {pragma}={value}")
            await cursor.close()
        await self._post_connect()
        self.log.debug("Created SQLCipher connection for filename=%s", self.filename)

    @translate_sqlcipher_exceptions
    async def execute_insert(self, query: str, values: list[Any]) -> int:
        return await super().execute_insert(query, values)

    @translate_sqlcipher_exceptions
    async def execute_many(self, query: str, values: list[list[Any]]) -> None:
        await super().execute_many(query, values)

    @translate_sqlcipher_exceptions
    async def execute_query(self, query: str, values: list[Any] | None = None) -> tuple[int, Sequence[dict[str, Any]]]:
        return await super().execute_query(query, values)

    @translate_sqlcipher_exceptions
    async def execute_query_dict(self, query: str, values: list[Any] | None = None) -> list[dict[str, Any]]:
        return await super().execute_query_dict(query, values)

    @translate_sqlcipher_exceptions
    async def execute_script(self, query: str) -> None:
        await super().execute_script(query)


client_class = SqlCipherClient
