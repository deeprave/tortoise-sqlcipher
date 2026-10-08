"""Behavior-focused integration tests for the SQLCipher Tortoise backend."""

import sqlite3
from asyncio import gather
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from tortoise import Tortoise
from tortoise.exceptions import ConfigurationError
from tortoise.transactions import in_transaction

from tests.sqlcipher_models import Color, EncryptedRecord, FieldRecord, Rank, RelationRecord, RelationTarget
from tests.sqlcipher_support import TEST_KEY, database_config, open_sqlcipher_database, sqlcipher
from tortoise_sqlcipher.sqlite_sqlcipher import SqlCipherClient

DatabaseInitializer = Callable[[str, bytes, bool, bool], Awaitable[Path]]

FIELD_VALUES = {
    "int_value": 1,
    "big_int_value": 2,
    "small_int_value": 3,
    "char_value": "char",
    "text_value": "text",
    "bool_value": True,
    "decimal_value": Decimal("12.34"),
    "datetime_value": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    "date_value": date(2026, 1, 2),
    "timedelta_value": timedelta(days=1, seconds=2),
    "float_value": 1.25,
    "json_value": {"key": ["value"]},
    "uuid_value": UUID("12345678-1234-5678-1234-567812345678"),
    "binary_value": b"binary-value",
    "char_enum_value": Color.RED,
    "int_enum_value": Rank.LOW,
}


def assert_ordinary_sqlite_rejects(database_path: Path) -> None:
    """Verify the encrypted database does not answer ordinary SQLite queries."""
    ordinary_connection = sqlite3.connect(database_path)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            ordinary_connection.execute("SELECT * FROM encryptedrecord").fetchall()
    finally:
        ordinary_connection.close()


@pytest.fixture(params=[("sqlcipher", True, sqlcipher.InterfaceError), ("sqlite", False, sqlite3.ProgrammingError)])
def timefield_engine(request: pytest.FixtureRequest) -> tuple[str, bool, type[Exception]]:
    """Provide the two SQLite drivers for the documented TimeField limitation."""
    return request.param


@pytest.mark.anyio
async def test_native_migration_initializes_an_encrypted_database(tortoise_database: DatabaseInitializer) -> None:
    """Native Tortoise migrations create a schema through the SQLCipher engine."""
    database_path = await tortoise_database("migrated.sqlite", TEST_KEY, True, True)
    await EncryptedRecord.create(value="migrated")
    assert await EncryptedRecord.filter(value="migrated").count() == 1
    assert_ordinary_sqlite_rejects(database_path)


@pytest.mark.anyio
async def test_database_fixture_closes_connections_after_setup_failure(
    monkeypatch: pytest.MonkeyPatch, tortoise_database: DatabaseInitializer
) -> None:
    """Fixture teardown closes Tortoise after initialization fails during setup."""

    async def fail_schema_generation() -> None:
        raise RuntimeError("schema setup failed")

    monkeypatch.setattr(Tortoise, "generate_schemas", fail_schema_generation)
    with pytest.raises(RuntimeError, match="schema setup failed"):
        await tortoise_database("failed-setup.sqlite", TEST_KEY, False, True)
    with pytest.raises(ConfigurationError, match="not initialised"):
        Tortoise.get_connection("default")


@pytest.mark.anyio
@pytest.mark.parametrize(("field_name", "expected"), FIELD_VALUES.items())
async def test_sqlite_supported_scalar_fields_round_trip(
    scalar_matrix_database: Path, field_name: str, expected: object
) -> None:
    """Each scalar field uses an isolated row in the shared encrypted matrix database."""
    created = FieldRecord(**{field_name: expected})
    await created.save()
    restored = await FieldRecord.get(id=created.id)
    assert getattr(restored, field_name) == expected


