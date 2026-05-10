from __future__ import annotations

"""
Parse scenario files under a corpus directory with ``genie_scx_py`` and write ``parser_report.txt``.

By default every matching file under ``--root`` is parsed (sorted by path). Use ``-n`` for a random sample.

Example::

    py AoE2ScenarioParser/legacy_bridge/workbench/parser_validation/parser_validation.py
    py AoE2ScenarioParser/legacy_bridge/workbench/parser_validation/parser_validation.py -n 100 --seed 42
"""

import argparse
import random
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

_SCENARIO_SUFFIXES = frozenset({".scn", ".scx", ".aoe2scenario", ".scx2"})


def _legacy_bridge_root() -> Path:
    # .../legacy_bridge/workbench/parser_validation/parser_validation.py → parents[2] == legacy_bridge
    return Path(__file__).resolve().parents[2]


def _ensure_genie_scx_py_on_path() -> None:
    root = _legacy_bridge_root()
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)


def _iter_scenario_files(root: Path, recursive: bool) -> Iterable[Path]:
    it = root.rglob("*") if recursive else root.iterdir()
    for p in it:
        if not p.is_file():
            continue
        if p.suffix.lower() not in _SCENARIO_SUFFIXES:
            continue
        yield p


@dataclass(slots=True)
class ParseOutcome:
    path: str
    status: Literal["ok", "de_rejected", "error"]
    detail: str


def _parse_one(path: Path, *, full_tracebacks: bool) -> ParseOutcome:
    from genie_scx_py.scenario import Scenario  # type: ignore[import-not-found]
    from genie_scx_py.types import DefinitiveEditionScenarioError  # type: ignore[import-not-found]

    try:
        with path.open("rb") as f:
            Scenario.read_from(f)
        return ParseOutcome(str(path), "ok", "")
    except DefinitiveEditionScenarioError as e:
        return ParseOutcome(str(path), "de_rejected", str(e))
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if full_tracebacks:
            msg = f"{msg}\n{traceback.format_exc()}"
        return ParseOutcome(str(path), "error", msg)


def _write_report(
    output: Path,
    *,
    root: Path,
    sample_limit: int | None,
    seed: int | None,
    recursive: bool,
    candidates: int,
    files_run: list[Path],
    outcomes: list[ParseOutcome],
) -> None:
    ok = sum(1 for o in outcomes if o.status == "ok")
    de_rejected = sum(1 for o in outcomes if o.status == "de_rejected")
    errors = sum(1 for o in outcomes if o.status == "error")

    lines: list[str] = [
        "genie_scx_py parser validation report",
        "====================================",
        f"Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
        f"Corpus root: {root}",
        f"Recursive listing: {recursive}",
        f"Scenario suffixes: {', '.join(sorted(_SCENARIO_SUFFIXES))}",
        f"Candidates matching suffixes: {candidates}",
        f"Random sample limit (-n): {sample_limit if sample_limit is not None else '(none — all files)'}",
        f"Files parsed: {len(files_run)}",
        f"Random seed (only if -n): {seed!r}",
        "",
        "Summary",
        "-------",
        f"  Parsed OK:           {ok}",
        f"  DE rejected (policy): {de_rejected}",
        f"  Parse errors:         {errors}",
        "",
        "Per file (parse errors and DE rejected)",
        "---------------------------------------",
    ]

    listed = [o for o in outcomes if o.status in ("error", "de_rejected")]
    if not listed:
        lines.append("(none)")
        lines.append("")
    else:
        for o in listed:
            tag = "ERROR" if o.status == "error" else "DE_REJECTED"
            lines.append(f"[{tag}] {o.path}")
            if o.detail:
                for sub in o.detail.strip().splitlines():
                    lines.append(f"    {sub}")
            lines.append("")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    default_root = Path(r"Z:\AOE2\AOE2 Archive Project\Custom Scenarios\Live")
    default_out = Path(__file__).resolve().parent / "parser_report.txt"

    ap = argparse.ArgumentParser(
        description="Parse scenarios with genie_scx_py and write a report (default: every file under --root)."
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=default_root,
        help=f"Directory to scan for scenario files (default: {default_root})",
    )
    ap.add_argument(
        "-n",
        "--count",
        type=int,
        default=None,
        metavar="N",
        help="Parse only N randomly chosen files. Default: parse all matching files (sorted by path).",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed when using -n (ignored when parsing all files).",
    )
    ap.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only scan the root directory, not subfolders.",
    )
    ap.add_argument("-o", "--output", type=Path, default=default_out, help=f"Report path (default: {default_out})")
    ap.add_argument(
        "--full-tracebacks",
        action="store_true",
        help="Include full tracebacks for parse errors in the report (can be large).",
    )
    args = ap.parse_args()

    root: Path = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 1

    if args.count is not None and args.count < 1:
        print("--count/-n must be >= 1 when given", file=sys.stderr)
        return 1

    recursive = not args.no_recursive
    candidates = sorted(_iter_scenario_files(root, recursive), key=lambda p: str(p).lower())
    n_cand = len(candidates)
    if n_cand == 0:
        print(f"No scenario files ({', '.join(sorted(_SCENARIO_SUFFIXES))}) under {root}", file=sys.stderr)
        return 1

    if args.count is None:
        files_run = candidates
    else:
        if args.seed is not None:
            random.seed(args.seed)
        k = min(args.count, n_cand)
        files_run = random.sample(candidates, k=k)

    _ensure_genie_scx_py_on_path()

    outcomes: list[ParseOutcome] = []
    for i, path in enumerate(files_run, start=1):
        print(f"[{i}/{len(files_run)}] {path.name}", flush=True)
        outcomes.append(_parse_one(path, full_tracebacks=args.full_tracebacks))

    _write_report(
        args.output,
        root=root,
        sample_limit=args.count,
        seed=args.seed,
        recursive=recursive,
        candidates=n_cand,
        files_run=files_run,
        outcomes=outcomes,
    )
    print(f"Wrote {args.output}")
    errors_n = sum(1 for o in outcomes if o.status == "error")
    return 1 if errors_n else 0


if __name__ == "__main__":
    raise SystemExit(main())
