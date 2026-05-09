from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Iterator, Optional

from .format import SCXFormat, ScenarioObject
from .map import Map
from .player import ScenarioPlayerData, WorldPlayerData
from .triggers import TriggerSystem
from .types import SCXVersion, VersionBundle


@dataclass(slots=True)
class Scenario:
    format: SCXFormat
    version_bundle: VersionBundle

    @staticmethod
    def read_from(reader: BinaryIO) -> "Scenario":
        fmt = SCXFormat.load_scenario(reader)
        vb = fmt.version_bundle()
        return Scenario(format=fmt, version_bundle=vb)

    @staticmethod
    def read_from_bytes(data: bytes) -> "Scenario":
        import io

        return Scenario.read_from(io.BytesIO(data))

    def write_to(self, writer: BinaryIO) -> None:
        self.format.write_to(writer, self.version_bundle)

    def write_to_version(self, writer: BinaryIO, version: VersionBundle) -> None:
        self.format.write_to(writer, version)

    def format_version(self) -> SCXVersion:
        return self.version_bundle.format

    def header_version(self) -> int:
        return self.version_bundle.header

    def data_version(self) -> float:
        return self.version_bundle.data

    def header(self):
        return self.format.header

    def description(self) -> Optional[str]:
        return self.format.tribe_scen.description()

    def filename(self) -> str:
        return self.format.tribe_scen.base.name

    def version(self) -> VersionBundle:
        return self.version_bundle

    def mod_name(self) -> Optional[str]:
        # Mirrors rust: tribe_scen.base.player_names[9]
        try:
            return self.format.tribe_scen.base.player_names[9]
        except Exception:
            return None

    def objects(self) -> Iterator[ScenarioObject]:
        for lst in self.format.player_objects:
            for obj in lst:
                yield obj

    def objects_mut(self) -> Iterator[ScenarioObject]:
        return self.objects()

    def world_players(self) -> list[WorldPlayerData]:
        return self.format.world_players

    def scenario_players(self) -> list[ScenarioPlayerData]:
        return self.format.scenario_players

    def map(self) -> Map:
        return self.format.map

    def map_mut(self) -> Map:
        return self.format.map

    def triggers(self) -> Optional[TriggerSystem]:
        return self.format.triggers

    def triggers_mut(self) -> Optional[TriggerSystem]:
        return self.format.triggers

