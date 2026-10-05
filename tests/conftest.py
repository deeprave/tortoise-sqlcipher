"""Shared fixtures for SQLCipher integration tests."""

from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import TypeAlias

import pytest
from tortoise import Tortoise
from tortoise.migrations.api import migrate

from tests.sqlcipher_support import close_tortoise_connections, database_config, sqlite_database_config

DatabaseInitializer: TypeAlias = Callable[[str, bytes, bool, bool], Awaitable[Path]]


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    """Keep module-scoped async fixtures on one asyncio backend."""
    return "asyncio"


@pytest.fixture
async def tortoise_database(tmp_path: Path) -> AsyncIterator[DatabaseInitializer]:
    """Initialize an isolated database and always release Tortoise connections."""

    async def initialize(name: str, encryption_key: bytes, use_migrations: bool, use_sqlcipher: bool) -> Path:
        database_path = tmp_path / name
        config = (
            database_config(database_path, encryption_key) if use_sqlcipher else sqlite_database_config(database_path)
        )
        try:
            if use_migrations:
                await migrate(config=config)
            await Tortoise.init(config=config)
            if not use_migrations:
                await Tortoise.generate_schemas()
            return database_path
        except BaseException:
            await close_tortoise_connections()
            raise

    try:
        yield initialize
    finally:
        await close_tortoise_connections()


@pytest.fixture(scope="module")
async def scalar_matrix_database(tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[Path]:
    """Create one encrypted database for isolated, parametrized scalar rows."""
    database_path = tmp_path_factory.mktemp("scalar-matrix") / "fields.sqlite"
    try:
        await Tortoise.init(config=database_config(database_path))
        await Tortoise.generate_schemas()
        yield database_path
    finally:
        await close_tortoise_connections()
