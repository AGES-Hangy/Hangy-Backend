from enum import Enum

from sqlalchemy import Enum as SQLEnum


def enum_column(enum_class: type[Enum]) -> SQLEnum:
    """Persist the enum *values* instead of their member names."""
    return SQLEnum(
        enum_class,
        values_callable=lambda enum: [member.value for member in enum],
    )
