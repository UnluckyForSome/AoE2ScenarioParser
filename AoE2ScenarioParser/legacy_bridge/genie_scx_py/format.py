from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field, replace
from typing import BinaryIO, List, Optional, Tuple

from ._io import BinaryReader, BinaryWriter, deflate_raw, inflate_raw
from ._support.macros import f32_eq
from ._support.read import read_opt_u32
from ._support.strings import (
    read_str,
    read_u16_length_prefixed_str,
    write_opt_str,
    write_str,
)
from ._support.ids import StringKey, StringKeyNum, string_key_try_into_u32
from .ai import AIInfo
from .bitmap import Bitmap
from .header import SCXHeader
from .map import Map
from .player import (
    PlayerBaseProperties,
    PlayerFiles,
    PlayerStartResources,
    ScenarioPlayerData,
    WorldPlayerData,
)
from .triggers import TriggerSystem
from .types import (
    CannotDisableBuildingsError,
    CannotDisableTechsError,
    CannotDisableUnitsError,
    DefinitiveEditionScenarioError,
    DiplomaticStance,
    SCXVersion,
    StartingAge,
    TooManyDisabledBuildingsError,
    TooManyDisabledTechsError,
    UnsupportedFormatVersionError,
    VersionBundle,
    is_ascii_scx_version_prefix,
    is_definitive_edition_container_format,
    is_definitive_edition_scenario_data_version,
)
from .victory import LegacyVictoryInfo, VictoryInfo
from ._support.ids import UnitTypeID


@dataclass(slots=True)
class ScenarioObject:
    position: Tuple[float, float, float]
    id: int
    object_type: UnitTypeID
    state: int
    angle: float
    frame: int
    garrisoned_in: Optional[int]

    @staticmethod
    def read_from(reader: BinaryIO, version: SCXVersion) -> "ScenarioObject":
        r = BinaryReader(reader)
        position = (r.read_f32(), r.read_f32(), r.read_f32())
        id_ = r.read_i32()
        object_type = UnitTypeID(r.read_u16())
        state = r.read_u8()
        angle = r.read_f32()
        frame = -1 if version < SCXVersion(b"1.15") else r.read_i16()
        if version < SCXVersion(b"1.13"):
            garrisoned_in = None
        else:
            gid = r.read_i32()
            if gid == -1:
                garrisoned_in = None
            else:
                if gid == 0 and version > SCXVersion(b"1.12"):
                    garrisoned_in = None
                else:
                    garrisoned_in = gid
        return ScenarioObject(
            position=position,
            id=id_,
            object_type=object_type,
            state=state,
            angle=angle,
            frame=frame,
            garrisoned_in=garrisoned_in,
        )

    def write_to(self, writer: BinaryIO, version: SCXVersion) -> None:
        w = BinaryWriter(writer)
        w.write_f32(self.position[0])
        w.write_f32(self.position[1])
        w.write_f32(self.position[2])
        w.write_i32(self.id)
        w.write_u16(int(self.object_type))
        w.write_u8(self.state)
        w.write_f32(self.angle)
        if version > SCXVersion(b"1.14"):
            w.write_i16(self.frame)
        if version > SCXVersion(b"1.12"):
            w.write_i32(self.garrisoned_in if self.garrisoned_in is not None else -1)


def _read_opt_string_key(reader: BinaryIO) -> Optional[StringKey]:
    v = read_opt_u32(reader)
    if v is None:
        return None
    return StringKeyNum(int(v))


def _write_opt_string_key(writer: BinaryIO, key: Optional[StringKey]) -> None:
    w = BinaryWriter(writer)
    if key is None:
        w.write_u32(0xFFFF_FFFF)
    else:
        w.write_u32(string_key_try_into_u32(key))


