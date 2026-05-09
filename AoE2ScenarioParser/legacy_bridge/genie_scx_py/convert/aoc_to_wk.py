from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from .._support.ids import UnitTypeID


@dataclass(slots=True)
class AoCToWK:
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
        }
        self.terrain_ids_map = {
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

