"""Disposable Tortoise models used by SQLCipher integration tests."""

from enum import IntEnum, StrEnum

from tortoise import fields
from tortoise.models import Model


class EncryptedRecord(Model):
    """A minimal persisted record for backend lifecycle tests."""

    id: int
    value = fields.CharField(max_length=254)


class Color(StrEnum):
    """A deterministic value for CharEnumField integration coverage."""

    RED = "red"
    BLUE = "blue"


class Rank(IntEnum):
    """A deterministic value for IntEnumField integration coverage."""

    LOW = 1
    HIGH = 2


class FieldRecord(Model):
    """Every scalar Tortoise field that SQLite supports through this backend."""

    id: int
    int_value = fields.IntField(null=True)
    big_int_value = fields.BigIntField(null=True)
    small_int_value = fields.SmallIntField(null=True)
    char_value = fields.CharField(max_length=32, null=True)
    text_value = fields.TextField(null=True)
    bool_value = fields.BooleanField(null=True)
    decimal_value = fields.DecimalField(max_digits=10, decimal_places=2, null=True)
    datetime_value = fields.DatetimeField(null=True)
    date_value = fields.DateField(null=True)
    time_value = fields.TimeField(null=True)
    timedelta_value = fields.TimeDeltaField(null=True)
    float_value = fields.FloatField(null=True)
    json_value = fields.JSONField(null=True)
    uuid_value = fields.UUIDField(null=True)
    binary_value = fields.BinaryField(null=True)
    char_enum_value = fields.CharEnumField(Color, null=True)
    int_enum_value = fields.IntEnumField(Rank, null=True)


class RelationTarget(Model):
    """Target for the standard SQLite relation variants."""

    id: int
    foreign_records: fields.ReverseRelation["RelationRecord"]
    one_to_one_record: "RelationRecord"
    many_records: fields.ManyToManyRelation["RelationRecord"]
    name = fields.CharField(max_length=32)


class RelationRecord(Model):
    """Exercise foreign-key, one-to-one, and many-to-many persistence."""

    foreign_target = fields.ForeignKeyField("models.RelationTarget", related_name="foreign_records")
    one_to_one_target = fields.OneToOneField("models.RelationTarget", related_name="one_to_one_record")
    many_targets = fields.ManyToManyField("models.RelationTarget", related_name="many_records")
    id: int