@pytest.mark.anyio
async def test_standard_sqlite_relation_variants_round_trip(tortoise_database: DatabaseInitializer) -> None:
    """Foreign-key, one-to-one, and many-to-many relations persist through SQLCipher."""
    await tortoise_database("relations.sqlite", TEST_KEY, False, True)
    first_target = await RelationTarget.create(name="first")
    second_target = await RelationTarget.create(name="second")
    record = await RelationRecord.create(foreign_target=first_target, one_to_one_target=second_target)
    await record.many_targets.add(first_target, second_target)
    restored = await RelationRecord.get(id=record.id).prefetch_related(
        "foreign_target", "one_to_one_target", "many_targets"
    )
    assert restored.foreign_target.name == "first"
    assert restored.one_to_one_target.name == "second"
    assert {target.name for target in restored.many_targets} == {"first", "second"}
    assert await first_target.foreign_records.all().count() == 1
    assert await second_target.one_to_one_record == restored
    assert await first_target.many_records.all().count() == 1


@pytest.mark.anyio
async def test_native_migration_supports_field_and_relation_round_trip(tortoise_database: DatabaseInitializer) -> None:
    """Native migration DDL supports representative scalar and relation behavior."""
    await tortoise_database("migrated-matrix.sqlite", TEST_KEY, True, True)
    field_record = await FieldRecord.create(char_enum_value=Color.BLUE, int_enum_value=Rank.HIGH)
    target = await RelationTarget.create(name="target")
    record = await RelationRecord.create(foreign_target=target, one_to_one_target=target)
    await record.many_targets.add(target)
    restored_field = await FieldRecord.get(id=field_record.id)
    restored_relation = await RelationRecord.get(id=record.id).prefetch_related("many_targets")
    assert restored_field.char_enum_value is Color.BLUE
    assert restored_field.int_enum_value is Rank.HIGH
    assert {related.name for related in restored_relation.many_targets} == {"target"}


@pytest.mark.anyio
async def test_time_field_retains_tortoise_sqlite_binding_limitation(
    timefield_engine: tuple[str, bool, type[Exception]], tortoise_database: DatabaseInitializer
) -> None:
    """Both drivers reject the unsupported TimeField bind without creating a row."""
    engine_name, use_sqlcipher, expected_error = timefield_engine
    await tortoise_database(f"time-{engine_name}.sqlite", TEST_KEY, False, use_sqlcipher)
    with pytest.raises(expected_error):
        await FieldRecord.create(time_value=time(3, 4, 5))
    assert await FieldRecord.all().count() == 0


@pytest.mark.anyio
async def test_database_and_live_sidecars_do_not_expose_plaintext(tortoise_database: DatabaseInitializer) -> None:
    """SQLCipher encrypts the database and each sidecar produced by a live write."""
    database_path = await tortoise_database("encrypted.sqlite", TEST_KEY, False, True)
    secret_value = "database-record-value-that-must-not-be-plaintext"
    await EncryptedRecord.create(value=secret_value)
    encrypted_files = [database_path, *database_path.parent.glob(f"{database_path.name}-*")]
    assert database_path.with_name(f"{database_path.name}-wal") in encrypted_files
    for encrypted_file in encrypted_files:
        contents = encrypted_file.read_bytes()
        assert b"encryptedrecord" not in contents
        assert secret_value.encode() not in contents
    assert_ordinary_sqlite_rejects(database_path)


@pytest.mark.anyio
async def test_migrated_transaction_rollback_discards_records(tortoise_database: DatabaseInitializer) -> None:
    """A transaction rollback leaves no record in a migrated encrypted database."""
    await tortoise_database("rollback.sqlite", TEST_KEY, True, True)
    with pytest.raises(RuntimeError, match="rollback"):
        async with in_transaction() as connection:
            await EncryptedRecord.create(value="discard", using_db=connection)
            raise RuntimeError("rollback")
    assert await EncryptedRecord.filter(value="discard").count() == 0


