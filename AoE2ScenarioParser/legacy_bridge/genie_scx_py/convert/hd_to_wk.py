from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from .._support.ids import UnitTypeID


@dataclass(slots=True)
class HDToWK:
    object_ids_map: Dict[int, UnitTypeID] = field(default_factory=dict)
    terrain_ids_map: Dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.object_ids_map:
            return
        self.object_ids_map = {
            1103: UnitTypeID(529),
            529: UnitTypeID(1103),
            1104: UnitTypeID(527),
            527: UnitTypeID(1104),
            1001: UnitTypeID(106),
            1003: UnitTypeID(114),
            1006: UnitTypeID(183),
            1007: UnitTypeID(203),
            1009: UnitTypeID(208),
            1010: UnitTypeID(223),
            1012: UnitTypeID(230),
            1013: UnitTypeID(260),
            1015: UnitTypeID(418),
            1016: UnitTypeID(453),
            1018: UnitTypeID(459),
            1103: UnitTypeID(467),
            1105: UnitTypeID(494),
            1104: UnitTypeID(653),
            947: UnitTypeID(699),
            948: UnitTypeID(701),
            1079: UnitTypeID(732),
            1021: UnitTypeID(734),
            1120: UnitTypeID(760),
            1155: UnitTypeID(762),
            1134: UnitTypeID(766),
            1132: UnitTypeID(774),
            1131: UnitTypeID(782),
            1129: UnitTypeID(784),
            1128: UnitTypeID(811),
            1126: UnitTypeID(823),
            1125: UnitTypeID(830),
            1123: UnitTypeID(836),
            946: UnitTypeID(848),
            1004: UnitTypeID(861),
            1122: UnitTypeID(891),
        }
        self.terrain_ids_map = {
            38: 33,
            45: 38,
            54: 11,
            55: 20,
            50: 41,
            49: 16,
            11: 3,
            16: 0,
            20: 19,
        }

    def convert(self, scen) -> None:
        for obj in scen.objects_mut():
            new_type = self.object_ids_map.get(int(obj.object_type))
            if new_type is not None:
                obj.object_type = new_type
        for tile in scen.map_mut().tiles:
            new_t = self.terrain_ids_map.get(int(tile.terrain))
            if new_t is not None:
                tile.terrain = new_t
        ts = scen.triggers_mut()
        if ts is not None:
            for trig in ts.triggers:
                for cond in trig.conditions:
                    nt = self.object_ids_map.get(int(cond.unit_type()))
                    if nt is not None:
                        cond.set_unit_type(nt)
                    nt = self.object_ids_map.get(int(cond.object_type()))
                    if nt is not None:
                        cond.set_object_type(nt)
                for eff in trig.effects:
                    nt = self.object_ids_map.get(int(eff.unit_type()))
                    if nt is not None:
                        eff.set_unit_type(nt)
                    nt = self.object_ids_map.get(int(eff.object_type()))
                    if nt is not None:
                        eff.set_object_type(nt)

