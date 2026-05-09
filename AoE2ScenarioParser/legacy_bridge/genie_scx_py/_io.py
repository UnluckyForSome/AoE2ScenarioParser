from __future__ import annotations

import io
import struct
import zlib
from dataclasses import dataclass
from typing import BinaryIO, Optional

from ._support.strings import (
    DecodeStringError,
    EncodeStringError,
    read_hd_style_str,
    read_str,
    read_u16_length_prefixed_str,
    read_u32_length_prefixed_str,
    write_i32_str,
    write_opt_i32_str,
    write_opt_str,
    write_str,
)


def _read_exact(reader: BinaryIO, n: int) -> bytes:
    b = reader.read(n)
    if b is None or len(b) != n:
        raise EOFError(f"Unexpected EOF reading {n} bytes")
    return b


@dataclass(slots=True)
class BinaryReader:
    r: BinaryIO

    def read_bool_u32(self) -> bool:
        return self.read_u32() != 0

    def read_u8(self) -> int:
        return struct.unpack("<B", _read_exact(self.r, 1))[0]

    def read_i8(self) -> int:
        return struct.unpack("<b", _read_exact(self.r, 1))[0]

    def read_u16(self) -> int:
        return struct.unpack("<H", _read_exact(self.r, 2))[0]

    def read_i16(self) -> int:
        return struct.unpack("<h", _read_exact(self.r, 2))[0]

    def read_u32(self) -> int:
        return struct.unpack("<I", _read_exact(self.r, 4))[0]

    def read_i32(self) -> int:
        return struct.unpack("<i", _read_exact(self.r, 4))[0]

    def read_u64(self) -> int:
        return struct.unpack("<Q", _read_exact(self.r, 8))[0]

    def read_f64(self) -> float:
        return struct.unpack("<d", _read_exact(self.r, 8))[0]

    def read_f32(self) -> float:
        return struct.unpack("<f", _read_exact(self.r, 4))[0]

    def read_bytes(self, n: int) -> bytes:
        return _read_exact(self.r, n)

    # String helpers (ported from genie-support::strings::ReadStringsExt)
    def read_str(self, length: int) -> Optional[str]:
        return read_str(self.r, length)

    def read_u16_length_prefixed_str(self) -> Optional[str]:
        return read_u16_length_prefixed_str(self.r)

    def read_u32_length_prefixed_str(self) -> Optional[str]:
        return read_u32_length_prefixed_str(self.r)

    def read_hd_style_str(self) -> Optional[str]:
        return read_hd_style_str(self.r)

    def skip(self, dist: int) -> None:
        if dist <= 0:
            return
        if hasattr(self.r, "seek"):
            try:
                self.r.seek(dist, io.SEEK_CUR)
                return
            except Exception:
                pass
        remaining = dist
        while remaining:
            chunk = self.r.read(min(remaining, 1024 * 1024))
            if not chunk:
                raise EOFError(f"Unexpected EOF skipping {dist} bytes")
            remaining -= len(chunk)


@dataclass(slots=True)
class BinaryWriter:
    w: BinaryIO

    def write_bool_u32(self, v: bool) -> None:
        self.write_u32(1 if v else 0)

    def write_u8(self, v: int) -> None:
        self.w.write(struct.pack("<B", v))

    def write_i8(self, v: int) -> None:
        self.w.write(struct.pack("<b", v))

    def write_u16(self, v: int) -> None:
        self.w.write(struct.pack("<H", v))

    def write_i16(self, v: int) -> None:
        self.w.write(struct.pack("<h", v))

    def write_u32(self, v: int) -> None:
        self.w.write(struct.pack("<I", v))

    def write_i32(self, v: int) -> None:
        self.w.write(struct.pack("<i", v))

    def write_u64(self, v: int) -> None:
        self.w.write(struct.pack("<Q", v))

    def write_f64(self, v: float) -> None:
        self.w.write(struct.pack("<d", float(v)))

    def write_f32(self, v: float) -> None:
        # Force f32 rounding.
        self.w.write(struct.pack("<f", float(v)))

    def write_bytes(self, b: bytes) -> None:
        self.w.write(b)

    # String helpers
    def write_str(self, s: str) -> None:
        write_str(self.w, s)

    def write_i32_str(self, s: str) -> None:
        write_i32_str(self.w, s)

    def write_opt_str(self, s: Optional[str]) -> None:
        write_opt_str(self.w, s)

    def write_opt_i32_str(self, s: Optional[str]) -> None:
        write_opt_i32_str(self.w, s)


def deflate_raw(data: bytes, level: int = 6) -> bytes:
    """
    Rust uses flate2 DeflateEncoder/Decoder (raw DEFLATE, no zlib header).
    Python equivalent is zlib with wbits=-15.
    """

    comp = zlib.compressobj(level=level, wbits=-15)
    out = comp.compress(data) + comp.flush()
    return out


def inflate_raw(data: bytes) -> bytes:
    decomp = zlib.decompressobj(wbits=-15)
    out = decomp.decompress(data) + decomp.flush()
    return out

