from __future__ import annotations

"""
Length-prefixed scenario strings (``str16`` / ``str32`` / ``read_str``): **Windows-1252**, matching
``genie-support`` / ``genie-scx`` (``encoding_rs::WINDOWS_1252``).

Some fixed-size or raw blobs in the Rust crate still use ``str::as_bytes()`` (UTF-8) — see comments
in ``format.py``, ``header.py``, and ``ai.py`` where UTF-8 is intentional for parity with Rust writes.
"""

import struct
from dataclasses import dataclass
from typing import BinaryIO, Optional

# Same codec label Python uses for Windows code page 1252 (AoE scenario strings).
CP1252 = "cp1252"


class DecodeStringError(ValueError):
    """Rust: ``DecodeStringError`` (invalid structural content, e.g. HD-style opener)."""


class EncodeStringError(ValueError):
    """Rust: ``EncodeStringError`` — character not representable in WINDOWS-1252."""


class ReadStringError(Exception):
    """Rust: ``ReadStringError`` enum (DecodeStringError | IoError)."""


class WriteStringError(Exception):
    """Rust: ``WriteStringError`` enum (EncodeStringError | IoError)."""


def _read_exact(reader: BinaryIO, n: int) -> bytes:
    b = reader.read(n)
    if b is None or len(b) != n:
        raise EOFError(f"Unexpected EOF reading {n} bytes")
    return b


def _decode_cp1252(raw: bytes) -> str:
    """
    Rust ``decode_str``: ``WINDOWS_1252.decode(bytes)`` — always succeeds for arbitrary bytes
    (8-bit mapping). Python's ``cp1252`` codec likewise maps every byte to a Unicode scalar.
    """

    if not raw:
        return ""
    return raw.decode(CP1252)


def read_str(reader: BinaryIO, length: int) -> Optional[str]:
    """
    Rust: ``ReadStringsExt::read_str(length)``
      - reads ``length`` bytes
      - truncates at first NUL
      - returns None if bytes empty after truncation
    """

    if length <= 0:
        return None
    raw = bytearray(_read_exact(reader, length))
    try:
        end = raw.index(0)
        raw = raw[:end]
    except ValueError:
        pass
    if len(raw) == 0:
        return None
    return _decode_cp1252(bytes(raw))


def read_u16_length_prefixed_str(reader: BinaryIO) -> Optional[str]:
    """
    Rust: ``0xFFFF`` => None; else ``read_str(len)``
    """

    (length,) = struct.unpack("<H", _read_exact(reader, 2))
    if length == 0xFFFF:
        return None
    return read_str(reader, int(length))


def read_u32_length_prefixed_str(reader: BinaryIO) -> Optional[str]:
    (length,) = struct.unpack("<I", _read_exact(reader, 4))
    if length == 0xFFFF_FFFF:
        return None
    return read_str(reader, int(length))


def read_hd_style_str(reader: BinaryIO) -> Optional[str]:
    """
    Rust: ``ReadStringsExt::read_hd_style_str``
      - reads u16 'signature' and expects ``0x0A60`` else ``DecodeStringError``
      - reads u16 length
      - reads length bytes and decodes (no NUL strip on this path in Rust)
    """

    (open_sig,) = struct.unpack("<H", _read_exact(reader, 2))
    if open_sig != 0x0A60:
        raise DecodeStringError("HD style string missing 0x0A60 opener")
    (length,) = struct.unpack("<H", _read_exact(reader, 2))
    raw = _read_exact(reader, int(length))
    return _decode_cp1252(raw)


def write_str(writer: BinaryIO, string: str) -> None:
    """
    Rust: ``write_str`` — WINDOWS-1252 encode (strict), ``i16`` length = byte len + 1 (incl. NUL),
    bytes, NUL.
    """

    try:
        encoded = string.encode(CP1252, errors="strict")
    except UnicodeEncodeError as e:
        raise EncodeStringError("could not encode string as WINDOWS-1252") from e
    if len(encoded) >= 0x7FFF:
        raise EncodeStringError("string too long for i16 length prefix")
    writer.write(struct.pack("<h", len(encoded) + 1))
    writer.write(encoded)
    writer.write(b"\x00")


def write_i32_str(writer: BinaryIO, string: str) -> None:
    try:
        encoded = string.encode(CP1252, errors="strict")
    except UnicodeEncodeError as e:
        raise EncodeStringError("could not encode string as WINDOWS-1252") from e
    if len(encoded) >= 0x7FFF_FFFF:
        raise EncodeStringError("string too long for i32 length prefix")
    writer.write(struct.pack("<i", len(encoded) + 1))
    writer.write(encoded)
    writer.write(b"\x00")


def write_opt_str(writer: BinaryIO, value: Optional[str]) -> None:
    if value is None:
        writer.write(struct.pack("<h", 0))
        return
    write_str(writer, value)


def write_opt_i32_str(writer: BinaryIO, value: Optional[str]) -> None:
    if value is None:
        writer.write(struct.pack("<i", 0))
        return
    write_i32_str(writer, value)
