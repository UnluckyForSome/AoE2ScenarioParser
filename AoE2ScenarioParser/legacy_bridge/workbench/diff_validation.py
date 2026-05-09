from __future__ import annotations

"""
diff_validation.py

This is a debugging-first workbench script. It rebuilds legacy scenarios via the bridge and produces
deterministic, heavily filtered diff outputs against DE-resaved references.
"""

import argparse
import importlib.util
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Match

from AoE2ScenarioParser import settings
from AoE2ScenarioParser.scenarios.aoe2_de_scenario import AoE2DEScenario
from AoE2ScenarioParser.scenarios.scenario_debug.compare import debug_compare


# ============================================================
# DIFF IGNORE START 
# ============================================================
#
# POLICY: remove unstable/non-semantic churn so remaining diffs are actionable mapping issues.
# Rationale is kept inline next to each ignored path/pattern below.

# Ignored (prefix, case-insensitive)
IGNORED_PREFIXES: tuple[str, ...] = (
    "FileHeader > timestamp_of_last_save",  # save time always differs
    "FileHeader > creator_name",  # conversion stamps a different creator vs DE resave
    "FileHeader > creator_version",  # conversion stamps a different creator vs DE resave
    "FileHeader > amount_of_unknown_numbers",  # header padding differs between pipelines
    "FileHeader > unknown_numbers",  # header padding differs between pipelines
    "FileHeader > scenario_instructions",  # DE often rewrites long-form instructions on open/resave
    "DataHeader > next_unit_id_to_place",  # placeholder; not meaningful for parity tracking

    # Opaque fixed-width tail bytes; DE/editor differs after open/resave vs bridge-from-default.
    "DataHeader > unknown",
    "DataHeader > filename",  # rebuilt uses legacy stem; reference uses resaved name
    "DataHeader > string_table_player_names",  # legacy string-table IDs don't match DE
    "DataHeader > tribe_names",  # DE resave resolves tribe names differently
    "Messages >",  # message IDs/rows churn across versions/editors
    "Cinematics >",  # same churn for cinematic hooks
    "Files > ai_files",  # legacy AI structure differs vs DE resave
    "Files > number_of_ai_files",  # derived count for ai_files
    "Files > ai_files_present",  # derived flag for ai_files
    
    # DE resaves sometimes materialize an AI error entry; rebuilt legacy output treats as absent.
    "Files > ai_error_present",
    "Files > ai_error",
    "Units > players_units > players_units[0] > unit_count",  # GAIA unit list churn vs DE-resaved refs
    "Units > players_units > players_units[0] > units",  # GAIA unit list churn vs DE-resaved refs
)

# Ignored (substring, case-insensitive):
IGNORED_SUBSTRINGS: tuple[str, ...] = (
    # PlayerDataTwo.resources row churn vs DE (includes legacy ore vs ore_x_unused editor hydration).
    "playerdatatwo > resources >",
    # Units.player_data_4 duplicate ore mirror slot vs DE resave.
    " > ore_x_duplicate",
    "string_table",  # legacy string-table IDs don't match DE
    "_stid",  # string-table IDs don't match DE
    "short_description_string_table_id",  # string-table IDs don't match DE
    "description_string_table_id",  # string-table IDs don't match DE
    "initial_animation_frame",  # legacy frame ↔ DE animation_frame quirks vs editor resaves
    "playerdatatwo > ai_files",  # legacy AI blobs differ structurally vs DE resaves
    "options > unknown_1",  # opaque bytes; unstable between pipelines
    "triggers > trigger_instruction_start",  # editor/resave toggles; not derived from legacy
    "units > player_data_3 > player_data_3[",  # editor-initialized camera slots; not fully exported
    "unknown_4",  # opaque unknown slot under player_data_3
    "> rotation",  # unit facing quantization/rounding differs vs editor resaves
)

# Ignored (suffix, case-insensitive) – avoids false positives like `string_id_option1`.
IGNORED_SUFFIXES: tuple[str, ...] = (
    " > string_id",  # string-table backed IDs (but not string_id_option1)
    " > item_id",  # DE resave sets trigger effect item_id to -1; rebuilt legacy mapping is correct
)

