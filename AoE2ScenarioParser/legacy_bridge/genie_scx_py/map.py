from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO, Iterator, List, Optional

from ._io import BinaryReader, BinaryWriter
from ._support.read import read_opt_u16


@dataclass(slots=True)
class Tile:
    terrain: int = 0
    layered_terrain: Optional[int] = None
    elevation: int = 0
    zone: int = 0
    mask_type: Optional[int] = None

    @staticmethod
    def read_from(reader: BinaryIO, version: int) -> "Tile":
        r = BinaryReader(reader)
        tile = Tile(
            terrain=r.read_u8(),
            layered_terrain=None,
            elevation=r.read_i8(),
            zone=r.read_i8(),
            mask_type=None,
        )
        if version >= 1:
            tile.mask_type = read_opt_u16(reader)
            tile.layered_terrain = read_opt_u16(reader)
        return tile

    def write_to(self, writer: BinaryIO, version: int) -> None:
        w = BinaryWriter(writer)
        w.write_u8(self.terrain)
        w.write_i8(self.elevation)
        w.write_i8(self.zone)
        if version >= 1:
            w.write_u16(self.mask_type if self.mask_type is not None else 0xFFFF)
            w.write_u16(self.layered_terrain if self.layered_terrain is not None else 0xFFFF)


@dataclass(slots=True)
class Map:
    version: int
    width: int
    height: int
    render_waves: bool
    tiles: List[Tile] = field(default_factory=list)

    @staticmethod
    def new(width: int, height: int) -> "Map":
        return Map(
            version=0,
            width=width,
            height=height,
            render_waves=True,
            tiles=[Tile() for _ in range(width * height)],
        )

    def fill(self, terrain_type: int) -> None:
        for t in self.tiles:
            t.terrain = terrain_type

    @staticmethod
    def read_from(reader: BinaryIO) -> "Map":
        r = BinaryReader(reader)
        first = r.read_u32()
        if first == 0xDEADF00D:
            version = r.read_u32()
            if version < 2:
                render_waves = True
            else:
                render_waves = r.read_u8() == 0
            width = r.read_u32()
            height = r.read_u32()
            m = Map(
                version=version,
                width=width,
                height=height,
                render_waves=render_waves,
                tiles=[],
            )
        else:
            width = first
            height = r.read_u32()
            m = Map(version=0, width=width, height=height, render_waves=True, tiles=[])

        if m.width > 500 or m.height > 500:
            raise ValueError(f"Unexpected map size {m.width}x{m.height}, this is likely a genie-scx bug.")

        m.tiles = []
        need_tiles = m.width * m.height
        try:
            for _ in range(m.height):
                for _ in range(m.width):
                    m.tiles.append(Tile.read_from(reader, m.version))
        except EOFError as e:
            raise ValueError(
                f"Truncated scenario map data: declared {m.width}x{m.height} ({need_tiles} tiles) "
                f"but only {len(m.tiles)} tiles could be read before end of stream ({e}). "
                f"The file may be incomplete or corrupt."
            ) from e
        return m

    def write_to(self, writer: BinaryIO, version: int) -> None:
        w = BinaryWriter(writer)
        if version != 0:
            w.write_u32(0xDEADF00D)
            w.write_u32(version)
        if version >= 2:
            w.write_u8(1 if not self.render_waves else 0)
        w.write_u32(self.width)
        w.write_u32(self.height)
        assert len(self.tiles) == self.height * self.width
        for t in self.tiles:
            t.write_to(writer, version)

    def tile(self, x: int, y: int) -> Optional[Tile]:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return None
        return self.tiles[y * self.width + x]

    def rows(self) -> Iterator[List[Tile]]:
        for y in range(self.height):
            start = y * self.width
            yield self.tiles[start : start + self.width]

