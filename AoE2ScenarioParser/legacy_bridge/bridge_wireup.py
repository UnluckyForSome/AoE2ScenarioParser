from __future__ import annotations

"""
bridge_wireup.py

Glue-only entry point:
  legacy scenario file -> aoe2_geniescx.Scenario -> bridge_mapping -> AoE2DEScenario -> .aoe2scenario

Transformation logic belongs in `bridge_mapping.py`.
"""

import argparse
import importlib.util
import sys
from pathlib import Path

from AoE2ScenarioParser import settings
from AoE2ScenarioParser.helper.printers import warn
from AoE2ScenarioParser.scenarios.aoe2_de_scenario import AoE2DEScenario


def _load_bridge_mapping() -> object:
    """Load `bridge_mapping.py` as a module from disk (not installed as a package)."""
    mapping_path = Path(__file__).resolve().parent / "bridge_mapping.py"
    spec = importlib.util.spec_from_file_location("legacy_bridge_bridge_mapping", mapping_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load mapping module from: {mapping_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def convert_legacy_to_de(
    input_path: str | Path,
    output_path: str | Path,
) -> None:
    old_print = settings.PRINT_STATUS_UPDATES
    settings.PRINT_STATUS_UPDATES = False
    try:
        from aoe2_geniescx import Scenario

        scen = Scenario.read_from_bytes(Path(input_path).read_bytes())
        scenario = AoE2DEScenario.from_default()
        mapping = _load_bridge_mapping()
        apply = getattr(mapping, "apply_legacy_scenario_to_de_scenario", None)
        if apply is None:
            raise AttributeError("bridge_mapping.py must define apply_legacy_scenario_to_de_scenario(scen, scenario)")
        apply(scen, scenario)
        try:
            scenario.variant = "aoe2"
        except Exception as e:
            warn(f"Unable to set scenario variant: {e}")
        scenario.commit()
        scenario.write_to_file(str(output_path), skip_reconstruction=True)
    finally:
        settings.PRINT_STATUS_UPDATES = old_print


def main() -> int:
    ap = argparse.ArgumentParser(description="Legacy bridge wireup: legacy -> rebuilt DE .aoe2scenario")
    ap.add_argument(
        "legacy",
        type=Path,
        help="Legacy scenario file (binary container; first bytes are ASCII format version e.g. 1.21)",
    )
    ap.add_argument("output", type=Path, help="Output .aoe2scenario path")
    args = ap.parse_args()

    convert_legacy_to_de(args.legacy, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