# Chunk-level ignores (whole debug_compare hunk, not just the path line).
IGNORED_CHUNK_REGEXES: tuple[re.Pattern[str], ...] = (
    # debug_compare treats NaN != NaN and emits `DIFFERENT VALUES (nan vs nan)` — not actionable parity signal.
    re.compile(r"\bnan\s+vs\s+nan\b", re.IGNORECASE),
)

# ============================================================
# DIFF IGNORE END
# ============================================================


def _path_is_ignored(path_line: str) -> bool:
    if path_line.startswith(IGNORED_PREFIXES):
        return True
    pl = path_line.lower()
    if any(pl.endswith(s) for s in IGNORED_SUFFIXES):
        return True
    return any(s in pl for s in IGNORED_SUBSTRINGS)


def _filter_diff_text(content: str) -> str:
    parts = content.split("\n\n\n")
    kept: list[str] = []
    for raw in parts:
        chunk = raw.strip("\n")
        if not chunk:
            continue
        path_line = chunk.split("\n", 1)[0].strip()
        if not path_line:
            continue
        if _path_is_ignored(path_line):
            continue
        if any(rx.search(chunk) for rx in IGNORED_CHUNK_REGEXES):
            continue
        kept.append(chunk)
    if not kept:
        return "\n"
    return "\n\n\n" + "\n\n\n".join(kept) + "\n"


def _write_filtered_diff(diff_path: Path) -> None:
    text = diff_path.read_text(encoding="utf-8", errors="replace")
    out = _filter_diff_text(text)
    diff_path.write_text(out, encoding="utf-8")


# debug_compare path lines look like: `Triggers > trigger_data > ...`
_PATH_LINE = re.compile(r"^[A-Za-z_][^\n]* > [^\n]+$")

_TRIGGER_DATA_IDX = re.compile(r"trigger_data\[(\d+)\]")


def _diff_file_pair_base(diff_path: Path) -> str:
    """`Original X.diff.txt` → base stem used for `Original X_rebuilt.aoe2scenario`."""
    name = diff_path.name
    if name.endswith(".diff.txt"):
        return name[: -len(".diff.txt")]
    return diff_path.stem


def _chunk_path_and_reason(chunk: str) -> tuple[str, str]:
    lines = chunk.splitlines()
    path_line = lines[0].strip() if lines else ""
    reason_line = ""
    for ln in lines[1:]:
        if ln.strip():
            reason_line = ln.strip()
            break
    return path_line, reason_line


def _parse_diff_values_reason(reason_line: str) -> tuple[str, str] | None:
    """Parse `DIFFERENT VALUES (a vs b)` from debug_compare (first line after path)."""
    s = reason_line.strip()
    if not s.startswith("DIFFERENT VALUES"):
        return None
    inner = s[len("DIFFERENT VALUES") :].strip()
    if not (inner.startswith("(") and inner.endswith(")")):
        return None
    inner = inner[1:-1].strip()
    if " vs " not in inner:
        return None
    left, right = inner.split(" vs ", 1)
    return (left.strip(), right.strip())


def _comparison_summary(reason_line: str) -> str:
    parsed = _parse_diff_values_reason(reason_line)
    if parsed:
        left, right = parsed
        return f"DV · RebuiltLegacy: `{left}` · ResavedDE: `{right}`"
    return reason_line.strip()


def _inject_trigger_names(path_line: str, idx_to_name: dict[int, str]) -> str:
    def repl(m: Match[str]) -> str:
        i = int(m.group(1))
        name = idx_to_name.get(i)
        if not name:
            return m.group(0)
        short = name.replace("\r", " ").replace("\n", " ").strip()
        if len(short) > 72:
            short = short[:69] + "..."
        return f"trigger_data[{i}] ({short})"

    return _TRIGGER_DATA_IDX.sub(repl, path_line)


def _load_trigger_index_to_name(rebuilt_path: Path) -> dict[int, str]:
    """Map trigger_data list index → trigger display name from rebuilt scenario file."""
    if not rebuilt_path.is_file():
        return {}
    old_print = settings.PRINT_STATUS_UPDATES
    settings.PRINT_STATUS_UPDATES = False
    try:
        scn = AoE2DEScenario.from_file(str(rebuilt_path))
        out = {i: (t.name or f"<unnamed #{i}>") for i, t in enumerate(scn.trigger_manager.triggers)}
    except Exception:
        out = {}
    finally:
        settings.PRINT_STATUS_UPDATES = old_print
    return out


