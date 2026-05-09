from __future__ import annotations

from dataclasses import dataclass

from ..scenario import Scenario  # added later in scenario-top

from .aoc_to_wk import AoCToWK
from .hd_to_wk import HDToWK


class ConvertError(ValueError):
    pass


def _is_wk_object(obj) -> bool:
    STORMY_DOG = 862
    return int(obj.id) > STORMY_DOG


@dataclass(slots=True)
class AutoToWK:
    def convert(self, scen: "Scenario") -> None:
        if scen.version().is_hd_edition():
            HDToWK().convert(scen)
        elif scen.version().is_aok() or scen.version().is_aoc():
            if any(_is_wk_object(o) for o in scen.objects()):
                return
            AoCToWK().convert(scen)
        else:
            raise ConvertError("invalid version")

