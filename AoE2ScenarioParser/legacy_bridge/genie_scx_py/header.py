from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO, List, Optional

from ._io import BinaryReader, BinaryWriter
from .types import DLCPackage, DataSet, SCXVersion
from ._support.strings import read_hd_style_str, read_u32_length_prefixed_str, write_opt_i32_str


@dataclass(slots=True)
class DLCOptions:
    version: int
    game_data_set: DataSet
    dependencies: List[DLCPackage] = field(default_factory=list)

    @staticmethod
    def default() -> "DLCOptions":
        return DLCOptions(
            version=1000,
            game_data_set=DataSet.BaseGame,
            dependencies=[DLCPackage.AgeOfKings, DLCPackage.AgeOfConquerors],
        )

    @staticmethod
    def read_from(reader: BinaryIO) -> "DLCOptions":
        r = BinaryReader(reader)
        version_or_data_set = r.read_i32()
        if version_or_data_set in (0, 1):
            game_data_set = DataSet.try_from(version_or_data_set)
        else:
            game_data_set = DataSet.try_from(r.read_i32())
        version = 0 if version_or_data_set == 1 else version_or_data_set
        num_dependencies = r.read_u32()
        deps: List[DLCPackage] = []
        for _ in range(num_dependencies):
            deps.append(DLCPackage.try_from(r.read_i32()))
        return DLCOptions(version=version, game_data_set=game_data_set, dependencies=deps)

    def write_to(self, writer: BinaryIO) -> None:
        w = BinaryWriter(writer)
        w.write_u32(1000)
        w.write_i32(self.game_data_set.to_i32())
        w.write_u32(len(self.dependencies))
        for d in self.dependencies:
            w.write_i32(d.to_i32())


@dataclass(slots=True)
class SCXHeader:
    version: int
    timestamp: int
    description: Optional[str]
    author_name: Optional[str]
    any_sp_victory: bool
    active_player_count: int
    dlc_options: Optional[DLCOptions]

    @staticmethod
    def read_from(reader: BinaryIO, format_version: SCXVersion) -> "SCXHeader":
        r = BinaryReader(reader)
        _header_size = r.read_u32()
        version = r.read_u32()
        timestamp = r.read_u32() if version >= 2 else 0
        if format_version == b"3.13":
            description = read_hd_style_str(reader)
        else:
            description = read_u32_length_prefixed_str(reader)
        any_sp_victory = r.read_u32() != 0
        active_player_count = r.read_u32()
        if version > 2 and format_version != b"3.13":
            dlc_options = DLCOptions.read_from(reader)
        else:
            dlc_options = None
        if version >= 5:
            author_name = read_u32_length_prefixed_str(reader)
            _num_triggers = r.read_u32()
        else:
            author_name = None
        return SCXHeader(
            version=version,
            timestamp=timestamp,
            description=description,
            author_name=author_name,
            any_sp_victory=any_sp_victory,
            active_player_count=active_player_count,
            dlc_options=dlc_options,
        )

    def write_to(self, writer: BinaryIO, format_version: SCXVersion, version: int) -> None:
        # Rust writes to intermediate vec and then prefixes with length.
        import io

        buf = io.BytesIO()
        w = BinaryWriter(buf)
        w.write_u32(version)
        if version >= 2:
            w.write_u32(self.timestamp)

        desc_bytes = bytearray()
        if self.description is not None:
            # Rust ``SCXHeader::write_to``: ``description.as_bytes()`` + NUL (UTF-8); read uses CP1252 ``read_u32_length_prefixed_str``.
            desc_bytes.extend(self.description.encode("utf-8", errors="replace"))
        desc_bytes.append(0)

        if format_version == b"3.13":
            assert len(desc_bytes) <= 0xFFFF
            w.write_u16(len(desc_bytes))
        else:
            assert len(desc_bytes) <= 0xFFFF_FFFF
            w.write_u32(len(desc_bytes))
        w.write_bytes(bytes(desc_bytes))

        w.write_u32(1 if self.any_sp_victory else 0)
        w.write_u32(self.active_player_count)

        if version > 2 and format_version != b"3.13":
            dlc = self.dlc_options if self.dlc_options is not None else DLCOptions.default()
            dlc.write_to(buf)

        if version >= 5:
            write_opt_i32_str(buf, self.author_name)
            w.write_u32(0)

        payload = buf.getvalue()
        out = BinaryWriter(writer)
        out.write_u32(len(payload))
        out.write_bytes(payload)