@dataclass(slots=True)
class RGEScen:
    version: float
    player_names: List[Optional[str]] = field(default_factory=lambda: [None] * 16)
    player_string_table: List[Optional[StringKey]] = field(default_factory=lambda: [None] * 16)
    player_base_properties: List[PlayerBaseProperties] = field(default_factory=lambda: [PlayerBaseProperties() for _ in range(16)])
    victory_conquest: bool = True
    name: str = ""
    description_string_table: Optional[StringKey] = None
    hints_string_table: Optional[StringKey] = None
    win_message_string_table: Optional[StringKey] = None
    loss_message_string_table: Optional[StringKey] = None
    history_string_table: Optional[StringKey] = None
    scout_string_table: Optional[StringKey] = None
    description: Optional[str] = None
    hints: Optional[str] = None
    win_message: Optional[str] = None
    loss_message: Optional[str] = None
    history: Optional[str] = None
    scout: Optional[str] = None
    pregame_cinematic: Optional[str] = None
    victory_cinematic: Optional[str] = None
    loss_cinematic: Optional[str] = None
    mission_bmp: Optional[str] = None
    player_build_lists: List[Optional[str]] = field(default_factory=lambda: [None] * 16)
    player_city_plans: List[Optional[str]] = field(default_factory=lambda: [None] * 16)
    player_ai_rules: List[Optional[str]] = field(default_factory=lambda: [None] * 16)
    player_files: List[PlayerFiles] = field(default_factory=lambda: [PlayerFiles() for _ in range(16)])
    ai_rules_types: List[int] = field(default_factory=lambda: [0] * 16)

    @staticmethod
    def read_from(reader: BinaryIO) -> "RGEScen":
        r = BinaryReader(reader)
        version = r.read_f32()
        player_names: List[Optional[str]] = [None] * 16
        if version > 1.13:
            for i in range(16):
                player_names[i] = read_str(reader, 256)
        player_string_table: List[Optional[StringKey]] = [None] * 16
        if version > 1.16:
            for i in range(16):
                player_string_table[i] = _read_opt_string_key(reader)
        player_base_properties = [PlayerBaseProperties() for _ in range(16)]
        if version > 1.13:
            for props in player_base_properties:
                props.active = r.read_i32()
                props.player_type = r.read_i32()
                props.civilization = r.read_i32()
                props.posture = r.read_i32()
        victory_conquest = (r.read_u8() != 0) if version >= 1.07 else True

        # RGE_Timeline (asserted zero in rust)
        _timeline_count = r.read_i16()
        _timeline_available = r.read_i16()
        _old_time = r.read_f32()
        if _timeline_count != 0:
            raise ValueError("Unexpected RGE_Timeline")

        name = read_u16_length_prefixed_str(reader) or ""

        if version >= 1.16:
            description_string_table = _read_opt_string_key(reader)
            hints_string_table = _read_opt_string_key(reader)
            win_message_string_table = _read_opt_string_key(reader)
            loss_message_string_table = _read_opt_string_key(reader)
            history_string_table = _read_opt_string_key(reader)
        else:
            description_string_table = None
            hints_string_table = None
            win_message_string_table = None
            loss_message_string_table = None
            history_string_table = None

        scout_string_table = _read_opt_string_key(reader) if version >= 1.22 else None
        description = read_u16_length_prefixed_str(reader)
        if version >= 1.11:
            hints = read_u16_length_prefixed_str(reader)
            win_message = read_u16_length_prefixed_str(reader)
            loss_message = read_u16_length_prefixed_str(reader)
            history = read_u16_length_prefixed_str(reader)
        else:
            hints = win_message = loss_message = history = None
        scout = read_u16_length_prefixed_str(reader) if version >= 1.22 else None

        pregame_cinematic = read_u16_length_prefixed_str(reader)
        victory_cinematic = read_u16_length_prefixed_str(reader)
        loss_cinematic = read_u16_length_prefixed_str(reader)
        mission_bmp = read_u16_length_prefixed_str(reader) if version >= 1.09 else None
        _mission_picture = Bitmap.read_from(reader) if version >= 1.10 else None

        player_build_lists = [read_u16_length_prefixed_str(reader) for _ in range(16)]
        player_city_plans = [read_u16_length_prefixed_str(reader) for _ in range(16)]
        player_ai_rules = [None] * 16
        if version >= 1.08:
            player_ai_rules = [read_u16_length_prefixed_str(reader) for _ in range(16)]

        player_files = [PlayerFiles() for _ in range(16)]
        for files in player_files:
            build_list_length = r.read_i32()
            city_plan_length = r.read_i32()
            ai_rules_length = r.read_i32() if version >= 1.08 else 0
            files.build_list = read_str(reader, build_list_length) or None
            files.city_plan = read_str(reader, city_plan_length) or None
            files.ai_rules = read_str(reader, ai_rules_length) or None

        ai_rules_types = [0] * 16
        if version >= 1.20:
            ai_rules_types = [r.read_i8() for _ in range(16)]
        if version >= 1.02:
            sep = r.read_i32()
            if sep != -99:
                raise ValueError("Bad separator")

        return RGEScen(
            version=version,
            player_names=player_names,
            player_string_table=player_string_table,
            player_base_properties=player_base_properties,
            victory_conquest=victory_conquest,
            name=name,
            description_string_table=description_string_table,
            hints_string_table=hints_string_table,
            win_message_string_table=win_message_string_table,
            loss_message_string_table=loss_message_string_table,
            history_string_table=history_string_table,
            scout_string_table=scout_string_table,
            description=description,
            hints=hints,
            win_message=win_message,
            loss_message=loss_message,
            history=history,
            scout=scout,
            pregame_cinematic=pregame_cinematic,
            victory_cinematic=victory_cinematic,
            loss_cinematic=loss_cinematic,
            mission_bmp=mission_bmp,
            player_build_lists=player_build_lists,
            player_city_plans=player_city_plans,
            player_ai_rules=player_ai_rules,
            player_files=player_files,
            ai_rules_types=ai_rules_types,
        )

    def write_to(self, writer: BinaryIO, version: float) -> None:
        w = BinaryWriter(writer)
        w.write_f32(version)
        if version > 1.13:
            for name in self.player_names:
                padded = bytearray(256)
                if name is not None:
                    # Rust ``RGEScen::write_to``: UTF-8 ``str::as_bytes()`` into 256-byte slots (not CP1252).
                    nb = name.encode("utf-8", errors="replace")
                    padded[: len(nb)] = nb[:256]
                w.write_bytes(bytes(padded))
        if version > 1.16:
            for key in self.player_string_table:
                _write_opt_string_key(writer, key)
        if version > 1.13:
            for props in self.player_base_properties:
                w.write_i32(props.active)
                w.write_i32(props.player_type)
                w.write_i32(props.civilization)
                w.write_i32(props.posture)
        if version >= 1.07:
            w.write_u8(1 if self.victory_conquest else 0)
        w.write_i16(0)
        w.write_i16(0)
        w.write_f32(-1.0)
        write_str(writer, self.name)
        if version >= 1.16:
            _write_opt_string_key(writer, self.description_string_table)
            _write_opt_string_key(writer, self.hints_string_table)
            _write_opt_string_key(writer, self.win_message_string_table)
            _write_opt_string_key(writer, self.loss_message_string_table)
            _write_opt_string_key(writer, self.history_string_table)
        if version >= 1.22:
            _write_opt_string_key(writer, self.scout_string_table)
        write_opt_str(writer, self.description)
        if version >= 1.11:
            write_opt_str(writer, self.hints)
            write_opt_str(writer, self.win_message)
            write_opt_str(writer, self.loss_message)
            write_opt_str(writer, self.history)
        if version >= 1.22:
            write_opt_str(writer, self.scout)
        write_opt_str(writer, self.pregame_cinematic)
        write_opt_str(writer, self.victory_cinematic)
        write_opt_str(writer, self.loss_cinematic)
        if version >= 1.09:
            write_opt_str(writer, None)
        if version >= 1.10:
            # empty bitmap placeholder
            w.write_u32(0)
            w.write_u32(0)
            w.write_u32(0)
            w.write_u16(1)
        for bl in self.player_build_lists:
            write_opt_str(writer, bl)
        for cp in self.player_city_plans:
            write_opt_str(writer, cp)
        if version >= 1.08:
            for ar in self.player_ai_rules:
                write_opt_str(writer, ar)
        for files in self.player_files:
            w.write_u32(len(files.build_list) if files.build_list else 0)
            w.write_u32(len(files.city_plan) if files.city_plan else 0)
            if version >= 1.08:
                w.write_u32(len(files.ai_rules) if files.ai_rules else 0)
            # Raw payload lengths + UTF-8 bytes: matches Rust ``write_all(string.as_bytes())`` (not ``write_str``).
            if files.build_list:
                w.write_bytes(files.build_list.encode("utf-8", errors="replace"))
            if files.city_plan:
                w.write_bytes(files.city_plan.encode("utf-8", errors="replace"))
            if version >= 1.08 and files.ai_rules:
                w.write_bytes(files.ai_rules.encode("utf-8", errors="replace"))
        if version >= 1.20:
            for t in self.ai_rules_types:
                w.write_i8(t)
        w.write_i32(-99)