def _markdown_escape_cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


@dataclass(frozen=True)
class Pair:
    base: str
    legacy: Path
    reference: Path


def _legacy_bridge_root() -> Path:
    """``legacy_bridge/`` (parent of ``workbench/``)."""
    return Path(__file__).resolve().parents[1]


def _workbench_root() -> Path:
    return Path(__file__).resolve().parent


def _diffchecks_root() -> Path:
    return _workbench_root() / "diffchecks"


def _resolve_diffcheck_set_dir(set_name_or_dir: str) -> Path:
    """
    Resolve a diffcheck set directory.

    Layout (per set):
      workbench/diffchecks/<SET>/
        inputs/                 (legacy + *DE reference pairs live here)
        outputs/rebuilt_scenarios/
        outputs/diffs/          (*.diff.txt + summary.txt)

    """
    p = Path(set_name_or_dir)
    if not p.is_absolute():
        p = _diffchecks_root() / p
    return p.resolve()


def _diffcheck_set_pairs_dir(set_dir: Path) -> Path:
    return set_dir / "inputs"


def _diffcheck_set_outputs_dir(set_dir: Path) -> Path:
    return set_dir / "outputs"


def _diffcheck_set_diffs_dir(set_dir: Path) -> Path:
    return _diffcheck_set_outputs_dir(set_dir) / "diffs"


def _diffcheck_set_rebuilt_dir(set_dir: Path) -> Path:
    return _diffcheck_set_outputs_dir(set_dir) / "rebuilt_scenarios"


