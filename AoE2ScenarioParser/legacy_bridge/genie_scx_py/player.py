from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, List, Optional, Tuple

from ._io import BinaryReader, BinaryWriter
from ._support.strings import read_u16_length_prefixed_str, write_opt_str
from .victory import VictoryConditions


@dataclass(slots=True)
class PlayerBaseProperties:
    posture: int = 0
    player_type: int = 0
    civilization: int = 0
    active: int = 0


@dataclass(slots=True)
class PlayerFiles:
    build_list: Optional[str] = None
    city_plan: Optional[str] = None
    ai_rules: Optional[str] = None


@dataclass(slots=True)
class PlayerStartResources:
    gold: int
    wood: int
    food: int
    stone: int
    ore: int
    goods: int
    player_color: Optional[int]

    @staticmethod
    def default() -> "PlayerStartResources":
        return PlayerStartResources(
            gold=100,
            wood=200,
            food=200,
            stone=200,
            ore=100,
            goods=0,
            player_color=None,
        )

    @staticmethod
    def read_from(reader: BinaryIO, version: float) -> "PlayerStartResources":
        r = BinaryReader(reader)
        gold = r.read_i32()
        wood = r.read_i32()
        food = r.read_i32()
        stone = r.read_i32()
        ore = r.read_i32() if version >= 1.17 else 100
        goods = r.read_i32() if version >= 1.17 else 0
        player_color = r.read_i32() if version >= 1.24 else None
        return PlayerStartResources(
            gold=gold,
            wood=wood,
            food=food,
            stone=stone,
            ore=ore,
            goods=goods,
            player_color=player_color,
        )

    def write_to(self, writer: BinaryIO, version: float) -> None:
        w = BinaryWriter(writer)
        w.write_i32(self.gold)
        w.write_i32(self.wood)
        w.write_i32(self.food)
        w.write_i32(self.stone)
        if version >= 1.17:
            w.write_i32(self.ore)
            w.write_i32(self.goods)
        if version >= 1.24:
            w.write_i32(self.player_color if self.player_color is not None else 0)


@dataclass(slots=True)
class ScenarioPlayerData:
    name: Optional[str]
    view: Tuple[float, float]
    location: Tuple[int, int]
    allied_victory: bool
    relations: List[int]
    unit_diplomacy: List[int]
    color: Optional[int]
    victory: VictoryConditions

    @staticmethod
    def read_from(reader: BinaryIO, version: float) -> "ScenarioPlayerData":
        r = BinaryReader(reader)
        name = read_u16_length_prefixed_str(reader)
        view = (r.read_f32(), r.read_f32())
        location = (r.read_i16(), r.read_i16())
        allied_victory = (r.read_u8() != 0) if version > 1.0 else False
        diplo_count = r.read_i16()
        relations: List[int] = []
        for _ in range(diplo_count):
            relations.append(r.read_i8())
        if version >= 1.08:
            unit_diplomacy = [r.read_i32() for _ in range(9)]
        else:
            unit_diplomacy = [0] * 9
        color = r.read_i32() if version >= 1.13 else None
        victory = VictoryConditions.read_from(reader, has_version=(version >= 1.09))
        return ScenarioPlayerData(
            name=name,
            view=view,
            location=location,
            allied_victory=allied_victory,
            relations=relations,
            unit_diplomacy=unit_diplomacy,
            color=color,
            victory=victory,
        )

    def write_to(self, writer: BinaryIO, version: float, victory_version: float) -> None:
        w = BinaryWriter(writer)
        write_opt_str(writer, self.name)
        w.write_f32(self.view[0])
        w.write_f32(self.view[1])
        w.write_i16(self.location[0])
        w.write_i16(self.location[1])
        if version > 1.0:
            w.write_u8(1 if self.allied_victory else 0)
        w.write_i16(len(self.relations))
        for rel in self.relations:
            w.write_i8(rel)
        if version >= 1.08:
            for v in self.unit_diplomacy:
                w.write_i32(v)
        if version >= 1.13:
            w.write_i32(self.color if self.color is not None else -1)
        self.victory.write_to(writer, victory_version if version >= 1.09 else None)


@dataclass(slots=True)
class WorldPlayerData:
    food: float
    wood: float
    gold: float
    stone: float
    ore: float
    goods: float
    population: float

    @staticmethod
    def default() -> "WorldPlayerData":
        return WorldPlayerData(
            food=200.0,
            wood=200.0,
            gold=100.0,
            stone=200.0,
            ore=100.0,
            goods=0.0,
            population=75.0,
        )

    @staticmethod
    def read_from(reader: BinaryIO, version: float) -> "WorldPlayerData":
        r = BinaryReader(reader)
        food = r.read_f32() if version > 1.06 else 200.0
        wood = r.read_f32() if version > 1.06 else 200.0
        gold = r.read_f32() if version > 1.06 else 50.0
        stone = r.read_f32() if version > 1.06 else 100.0
        ore = r.read_f32() if version > 1.12 else 100.0
        goods = r.read_f32() if version > 1.12 else 0.0
        population = r.read_f32() if version >= 1.14 else 75.0
        return WorldPlayerData(
            food=food,
            wood=wood,
            gold=gold,
            stone=stone,
            ore=ore,
            goods=goods,
            population=population,
        )

    def write_to(self, writer: BinaryIO, version: float) -> None:
        w = BinaryWriter(writer)
        if version > 1.06:
            w.write_f32(self.food)
            w.write_f32(self.wood)
            w.write_f32(self.gold)
            w.write_f32(self.stone)
        if version > 1.12:
            w.write_f32(self.ore)
        if version > 1.12:
            w.write_f32(self.goods)
        if version >= 1.14:
            w.write_f32(self.population)

