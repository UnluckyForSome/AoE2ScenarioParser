from __future__ import annotations

import io
import struct
from typing import BinaryIO, Optional, TypeVar, Callable


class InvalidDataError(ValueError):
    """Rust analog: io::ErrorKind::InvalidData for failed TryFrom conversions."""


T = TypeVar("T")


def _read_exact(reader: BinaryIO, n: int) -> bytes:
    b = reader.read(n)
    if b is None or len(b) != n:
        raise EOFError(f"Unexpected EOF reading {n} bytes")
    return b


def read_u16_le(reader: BinaryIO) -> int:
    return struct.unpack("<H", _read_exact(reader, 2))[0]


def read_u32_le(reader: BinaryIO) -> int:
    return struct.unpack("<I", _read_exact(reader, 4))[0]


def read_opt_u16(reader: BinaryIO, convert: Callable[[int], T] | None = None) -> Optional[T]:
    """
    Rust: read_opt_u16<T, R>(input: &mut R) -> io::Result<Option<T>>
    Sentinel: 0xFFFF => None
    """

    v = read_u16_le(reader)
    if v == 0xFFFF:
        return None
    if convert is None:
        return v  # type: ignore[return-value]
    try:
        return convert(v)
    except Exception as e:
        raise InvalidDataError(str(e)) from e


def read_opt_u32(reader: BinaryIO, convert: Callable[[int], T] | None = None) -> Optional[T]:
    """
    Rust: read_opt_u32<T, R>(input: &mut R) -> io::Result<Option<T>>
    Sentinels:
      - 0xFFFF_FFFF => None
      - 0xFFFF_FFFE => None (HD uses -2 in some places)
    """

    v = read_u32_le(reader)
    if v in (0xFFFF_FFFF, 0xFFFF_FFFE):
        return None
    if convert is None:
        return v  # type: ignore[return-value]
    try:
        return convert(v)
    except Exception as e:
        raise InvalidDataError(str(e)) from e


def skip(reader: BinaryIO, dist: int) -> None:
    """
    Rust: io::copy(&mut self.by_ref().take(dist), &mut io::sink())
    """

    if dist <= 0:
        return
    # Fast path: seek if possible.
    if hasattr(reader, "seek") and hasattr(reader, "tell"):
        try:
            reader.seek(dist, io.SEEK_CUR)
            return
        except Exception:
            pass
    # Fallback: read and discard.
    remaining = dist
    while remaining:
        chunk = reader.read(min(remaining, 1024 * 1024))
        if not chunk:
            raise EOFError(f"Unexpected EOF skipping {dist} bytes")
        remaining -= len(chunk)

