from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO, List, Optional, Tuple

from ._io import BinaryReader, BinaryWriter


@dataclass(slots=True)
class RGBA8:
    r: int
    g: int
    b: int
    a: int


@dataclass(slots=True)
class BitmapInfo:
    size: int = 0
    width: int = 0
    height: int = 0
    planes: int = 0
    bit_count: int = 0
    compression: int = 0
    size_image: int = 0
    xpels_per_meter: int = 0
    ypels_per_meter: int = 0
    clr_used: int = 0
    clr_important: int = 0
    colors: List[RGBA8] = field(default_factory=list)

    @staticmethod
    def read_from(reader: BinaryIO) -> "BitmapInfo":
        r = BinaryReader(reader)
        info = BitmapInfo(
            size=r.read_u32(),
            width=r.read_i32(),
            height=r.read_i32(),
            planes=r.read_u16(),
            bit_count=r.read_u16(),
            compression=r.read_u32(),
            size_image=r.read_u32(),
            xpels_per_meter=r.read_i32(),
            ypels_per_meter=r.read_i32(),
            clr_used=r.read_u32(),
            clr_important=r.read_u32(),
        )
        for _ in range(256):
            info.colors.append(RGBA8(r=r.read_u8(), g=r.read_u8(), b=r.read_u8(), a=r.read_u8()))
        return info

    def write_to(self, writer: BinaryIO) -> None:
        w = BinaryWriter(writer)
        assert len(self.colors) == 256
        w.write_u32(self.size)
        w.write_i32(self.width)
        w.write_i32(self.height)
        w.write_u16(self.planes)
        w.write_u16(self.bit_count)
        w.write_u32(self.compression)
        w.write_u32(self.size_image)
        w.write_i32(self.xpels_per_meter)
        w.write_i32(self.ypels_per_meter)
        w.write_u32(self.clr_used)
        w.write_u32(self.clr_important)
        for c in self.colors:
            w.write_u8(c.r)
            w.write_u8(c.g)
            w.write_u8(c.b)
            w.write_u8(c.a)


@dataclass(slots=True)
class Bitmap:
    own_memory: int
    width: int
    height: int
    orientation: int
    info: BitmapInfo
    pixels: bytes

    @staticmethod
    def read_from(reader: BinaryIO) -> Optional["Bitmap"]:
        r = BinaryReader(reader)
        own_memory = r.read_u32()
        width = r.read_u32()
        height = r.read_u32()
        orientation = r.read_u16()
        if width > 0 and height > 0:
            info = BitmapInfo.read_from(reader)
            aligned_width = height * ((width + 3) & ~3)
            pixels = r.read_bytes(int(aligned_width))
            return Bitmap(
                own_memory=own_memory,
                width=width,
                height=height,
                orientation=orientation,
                info=info,
                pixels=pixels,
            )
        return None

    def write_to(self, writer: BinaryIO) -> None:
        w = BinaryWriter(writer)
        w.write_u32(self.own_memory)
        w.write_u32(self.width)
        w.write_u32(self.height)
        w.write_u16(self.orientation)
        self.info.write_to(writer)
        w.write_bytes(self.pixels)

    @staticmethod
    def write_empty(writer: BinaryIO) -> None:
        w = BinaryWriter(writer)
        w.write_u32(0)
        w.write_u32(0)
        w.write_u32(0)
        w.write_u16(0)

