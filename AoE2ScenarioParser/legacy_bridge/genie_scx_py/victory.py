from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import BinaryIO, List, Optional, Tuple

from ._io import BinaryReader, BinaryWriter
from .types import VictoryConditionValue


@dataclass(slots=True)
class LegacyVictoryInfo:
    object_type: int = 0
    all_flag: bool = False
    player_id: int = 0
    dest_object_id: int = 0
    area: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    victory_type: int = 0
    amount: int = 0
    attribute: int = 0
    object_id: int = 0
    dest_object_id2: int = 0

    @staticmethod
    def read_from(reader: BinaryIO) -> "LegacyVictoryInfo":
        r = BinaryReader(reader)
        obj = LegacyVictoryInfo(
            object_type=r.read_i32(),
            all_flag=r.read_i32() != 0,
            player_id=r.read_i32(),
            dest_object_id=r.read_i32(),
            area=(r.read_f32(), r.read_f32(), r.read_f32(), r.read_f32()),
            victory_type=r.read_i32(),
            amount=r.read_i32(),
            attribute=r.read_i32(),
            object_id=r.read_i32(),
            dest_object_id2=r.read_i32(),
        )
        _object_ptr = r.read_u32()
        _dest_object_ptr = r.read_u32()
        return obj

    def write_to(self, writer: BinaryIO) -> None:
        w = BinaryWriter(writer)
        w.write_i32(self.object_type)
        w.write_i32(1 if self.all_flag else 0)
        w.write_i32(self.player_id)
        w.write_i32(self.dest_object_id)
        w.write_f32(self.area[0])
        w.write_f32(self.area[1])
        w.write_f32(self.area[2])
        w.write_f32(self.area[3])
        w.write_i32(self.victory_type)
        w.write_i32(self.amount)
        w.write_i32(self.attribute)
        w.write_i32(self.object_id)
        w.write_i32(self.dest_object_id2)
        w.write_u32(0)
        w.write_u32(0)


@dataclass(slots=True)
class VictoryEntry:
    command: VictoryConditionValue
    object_type: int
    player_id: int
    x0: float
    y0: float
    x1: float
    y1: float
    number: int
    count: int
    source_object: int
    target_object: int
    victory_group: int
    ally_flag: int
    state: int

    @staticmethod
    def read_from(reader: BinaryIO) -> "VictoryEntry":
        r = BinaryReader(reader)
        cmd = VictoryConditionValue.from_u8(r.read_u8())
        return VictoryEntry(
            command=cmd,
            object_type=r.read_i32(),
            player_id=r.read_i32(),
            x0=r.read_f32(),
            y0=r.read_f32(),
            x1=r.read_f32(),
            y1=r.read_f32(),
            number=r.read_i32(),
            count=r.read_i32(),
            source_object=r.read_i32(),
            target_object=r.read_i32(),
            victory_group=r.read_i8(),
            ally_flag=r.read_i8(),
            state=r.read_i8(),
        )

    def write_to(self, writer: BinaryIO) -> None:
        w = BinaryWriter(writer)
        w.write_u8(self.command.to_u8())
        w.write_i32(self.object_type)
        w.write_i32(self.player_id)
        w.write_f32(self.x0)
        w.write_f32(self.y0)
        w.write_f32(self.x1)
        w.write_f32(self.y1)
        w.write_i32(self.number)
        w.write_i32(self.count)
        w.write_i32(self.source_object)
        w.write_i32(self.target_object)
        w.write_i8(self.victory_group)
        w.write_i8(self.ally_flag)
        w.write_i8(self.state)


