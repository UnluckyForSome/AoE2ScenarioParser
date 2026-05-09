from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union


@dataclass(frozen=True, slots=True)
class UnitTypeID:
    """
    Rust: `pub struct UnitTypeID(u16);`

    This is intentionally a thin wrapper around an unsigned 16-bit integer.
    """

    value: int = 0

    def __post_init__(self) -> None:
        if not (0 <= self.value <= 0xFFFF):
            raise ValueError(f"UnitTypeID out of range for u16: {self.value!r}")

    def __int__(self) -> int:
        return self.value


@dataclass(frozen=True, slots=True)
class TechID:
    """Rust: `pub struct TechID(u16);`"""

    value: int = 0

    def __post_init__(self) -> None:
        if not (0 <= self.value <= 0xFFFF):
            raise ValueError(f"TechID out of range for u16: {self.value!r}")

    def __int__(self) -> int:
        return self.value


@dataclass(frozen=True, slots=True)
class SpriteID:
    """Rust: `pub struct SpriteID(u16);`"""

    value: int = 0

    def __post_init__(self) -> None:
        if not (0 <= self.value <= 0xFFFF):
            raise ValueError(f"SpriteID out of range for u16: {self.value!r}")

    def __int__(self) -> int:
        return self.value


@dataclass(frozen=True, slots=True)
class StringKeyNum:
    value: int

    def __post_init__(self) -> None:
        if not (0 <= self.value <= 0xFFFF_FFFF):
            raise ValueError(f"StringKey.Num out of range for u32: {self.value!r}")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class StringKeyName:
    value: str

    def __str__(self) -> str:
        return self.value


StringKey = Union[StringKeyNum, StringKeyName]


class TryFromStringKeyError(ValueError):
    """
    Rust: `pub struct TryFromStringKeyError;`
    Raised when attempting to convert a StringKey into an integer size but the
    key is named, or numeric but out of range for the requested type.
    """


def string_key_from(value: Any) -> StringKey:
    """
    Rust equivalents:
      - From<u32>, From<u16>
      - TryFrom<i32>, TryFrom<i16>
      - From<&str>, From<String>
    """

    if isinstance(value, (StringKeyNum, StringKeyName)):
        return value

    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"StringKey cannot be created from negative integer: {value!r}")
        return StringKeyNum(int(value))

    if isinstance(value, str):
        try:
            n = int(value, 10)
        except Exception:
            return StringKeyName(value)
        if n < 0:
            return StringKeyName(value)
        # Rust `s.parse()` chooses Num for any valid u32 string.
        if n <= 0xFFFF_FFFF:
            return StringKeyNum(n)
        return StringKeyName(value)

    raise TypeError(f"Unsupported type for StringKey: {type(value).__name__}")


def string_key_is_numeric(key: StringKey) -> bool:
    return isinstance(key, StringKeyNum)


def string_key_is_named(key: StringKey) -> bool:
    return isinstance(key, StringKeyName)


def string_key_try_into_u32(key: StringKey) -> int:
    if isinstance(key, StringKeyNum):
        return key.value
    raise TryFromStringKeyError()


def string_key_try_into_i32(key: StringKey) -> int:
    v = string_key_try_into_u32(key)
    if v <= 0x7FFF_FFFF:
        return int(v)
    raise TryFromStringKeyError()


def string_key_try_into_u16(key: StringKey) -> int:
    v = string_key_try_into_u32(key)
    if v <= 0xFFFF:
        return int(v)
    raise TryFromStringKeyError()


def string_key_try_into_i16(key: StringKey) -> int:
    v = string_key_try_into_u16(key)
    if v <= 0x7FFF:
        return int(v)
    raise TryFromStringKeyError()


def string_key_to_str(key: StringKey) -> str:
    return str(key)

