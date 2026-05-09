from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO, Optional


class DecodeStringError(ValueError):
    """Rust: DecodeStringError (lossy decode still can fail on structural issues)."""


class EncodeStringError(ValueError):
    """Rust: EncodeStringError."""


class ReadStringError(Exception):
    """Rust: ReadStringError enum (DecodeStringError | IoError)."""


class WriteStringError(Exception):
    """Rust: WriteStringError enum (EncodeStringError | IoError)."""


def _read_exact(reader: BinaryIO, n: int) -> bytes:
    b = reader.read(n)
    if b is None or len(b) != n:
        raise EOFError(f"Unexpected EOF reading {n} bytes")
    return b


def _decode_cp1252_lossy(raw: bytes) -> str:
    if not raw:
        return ""
    # Matches rust fix: WINDOWS_1252.decode(bytes) and ignore failure flag.
    return raw.decode("cp1252", errors="replace")


def read_str(reader: BinaryIO, length: int) -> Optional[str]:
    """
    Rust: ReadStringsExt::read_str(length)
      - reads `length` bytes
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
    return _decode_cp1252_lossy(bytes(raw))


def read_u16_length_prefixed_str(reader: BinaryIO) -> Optional[str]:
    """
    Rust: 0xFFFF => None; else read_str(len)
    NOTE: Rust uses u16 for prefix but compares against 0xFFFF.
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
    Rust: ReadStringsExt::read_hd_style_str
      - reads u16 'signature' and expects 0x0A60 else DecodeStringError
      - reads u16 length
      - reads length bytes and decodes (no NUL strip in Rust path)
    """

    (open_sig,) = struct.unpack("<H", _read_exact(reader, 2))
    if open_sig != 0x0A60:
        raise DecodeStringError("HD style string missing 0x0A60 opener")
    (length,) = struct.unpack("<H", _read_exact(reader, 2))
    raw = _read_exact(reader, int(length))
    return _decode_cp1252_lossy(raw)


def write_str(writer: BinaryIO, string: str) -> None:
    """
    Rust: write_str:
      - encode cp1252 (fails if cannot encode)
      - write i16 length (bytes_len + 1) little-endian
      - write bytes
      - write NUL
    """

    try:
        encoded = string.encode("cp1252", errors="strict")
    except Exception as e:
        raise WriteStringError(EncodeStringError()) from e
    if len(encoded) >= 0x7FFF:
        raise WriteStringError("string too long for i16 length prefix")
    writer.write(struct.pack("<h", len(encoded) + 1))
    writer.write(encoded)
    writer.write(b"\x00")


def write_i32_str(writer: BinaryIO, string: str) -> None:
    try:
        encoded = string.encode("cp1252", errors="strict")
    except Exception as e:
        raise WriteStringError(EncodeStringError()) from e
    if len(encoded) >= 0x7FFF_FFFF:
        raise WriteStringError("string too long for i32 length prefix")
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