@dataclass(slots=True)
class TribeScen:
    base: RGEScen
    player_start_resources: List[PlayerStartResources]
    victory: VictoryInfo
    victory_all_flag: bool
    mp_victory_type: int
    victory_score: int
    victory_time: int
    diplomacy: List[List[DiplomaticStance]]
    legacy_victory_info: List[List[LegacyVictoryInfo]]
    allied_victory: List[int]
    teams_locked: bool
    can_change_teams: bool
    random_start_locations: bool
    max_teams: int
    num_disabled_techs: List[int]
    disabled_techs: List[List[int]]
    num_disabled_units: List[int]
    disabled_units: List[List[int]]
    num_disabled_buildings: List[int]
    disabled_buildings: List[List[int]]
    combat_mode: int
    naval_mode: int
    all_techs: bool
    player_start_ages: List[StartingAge]
    view: Tuple[int, int]
    map_type: Optional[int]
    base_priorities: List[int]

    @staticmethod
    def read_from(reader: BinaryIO) -> "TribeScen":
        r = BinaryReader(reader)
        base = RGEScen.read_from(reader)
        version = base.version
        player_start_resources = [PlayerStartResources.default() for _ in range(16)]
        if version <= 1.13:
            for i in range(16):
                base.player_names[i] = read_str(reader, 256)
            for props, res in zip(base.player_base_properties, player_start_resources):
                props.active = r.read_i32()
                res2 = PlayerStartResources.read_from(reader, version)
                res.gold, res.wood, res.food, res.stone, res.ore, res.goods, res.player_color = (
                    res2.gold,
                    res2.wood,
                    res2.food,
                    res2.stone,
                    res2.ore,
                    res2.goods,
                    res2.player_color,
                )
                props.player_type = r.read_i32()
                props.civilization = r.read_i32()
                props.posture = r.read_i32()
        else:
            for i in range(16):
                player_start_resources[i] = PlayerStartResources.read_from(reader, version)
        if version >= 1.02:
            sep = r.read_i32()
            if sep != -99:
                raise ValueError("Bad separator")
        victory = VictoryInfo.read_from(reader)
        victory_all_flag = r.read_i32() != 0
        if version >= 1.13:
            mp_victory_type = r.read_i32()
            victory_score = r.read_i32()
            victory_time = r.read_i32()
        else:
            mp_victory_type = 4
            victory_score = 900
            victory_time = 9000
        diplomacy: List[List[DiplomaticStance]] = [[DiplomaticStance.Neutral for _ in range(16)] for _ in range(16)]
        for y in range(16):
            for x in range(16):
                diplomacy[y][x] = DiplomaticStance.try_from(r.read_i32())
        legacy_victory_info = [[LegacyVictoryInfo.read_from(reader) for _ in range(12)] for _ in range(16)]
        if version >= 1.02:
            sep = r.read_i32()
            if sep != -99:
                raise ValueError("Bad separator")
        allied_victory = [r.read_i32() for _ in range(16)]
        if version >= 1.24:
            teams_locked = r.read_i8() != 0
            can_change_teams = r.read_i8() != 0
            random_start_locations = r.read_i8() != 0
            max_teams = r.read_u8()
        elif f32_eq(version, 1.23):
            teams_locked = r.read_i32() != 0
            can_change_teams = True
            random_start_locations = True
            max_teams = 4
        else:
            teams_locked = False
            can_change_teams = True
            random_start_locations = True
            max_teams = 4

        num_disabled_techs = [0] * 16
        disabled_techs: List[List[int]] = [[] for _ in range(16)]
        num_disabled_units = [0] * 16
        disabled_units: List[List[int]] = [[] for _ in range(16)]
        num_disabled_buildings = [0] * 16
        disabled_buildings: List[List[int]] = [[] for _ in range(16)]

        if version >= 1.18:
            num_disabled_techs = [r.read_i32() for _ in range(16)]
            disabled_techs = [[r.read_i32() for _ in range(30)] for _ in range(16)]
            num_disabled_units = [r.read_i32() for _ in range(16)]
            disabled_units = [[r.read_i32() for _ in range(30)] for _ in range(16)]
            num_disabled_buildings = [r.read_i32() for _ in range(16)]
            max_disabled_buildings = 30 if version >= 1.25 else 20
            disabled_buildings = [[r.read_i32() for _ in range(max_disabled_buildings)] for _ in range(16)]
        elif version > 1.03:
            disabled_techs = [[r.read_i32() for _ in range(20)] for _ in range(16)]
            # guess num_disabled_techs
            for i in range(16):
                arr = disabled_techs[i]
                pos = next((idx for idx, val in enumerate(arr) if val <= 0), None)
                num_disabled_techs[i] = (pos + 1) if pos is not None else 0
        # else: no disabling

        combat_mode = r.read_i32() if version > 1.04 else 0
        if version >= 1.12:
            naval_mode = r.read_i32()
            all_techs = r.read_i32() != 0
        else:
            naval_mode = 0
            all_techs = False

        player_start_ages = [StartingAge.Default for _ in range(16)]
        if version > 1.05:
            for i in range(16):
                player_start_ages[i] = StartingAge.try_from(r.read_i32(), version)
        if version >= 1.02:
            sep = r.read_i32()
            if sep != -99:
                raise ValueError("Bad separator")
        view = (r.read_i32(), r.read_i32()) if version >= 1.19 else (-1, -1)
        if version >= 1.21:
            mt = r.read_i32()
            map_type = None if mt in (-2, -1) else mt
        else:
            map_type = None
        base_priorities = [0] * 16
        if version >= 1.24:
            base_priorities = [r.read_i8() for _ in range(16)]

        return TribeScen(
            base=base,
            player_start_resources=player_start_resources,
            victory=victory,
            victory_all_flag=victory_all_flag,
            mp_victory_type=mp_victory_type,
            victory_score=victory_score,
            victory_time=victory_time,
            diplomacy=diplomacy,
            legacy_victory_info=legacy_victory_info,
            allied_victory=allied_victory,
            teams_locked=teams_locked,
            can_change_teams=can_change_teams,
            random_start_locations=random_start_locations,
            max_teams=max_teams,
            num_disabled_techs=num_disabled_techs,
            disabled_techs=disabled_techs,
            num_disabled_units=num_disabled_units,
            disabled_units=disabled_units,
            num_disabled_buildings=num_disabled_buildings,
            disabled_buildings=disabled_buildings,
            combat_mode=combat_mode,
            naval_mode=naval_mode,
            all_techs=all_techs,
            player_start_ages=player_start_ages,
            view=view,
            map_type=map_type,
            base_priorities=base_priorities,
        )

    def write_to(self, writer: BinaryIO, version: float) -> None:
        # Note: For now, we implement only the exact write ordering used by the Rust crate.
        w = BinaryWriter(writer)
        self.base.write_to(writer, version)
        if version <= 1.13:
            for name in self.base.player_names:
                padded = bytearray(256)
                if name is not None:
                    # Rust: UTF-8 ``as_bytes()`` padding (read uses CP1252 ``read_str(256)`` — same as upstream).
                    nb = name.encode("utf-8", errors="replace")
                    padded[: len(nb)] = nb[:256]
                w.write_bytes(bytes(padded))
            for props, res in zip(self.base.player_base_properties, self.player_start_resources):
                w.write_i32(props.active)
                res.write_to(writer, version)
                w.write_i32(props.player_type)
                w.write_i32(props.civilization)
                w.write_i32(props.posture)
        else:
            for res in self.player_start_resources:
                res.write_to(writer, version)
        if version >= 1.02:
            w.write_i32(-99)
        self.victory.write_to(writer)
        w.write_i32(1 if self.victory_all_flag else 0)
        if version >= 1.13:
            w.write_i32(self.mp_victory_type)
            w.write_i32(self.victory_score)
            w.write_i32(self.victory_time)
        for row in self.diplomacy:
            for stance in row:
                w.write_i32(stance.to_i32())
        for row in self.legacy_victory_info:
            for entry in row:
                entry.write_to(writer)
        if version >= 1.02:
            w.write_i32(-99)
        for v in self.allied_victory:
            w.write_i32(v)
        if version >= 1.24:
            w.write_i8(1 if self.teams_locked else 0)
            w.write_i8(1 if self.can_change_teams else 0)
            w.write_i8(1 if self.random_start_locations else 0)
            w.write_u8(self.max_teams)
        elif f32_eq(version, 1.23):
            w.write_i32(1 if self.teams_locked else 0)

        # Disabled techs/units/buildings — AoC/HD-era layout (matches genie-scx ``TribeScen`` write path).
        if version >= 1.18:
            max_disabled_buildings = 30 if version >= 1.25 else 20
            most_b = max(self.num_disabled_buildings) if self.num_disabled_buildings else 0
            if most_b > max_disabled_buildings:
                raise TooManyDisabledBuildingsError(most_b, max_disabled_buildings)
            for n in self.num_disabled_techs:
                w.write_i32(n)
            for player_disabled in self.disabled_techs:
                for i in range(30):
                    w.write_i32(player_disabled[i] if i < len(player_disabled) else -1)
            for n in self.num_disabled_units:
                w.write_i32(n)
            for player_disabled in self.disabled_units:
                for i in range(30):
                    w.write_i32(player_disabled[i] if i < len(player_disabled) else -1)
            for n in self.num_disabled_buildings:
                w.write_i32(n)
            for player_disabled in self.disabled_buildings:
                for i in range(max_disabled_buildings):
                    w.write_i32(player_disabled[i] if i < len(player_disabled) else -1)
        elif version > 1.03:
            most_t = max(self.num_disabled_techs) if self.num_disabled_techs else 0
            if most_t > 20:
                raise TooManyDisabledTechsError(most_t)
            if any(n > 0 for n in self.num_disabled_units):
                raise CannotDisableUnitsError()
            if any(n > 0 for n in self.num_disabled_buildings):
                raise CannotDisableBuildingsError()
            for player_disabled in self.disabled_techs:
                for i in range(20):
                    w.write_i32(player_disabled[i] if i < len(player_disabled) else -1)
        else:
            if any(n > 0 for n in self.num_disabled_techs):
                raise CannotDisableTechsError()
            if any(n > 0 for n in self.num_disabled_units):
                raise CannotDisableUnitsError()
            if any(n > 0 for n in self.num_disabled_buildings):
                raise CannotDisableBuildingsError()

        if version > 1.04:
            w.write_i32(0)
        if version >= 1.12:
            w.write_i32(0)
            w.write_i32(1 if self.all_techs else 0)
        if version > 1.05:
            for age in self.player_start_ages:
                w.write_i32(age.to_i32(version))
        if version >= 1.02:
            w.write_i32(-99)
        if version >= 1.19:
            w.write_i32(self.view[0])
            w.write_i32(self.view[1])
        if version >= 1.21:
            w.write_i32(self.map_type if self.map_type is not None else -1)
        if version >= 1.24:
            for p in self.base_priorities:
                w.write_i8(p)

    def version(self) -> float:
        return self.base.version

    def description(self) -> Optional[str]:
        return self.base.description

    def legacy_ai_filenames(self) -> List[Optional[str]]:
        return self.base.player_ai_rules

    def legacy_ai_script_contents(self) -> List[Optional[str]]:
        return [pf.ai_rules for pf in self.base.player_files[:16]]

    def legacy_ai_rules_types(self) -> List[int]:
        return self.base.ai_rules_types