def _load_wireup_module() -> object:
    wireup_path = _legacy_bridge_root() / "bridge_wireup.py"
    spec = importlib.util.spec_from_file_location("legacy_bridge_bridge_wireup", wireup_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load wireup module from: {wireup_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def discover_pairs(pairs_dir: Path) -> list[Pair]:
    """
    Deterministically choose one legacy file `X.*` and one reference file `XDE.*` for each base `X`.
    """
    files = [p for p in pairs_dir.iterdir() if p.is_file()]
    by_stem: dict[str, list[Path]] = {}
    for p in files:
        by_stem.setdefault(p.stem, []).append(p)

    bases: set[str] = set()
    for stem in by_stem:
        if stem.endswith("DE"):
            bases.add(stem[:-2])
        else:
            bases.add(stem)

    out: list[Pair] = []
    for base in sorted(bases):
        legacy_candidates = sorted(by_stem.get(base, []), key=lambda p: (p.suffix.lower(), p.name.lower()))
        ref_candidates = sorted(by_stem.get(f"{base}DE", []), key=lambda p: (p.suffix.lower(), p.name.lower()))
        if not legacy_candidates or not ref_candidates:
            continue
        out.append(Pair(base=base, legacy=legacy_candidates[0], reference=ref_candidates[0]))
    return out


def rebuild_compare(
    *,
    set_dir: Path,
) -> int:
    pairs_dir = _diffcheck_set_pairs_dir(set_dir)
    diffs_dir = _diffcheck_set_diffs_dir(set_dir)
    rebuilt_dir = _diffcheck_set_rebuilt_dir(set_dir)
    diffs_dir.mkdir(parents=True, exist_ok=True)
    rebuilt_dir.mkdir(parents=True, exist_ok=True)

    pairs = discover_pairs(pairs_dir)
    if not pairs:
        print(f"No pairs found in {pairs_dir}")
        return 1

    wireup = _load_wireup_module()
    convert = getattr(wireup, "convert_legacy_to_de", None)
    if convert is None:
        raise AttributeError("bridge_wireup.py must define convert_legacy_to_de(...)")

    old_print = settings.PRINT_STATUS_UPDATES
    settings.PRINT_STATUS_UPDATES = False
    failures: list[str] = []
    try:
        for pair in pairs:
            rebuilt = rebuilt_dir / f"{pair.base}_rebuilt.aoe2scenario"
            diff_path = diffs_dir / f"{pair.base}.diff.txt"

            print(f"BUILD {pair.legacy.name} -> {rebuilt.name}")
            try:
                convert(pair.legacy, rebuilt)

                print(f"DIFF  {rebuilt.name} vs {pair.reference.name} -> {diff_path.name}")
                rebuilt_scn = AoE2DEScenario.from_file(str(rebuilt))
                ref_scn = AoE2DEScenario.from_file(str(pair.reference))
                debug_compare(rebuilt_scn, ref_scn, str(diff_path), commit=False, allow_multiple_versions=True)
                _write_filtered_diff(diff_path)
            except Exception as e:
                err = f"{pair.base}: {e}"
                print(f"FAILED {err}")
                failures.append(err)
                try:
                    if diff_path.is_file():
                        diff_path.unlink()
                except OSError:
                    pass
    finally:
        settings.PRINT_STATUS_UPDATES = old_print

    if failures:
        print(
            f"\n{len(failures)} pair(s) failed "
            f"(rebuilt/diff for those stems may be missing or stale):\n"
            + "\n".join(failures)
        )
    return 1 if failures else 0


def _write_summary(*, set_dir: Path) -> int:
    diffs_dir = _diffcheck_set_diffs_dir(set_dir)
    diffs_dir.mkdir(parents=True, exist_ok=True)
    rebuilt_root = _diffcheck_set_rebuilt_dir(set_dir)

    counts: Counter[tuple[str, str]] = Counter()
    sources: defaultdict[tuple[str, str], set[str]] = defaultdict(set)

    files = sorted(diffs_dir.glob("*.diff.txt"))
    for diff_path in files:
        pair_base = _diff_file_pair_base(diff_path)
        rebuilt_path = rebuilt_root / f"{pair_base}_rebuilt.aoe2scenario"
        idx_to_name = _load_trigger_index_to_name(rebuilt_path)

        text = diff_path.read_text(encoding="utf-8", errors="replace")
        for raw in text.split("\n\n\n"):
            chunk = raw.strip("\n")
            if not chunk:
                continue
            path_line, reason_line = _chunk_path_and_reason(chunk)
            if not path_line or not _PATH_LINE.match(path_line) or " > " not in path_line:
                continue
            if _path_is_ignored(path_line) or any(rx.search(chunk) for rx in IGNORED_CHUNK_REGEXES):
                continue

            enriched_path = _inject_trigger_names(path_line, idx_to_name)
            comparison = _comparison_summary(reason_line)
            key = (enriched_path, comparison)
            counts[key] += 1
            sources[key].add(pair_base)

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))
    total = sum(counts.values())

    out_lines = [
        "# Legacy bridge diff summary",
        "#",
        "# Rows omitted by policy: top of `diff_validation.py` (DIFF IGNORE POLICY + NaN-vs-NaN chunks).",
        "# Trigger names come from `outputs/.../rebuilt_scenarios/<same stem>_rebuilt.aoe2scenario` "
        "(see `--rebuilt-subdir` if you did not use default rebuilt layout).",
        "# Compare column: first value = rebuilt legacy bridge output; second = DE reference scenario.",
        "#",
        f"# {len(ranked)} distinct path+comparison rows · {total} occurrences total · {len(files)} diff files",
        "",
        "| Occurrences | Seen in diff file(s) | Path | Comparison |",
        "|------------:|----------------------|------|------------|",
    ]
    for (path_s, cmp_s), c in ranked:
        seen = ", ".join(sorted(sources[(path_s, cmp_s)]))
        out_lines.append(
            "| "
            + " | ".join(
                [
                    str(c),
                    _markdown_escape_cell(seen),
                    _markdown_escape_cell(path_s),
                    _markdown_escape_cell(cmp_s),
                ]
            )
            + " |"
        )

    summary_path = diffs_dir / "summary.txt"
    summary_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"Wrote {summary_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Legacy bridge workbench: rebuild + diff + summarize (diffcheck sets only).")
    ap.add_argument(
        "--set",
        required=True,
        help="Diffcheck set name under workbench/diffchecks/<SET>/ (uses inputs/ + outputs/{rebuilt_scenarios,diffs}).",
    )

    args = ap.parse_args()
    set_dir = _resolve_diffcheck_set_dir(args.set)

    rc = rebuild_compare(set_dir=set_dir)
    _write_summary(set_dir=set_dir)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