@dataclass(slots=True)
class VictoryPointEntry:
    command: int
    state: int
    attribute: int
    amount: int
    points: int
    current_points: int
    id: int
    group: int
    current_attribute_amount: float
    attribute1: int
    current_attribute_amount1: float

    @staticmethod
    def read_from(reader: BinaryIO, version: float) -> "VictoryPointEntry":
        r = BinaryReader(reader)
        command = r.read_i8()
        state = r.read_i8()
        attribute = r.read_i32()
        amount = r.read_i32()
        points = r.read_i32()
        current_points = r.read_i32()
        id_ = r.read_i8()
        group = r.read_i8()
        current_attribute_amount = r.read_f32()
        if version >= 2.0:
            attribute1 = r.read_i32()
            current_attribute_amount1 = r.read_f32()
        else:
            attribute1 = -1
            current_attribute_amount1 = 0.0
        return VictoryPointEntry(
            command=command,
            state=state,
            attribute=attribute,
            amount=amount,
            points=points,
            current_points=current_points,
            id=id_,
            group=group,
            current_attribute_amount=current_attribute_amount,
            attribute1=attribute1,
            current_attribute_amount1=current_attribute_amount1,
        )

    def write_to(self, writer: BinaryIO, version: float) -> None:
        w = BinaryWriter(writer)
        w.write_i8(self.command)
        w.write_i8(self.state)
        w.write_i32(self.attribute)
        w.write_i32(self.amount)
        w.write_i32(self.points)
        w.write_i32(self.current_points)
        w.write_i8(self.id)
        w.write_i8(self.group)
        w.write_f32(self.current_attribute_amount)
        if version >= 2.0:
            w.write_i32(self.attribute1)
            w.write_f32(self.current_attribute_amount1)


class VictoryState(IntEnum):
    NotAchieved = 0
    Failed = 1
    Achieved = 2
    Disabled = 3

    @staticmethod
    def try_from(n: int) -> "VictoryState":
        try:
            return VictoryState(int(n))
        except Exception as e:
            raise ValueError(f"invalid VictoryState {n!r}") from e


@dataclass(slots=True)
class VictoryConditions:
    version: float = 0.0
    victory: VictoryState = VictoryState.NotAchieved
    total_points: int = 0
    starting_points: int = 0
    starting_group: int = 0
    entries: List[VictoryEntry] = field(default_factory=list)
    point_entries: List[VictoryPointEntry] = field(default_factory=list)

    @staticmethod
    def read_from(reader: BinaryIO, has_version: bool) -> "VictoryConditions":
        r = BinaryReader(reader)
        version = r.read_f32() if has_version else 0.0
        num_conditions = r.read_i32()
        victory = VictoryState.try_from(r.read_u8())
        entries: List[VictoryEntry] = []
        for _ in range(num_conditions):
            entries.append(VictoryEntry.read_from(reader))

        total_points = 0
        point_entries: List[VictoryPointEntry] = []
        starting_points = 0
        starting_group = 0
        if version >= 1.0:
            total_points = r.read_i32()
            num_point_entries = r.read_i32()
            if version >= 2.0:
                starting_points = r.read_i32()
                starting_group = r.read_i32()
            for _ in range(num_point_entries):
                point_entries.append(VictoryPointEntry.read_from(reader, version))

        return VictoryConditions(
            version=version,
            victory=victory,
            total_points=total_points,
            starting_points=starting_points,
            starting_group=starting_group,
            entries=entries,
            point_entries=point_entries,
        )

    def write_to(self, writer: BinaryIO, version: Optional[float]) -> None:
        w = BinaryWriter(writer)
        if version is not None:
            w.write_f32(version)
        v = version if version is not None else float("-inf")
        w.write_i32(len(self.entries))
        w.write_u8(int(self.victory))
        for e in self.entries:
            e.write_to(writer)
        if v >= 1.0:
            w.write_i32(self.total_points)
            w.write_i32(len(self.point_entries))
            if v >= 2.0:
                w.write_i32(self.starting_points)
                w.write_i32(self.starting_group)
            for pe in self.point_entries:
                pe.write_to(writer, v)


@dataclass(slots=True)
class VictoryInfo:
    conquest: bool = False
    ruins: int = 0
    relics: int = 0
    discoveries: int = 0
    exploration: int = 0
    gold: int = 0

    @staticmethod
    def read_from(reader: BinaryIO) -> "VictoryInfo":
        r = BinaryReader(reader)
        return VictoryInfo(
            conquest=r.read_i32() != 0,
            ruins=r.read_i32(),
            relics=r.read_i32(),
            discoveries=r.read_i32(),
            exploration=r.read_i32(),
            gold=r.read_i32(),
        )

    def write_to(self, writer: BinaryIO) -> None:
        w = BinaryWriter(writer)
        w.write_i32(1 if self.conquest else 0)
        w.write_i32(self.ruins)
        w.write_i32(self.relics)
        w.write_i32(self.discoveries)
        w.write_i32(self.exploration)
        w.write_i32(self.gold)