@dataclass(slots=True)
class SCXFormat:
    version: SCXVersion
    header: SCXHeader
    next_object_id: int
    tribe_scen: TribeScen
    map: Map
    world_players: List[WorldPlayerData]
    player_objects: List[List[ScenarioObject]]
    scenario_players: List[ScenarioPlayerData]
    triggers: Optional[TriggerSystem]
    ai_info: Optional[AIInfo]

    def version_bundle(self) -> VersionBundle:
        """
        Extract version bundle information from a parsed SCX file.

        Matches ``genie-scx`` ``SCXFormat::version`` (Rust cannot name this ``version`` on a struct
        that also has a ``version`` field; here we keep ``version_bundle`` to avoid clashing with
        the :attr:`version` container token field). Unlisted fields use :meth:`VersionBundle.aoc`
        defaults (``picture``, ``victory``, ``dlc_options``).
        """
        return replace(
            VersionBundle.aoc(),
            format=self.version,
            header=self.header.version,
            data=self.tribe_scen.version(),
            triggers=None if self.triggers is None else float(self.triggers.version),
            map=self.map.version,
        )

    @staticmethod
    def load_inner(version: SCXVersion, player_version: float, reader: BinaryIO) -> "SCXFormat":
        header = SCXHeader.read_from(reader, version)
        compressed = reader.read()
        payload = inflate_raw(compressed)
        if len(payload) < 8:
            raise EOFError("scenario payload too short")
        scenario_data_version = struct.unpack_from("<f", payload, 4)[0]
        if is_definitive_edition_scenario_data_version(scenario_data_version):
            raise DefinitiveEditionScenarioError(data_version=scenario_data_version)
        buf = io.BytesIO(payload)
        r = BinaryReader(buf)
        next_object_id = r.read_i32()
        tribe_scen = TribeScen.read_from(buf)
        map_ = Map.read_from(buf)
        num_players = r.read_u32()
        world_players: List[WorldPlayerData] = []
        for _ in range(1, num_players):
            world_players.append(WorldPlayerData.read_from(buf, player_version))

        def read_scenario_players() -> List[ScenarioPlayerData]:
            num = r.read_u32()
            players: List[ScenarioPlayerData] = []
            for _ in range(1, num):
                players.append(ScenarioPlayerData.read_from(buf, player_version))
            return players

        def read_player_objects() -> List[List[ScenarioObject]]:
            lists: List[List[ScenarioObject]] = []
            for pi in range(num_players):
                num_objects = r.read_u32()
                objs: List[ScenarioObject] = []
                for oi in range(num_objects):
                    try:
                        objs.append(ScenarioObject.read_from(buf, version))
                    except EOFError as err:
                        raise ValueError(
                            "Truncated scenario while reading placed objects "
                            f"(player index {pi + 1}/{num_players}, "
                            f"object {oi + 1}/{num_objects}). "
                            "The file may be incomplete or corrupt."
                        ) from err
                lists.append(objs)
            return lists

        player_objects = read_player_objects()
        scenario_players = read_scenario_players()

        triggers = None if version < SCXVersion(b"1.14") else TriggerSystem.read_from(buf)
        ai_info = AIInfo.read_from(buf) if (version > SCXVersion(b"1.17") and version < SCXVersion(b"2.00")) else None

        return SCXFormat(
            version=version,
            header=header,
            next_object_id=next_object_id,
            tribe_scen=tribe_scen,
            map=map_,
            world_players=world_players,
            player_objects=player_objects,
            scenario_players=scenario_players,
            triggers=triggers,
            ai_info=ai_info,
        )

    @staticmethod
    def load_scenario(reader: BinaryIO) -> "SCXFormat":
        header4 = reader.read(4)
        if header4 is None or len(header4) != 4:
            raise EOFError("missing format version")
        format_version = SCXVersion(header4)
        if is_ascii_scx_version_prefix(header4) and is_definitive_edition_container_format(format_version):
            raise DefinitiveEditionScenarioError(container_format=str(format_version))
        player_version = format_version.to_player_version()
        if player_version is None:
            raise UnsupportedFormatVersionError(format_version)
        return SCXFormat.load_inner(format_version, player_version, reader)

    def write_to(self, writer: BinaryIO, version: VersionBundle) -> None:
        if is_definitive_edition_container_format(version.format):
            raise DefinitiveEditionScenarioError(container_format=str(version.format))
        if is_definitive_edition_scenario_data_version(version.data):
            raise DefinitiveEditionScenarioError(data_version=version.data)
        player_version = version.format.to_player_version()
        if player_version is None:
            raise UnsupportedFormatVersionError(version.format)
        w = BinaryWriter(writer)
        w.write_bytes(version.format.as_bytes())
        self.header.write_to(writer, version.format, version.header)

        payload_buf = io.BytesIO()
        pw = BinaryWriter(payload_buf)
        pw.write_i32(self.next_object_id)
        self.tribe_scen.write_to(payload_buf, version.data)
        self.map.write_to(payload_buf, version.map)
        pw.write_i32(len(self.player_objects))
        for wp in self.world_players:
            wp.write_to(payload_buf, player_version)
        for objs in self.player_objects:
            pw.write_i32(len(objs))
            for obj in objs:
                obj.write_to(payload_buf, version.format)
        pw.write_i32(len(self.scenario_players) + 1)
        for sp in self.scenario_players:
            sp.write_to(payload_buf, player_version, version.victory)

        if version.format > SCXVersion(b"1.13"):
            triggers = self.triggers if self.triggers is not None else TriggerSystem.default()
            triggers.write_to(payload_buf, version.triggers if version.triggers is not None else 1.6)
        if version.format > SCXVersion(b"1.17") and version.format < SCXVersion(b"2.00"):
            ai = self.ai_info if self.ai_info is not None else AIInfo()
            ai.write_to(payload_buf)
        compressed = deflate_raw(payload_buf.getvalue(), level=6)
        w.write_bytes(compressed)

