from __future__ import annotations

"""
Developer helpers for the legacy bridge workbench.

Replaces ad-hoc checks that previously lived under ``tests/legacy_bridge/`` (parse corpus,
smallsample smoke invariants, round-trip sanity). Run from repo root, for example::

    py AoE2ScenarioParser/legacy_bridge/workbench/devtools.py parse-diffchecks
    py AoE2ScenarioParser/legacy_bridge/workbench/devtools.py smoke-smallsample
    py AoE2ScenarioParser/legacy_bridge/workbench/devtools.py round-trip-smallsample
"""

import argparse
import io
import sys
from pathlib import Path


def _legacy_bridge_root() -> Path:
    # .../legacy_bridge/workbench/devtools.py → parents[1] == legacy_bridge
    return Path(__file__).resolve().parents[1]


def _diffchecks_root() -> Path:
    return _legacy_bridge_root() / "workbench" / "diffchecks"


def _smallsample_inputs() -> Path:
    return _diffchecks_root() / "legacy_de_pairs_smallsample" / "inputs"


_SKIP_PARSE_NAMES = frozenset({"corlis.aoescn", "original aok - joan 6.scn"})


def cmd_parse_diffchecks() -> int:
    """Parse every legacy container file under ``workbench/diffchecks/*/inputs``."""
    from genie_scx_py.scenario import Scenario  # type: ignore[import-not-found]
    from genie_scx_py.types import legacy_format_version_peek_path  # type: ignore[import-not-found]

    root = _diffchecks_root()
    files: list[Path] = []
    for p in root.rglob("inputs/*"):
        if not p.is_file():
            continue
        if p.name.lower() in _SKIP_PARSE_NAMES:
            continue
        if legacy_format_version_peek_path(p) is None:
            continue
        files.append(p)

    files.sort(key=lambda x: str(x))
    if not files:
        print(f"No inputs found under {root}", file=sys.stderr)
        return 1

    failures: list[tuple[str, str]] = []
    for path in files:
        try:
            with path.open("rb") as f:
                Scenario.read_from(f)
            print(f"OK {path.relative_to(root)}")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            failures.append((str(path), err))
            print(f"FAIL {path.relative_to(root)} — {err}")

    if failures:
        print(f"\n{len(failures)} failure(s) out of {len(files)}", file=sys.stderr)
        return 1
    print(f"\nAll {len(files)} file(s) parsed OK.")
    return 0


def cmd_smoke_smallsample() -> int:
    """Parse ``legacy_de_pairs_smallsample`` legacy files and assert basic structural invariants."""
    from genie_scx_py import Scenario  # type: ignore[import-not-found]
    from genie_scx_py.types import legacy_format_version_peek_path  # type: ignore[import-not-found]

    sample_dir = _smallsample_inputs()
    if not sample_dir.is_dir():
        print(f"Missing directory: {sample_dir}", file=sys.stderr)
        return 1

    paths = sorted(
        p for p in sample_dir.iterdir() if p.is_file() and legacy_format_version_peek_path(p) is not None
    )
    if not paths:
        print(f"No legacy scenario headers in {sample_dir}", file=sys.stderr)
        return 1

    errors: list[str] = []
    for path in paths:
        try:
            scen = Scenario.read_from_bytes(path.read_bytes())
            fmt = scen.format
            fe: list[str] = []
            if fmt.header is None:
                fe.append("missing header")
            w, h = int(fmt.map.width), int(fmt.map.height)
            if w < 1:
                fe.append("map.width < 1")
            if w != h:
                fe.append(f"map not square ({w}x{h})")
            if len(fmt.map.tiles) == 0:
                fe.append("no tiles")
            if len(fmt.world_players) < 8:
                fe.append(f"world_players len {len(fmt.world_players)}")
            if len(fmt.player_objects) < 8:
                fe.append(f"player_objects len {len(fmt.player_objects)}")
            if len(fmt.scenario_players) < 8:
                fe.append(f"scenario_players len {len(fmt.scenario_players)}")
            tribe = fmt.tribe_scen
            if tribe.base is None:
                fe.append("tribe_scen.base missing")
            if len(tribe.legacy_ai_filenames()) < 16:
                fe.append("legacy_ai_filenames len < 16")
            if fe:
                for msg in fe:
                    line = f"{path.name}: {msg}"
                    errors.append(line)
                    print(f"FAIL {line}", file=sys.stderr)
            else:
                print(f"OK {path.name}")
        except Exception as e:
            line = f"{path.name}: {type(e).__name__}: {e}"
            errors.append(line)
            print(f"FAIL {line}", file=sys.stderr)

    if errors:
        print(f"\n{len(errors)} issue(s).", file=sys.stderr)
        return 1
    print(f"\nSmoke OK for {len(paths)} file(s).")
    return 0


def cmd_round_trip_smallsample() -> int:
    """Read/write/read smallsample legacy files; compare format + header version."""
    from genie_scx_py.scenario import Scenario  # type: ignore[import-not-found]
    from genie_scx_py.types import legacy_format_version_peek_path  # type: ignore[import-not-found]

    sample_dir = _smallsample_inputs()
    if not sample_dir.is_dir():
        print(f"Missing directory: {sample_dir}", file=sys.stderr)
        return 1

    paths = sorted(
        p for p in sample_dir.iterdir() if p.is_file() and legacy_format_version_peek_path(p) is not None
    )
    if not paths:
        print(f"No legacy scenario headers in {sample_dir}", file=sys.stderr)
        return 1

    failures: list[str] = []
    for path in paths:
        try:
            data = path.read_bytes()
            scen = Scenario.read_from(io.BytesIO(data))
            out = io.BytesIO()
            scen.write_to(out)
            scen2 = Scenario.read_from(io.BytesIO(out.getvalue()))
            bad: list[str] = []
            if str(scen.version().format) != str(scen2.version().format):
                bad.append("format version mismatch")
            if int(scen.version().header) != int(scen2.version().header):
                bad.append("header version mismatch")
            if bad:
                for msg in bad:
                    line = f"{path.name}: {msg}"
                    failures.append(line)
                    print(f"FAIL {line}", file=sys.stderr)
            else:
                print(f"OK {path.name}")
        except Exception as e:
            line = f"{path.name}: {type(e).__name__}: {e}"
            failures.append(line)
            print(f"FAIL {line}", file=sys.stderr)

    if failures:
        print(f"\n{len(failures)} failure(s).", file=sys.stderr)
        return 1
    print(f"\nRound-trip OK for {len(paths)} file(s).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Legacy bridge workbench devtools")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "parse-diffchecks",
        help="Parse all files under diffchecks/*/inputs whose header is a supported legacy format version",
    )
    sub.add_parser("smoke-smallsample", help="Structural smoke test on legacy_de_pairs_smallsample inputs")
    sub.add_parser("round-trip-smallsample", help="Read/write/read smallsample legacy scenarios")

    args = ap.parse_args()
    if args.cmd == "parse-diffchecks":
        return cmd_parse_diffchecks()
    if args.cmd == "smoke-smallsample":
        return cmd_smoke_smallsample()
    if args.cmd == "round-trip-smallsample":
        return cmd_round_trip_smallsample()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