@pytest.mark.anyio
async def test_migrated_concurrent_writes_persist_all_records(tortoise_database: DatabaseInitializer) -> None:
    """Concurrent ORM writes persist every record in a migrated encrypted database."""
    await tortoise_database("concurrent.sqlite", TEST_KEY, True, True)
    await gather(*(EncryptedRecord.create(value=f"record-{number}") for number in range(10)))
    assert await EncryptedRecord.all().count() == 10


async def read_record_through_backend(database_path: Path, encryption_key: bytes) -> str:
    """Read a record through the package engine using the supplied SQLCipher key."""
    await Tortoise.init(config=database_config(database_path, encryption_key))
    try:
        return (await EncryptedRecord.get()).value
    finally:
        await Tortoise.close_connections()


@pytest.mark.anyio
async def test_rekeyed_database_and_native_backup_require_the_replacement_key(
    tortoise_database: DatabaseInitializer,
) -> None:
    """SQLCipher rekeying protects both the source database and native backup."""
    original_key = bytes.fromhex("01" * 32)
    replacement_key = bytes.fromhex("02" * 32)
    database_path = await tortoise_database("rekeyed.sqlite", original_key, False, True)
    backup_path = database_path.with_name("rekeyed-backup.sqlite")
    record_value = "rekeyed-record"
    await EncryptedRecord.create(value=record_value)
    await Tortoise.close_connections()
    source_connection = open_sqlcipher_database(database_path, original_key)
    backup_connection = open_sqlcipher_database(backup_path, replacement_key)
    try:
        source_connection.reset_key(replacement_key)
        source_connection.backup(backup_connection)
    finally:
        backup_connection.close()
        source_connection.close()
    old_key_connection = open_sqlcipher_database(database_path, original_key)
    try:
        with pytest.raises(sqlcipher.DatabaseError):
            old_key_connection.execute("SELECT * FROM encryptedrecord").fetchall()
    finally:
        old_key_connection.close()
    assert await read_record_through_backend(database_path, replacement_key) == record_value
    assert await read_record_through_backend(backup_path, replacement_key) == record_value


@pytest.mark.anyio
async def test_public_key_rotation_reopens_the_database_with_the_replacement_key(
    tortoise_database: DatabaseInitializer,
) -> None:
    """The client rotates through its public API and retains only the replacement key."""
    original_key = bytes.fromhex("03" * 32)
    replacement_key = bytes.fromhex("04" * 32)
    database_path = await tortoise_database("public-rekey.sqlite", original_key, False, True)
    record_value = "public-rekey-record"
    await EncryptedRecord.create(value=record_value)

    client = cast(SqlCipherClient, Tortoise.get_connection("default"))
    assert await client.rotate_key(replacement_key) is None
    assert await EncryptedRecord.get().values_list("value", flat=True) == record_value

    await Tortoise.close_connections()
    old_key_connection = open_sqlcipher_database(database_path, original_key)
    try:
        with pytest.raises(sqlcipher.DatabaseError):
            old_key_connection.execute("SELECT * FROM encryptedrecord").fetchall()
    finally:
        old_key_connection.close()
    assert await read_record_through_backend(database_path, replacement_key) == record_value


@pytest.mark.anyio
async def test_public_snapshot_operations_preserve_tortoise_model_access(
    tortoise_database: DatabaseInitializer,
) -> None:
    """Tortoise reads the restored model state through the refreshed SQLCipher client."""
    database_path = await tortoise_database("public-snapshot.sqlite", TEST_KEY, False, True)
    snapshot_path = database_path.with_name("public-snapshot-backup.sqlite")
    client = cast(SqlCipherClient, Tortoise.get_connection("default"))
    await EncryptedRecord.create(value="snapshot")
    assert database_path.with_name(f"{database_path.name}-wal").exists()
    await client.backup(snapshot_path)
    await EncryptedRecord.all().delete()
    await EncryptedRecord.create(value="changed")

    assert await client.restore(snapshot_path) is None
    assert await EncryptedRecord.get().values_list("value", flat=True) == "snapshot"

    await Tortoise.close_connections()
    assert await read_record_through_backend(snapshot_path, TEST_KEY) == "snapshot"
