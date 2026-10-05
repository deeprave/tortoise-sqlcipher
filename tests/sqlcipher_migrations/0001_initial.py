"""Create disposable SQLCipher integration-test tables."""

from typing import cast

from tortoise import fields
from tortoise.migrations import CreateModel
from tortoise.migrations.migration import Migration

from tests.sqlcipher_models import Color, Rank


class Migration(Migration):
    """Initial schema for package-owned SQLCipher integration fixtures."""

    dependencies = []
    operations = [
        CreateModel(
            name="EncryptedRecord",
            fields=[
                ("id", fields.IntField(primary_key=True)),
                ("value", fields.CharField(max_length=254)),
            ],
            options={},
        ),
        CreateModel(
            name="FieldRecord",
            fields=[
                ("id", fields.IntField(primary_key=True)),
                ("int_value", fields.IntField(null=True)),
                ("big_int_value", fields.BigIntField(null=True)),
                ("small_int_value", fields.SmallIntField(null=True)),
                ("char_value", fields.CharField(max_length=32, null=True)),
                ("text_value", fields.TextField(null=True)),
                ("bool_value", fields.BooleanField(null=True)),
                ("decimal_value", fields.DecimalField(max_digits=10, decimal_places=2, null=True)),
                ("datetime_value", fields.DatetimeField(null=True)),
                ("date_value", fields.DateField(null=True)),
                ("time_value", fields.TimeField(null=True)),
                ("timedelta_value", fields.TimeDeltaField(null=True)),
                ("float_value", fields.FloatField(null=True)),
                ("json_value", fields.JSONField(null=True)),
                ("uuid_value", fields.UUIDField(null=True)),
                ("binary_value", fields.BinaryField(null=True)),
                ("char_enum_value", cast(fields.Field[Color], fields.CharEnumField(Color, null=True))),
                ("int_enum_value", cast(fields.Field[Rank], fields.IntEnumField(Rank, null=True))),
            ],
            options={},
        ),
        CreateModel(
            name="RelationTarget",
            fields=[
                ("id", fields.IntField(primary_key=True)),
                ("name", fields.CharField(max_length=32)),
            ],
            options={},
        ),
        CreateModel(
            name="RelationRecord",
            fields=[
                ("id", fields.IntField(primary_key=True)),
                (
                    "foreign_target",
                    fields.ForeignKeyField("models.RelationTarget", related_name="foreign_records"),
                ),
                (
                    "one_to_one_target",
                    fields.OneToOneField("models.RelationTarget", related_name="one_to_one_record"),
                ),
                (
                    "many_targets",
                    fields.ManyToManyField("models.RelationTarget", related_name="many_records"),
                ),
            ],
            options={},
        ),
    ]
