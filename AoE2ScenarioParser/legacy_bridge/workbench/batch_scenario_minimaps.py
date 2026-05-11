from __future__ import annotations

"""
Batch-render small minimap images from AoE II scenarios using McMinimap (legacy .scn/.scx + DE .aoe2scenario).

By default every matching file under ``--root`` is rendered (sorted by path). Use ``-n`` for a random sample.

Outputs mirror relative paths from ``--root`` under ``-o`` (default: ``othertools/aoe2mcminimap_output``).

**Transparency:** use ``--format webp`` (default) or ``png``. JPEG has no alpha.

**Compression:** lossy **WebP** with alpha is usually the best size/quality tradeoff for web thumbnails.
Use ``--format png`` for lossless alpha (larger). Tune ``--webp-quality`` / ``--webp-method``.

Example::

    py AoE2ScenarioParser/legacy_bridge/workbench/batch_scenario_minimaps.py
    py AoE2ScenarioParser/legacy_bridge/workbench/batch_scenario_minimaps.py -n 100 --seed 42

On Windows, if legacy scenarios fail with ``UnicodeDecodeError``, use UTF-8 (e.g. ``set PYTHONUTF8=1``).
"""

import argparse
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

_SCENARIO_SUFFIXES = frozenset({".scn", ".scx", ".aoe2scenario", ".scx2"})

OutputFormat = Literal["webp", "png", "jpeg"]

_FORMAT_SUFFIX: dict[OutputFormat, str] = {
    "webp": ".webp",
    "png": ".png",
    "jpeg": ".jpg",
}


def _workbench_dir() -> Path:
    return Path(__file__).resolve().parent


def _legacy_bridge_root() -> Path:
    # .../legacy_bridge/workbench/batch_scenario_minimaps.py -> parents[1] == legacy_bridge
    return Path(__file__).resolve().parents[1]


def _aoesp_package_root() -> Path:
    """Directory that contains the ``AoE2ScenarioParser`` package tree."""
    return _legacy_bridge_root().parent


def _default_minimap_output_dir() -> Path:
    return _workbench_dir() / "othertools" / "aoe2mcminimap_output"


def _ensure_import_paths() -> None:
    pkg = str(_aoesp_package_root())
    if pkg not in sys.path:
        sys.path.insert(0, pkg)


def _iter_scenario_files(root: Path, recursive: bool) -> Iterable[Path]:
    it = root.rglob("*") if recursive else root.iterdir()
    for p in it:
        if not p.is_file():
            continue
        if p.suffix.lower() not in _SCENARIO_SUFFIXES:
            continue
        yield p


def _build_jobs(
    root: Path, out_root: Path, paths: list[Path], *, format_name: OutputFormat
) -> list[tuple[Path, Path]]:
    root_res = root.resolve()
    suf = _FORMAT_SUFFIX[format_name]
    jobs: list[tuple[Path, Path]] = []
    for path in paths:
        rel = path.resolve().relative_to(root_res)
        jobs.append((path, (out_root / rel).with_suffix(suf)))
    return jobs


def _save_rgba_thumbnail(
    img,
    dest: Path,
    *,
    max_edge: int,
    fmt: OutputFormat,
    webp_quality: int,
    webp_method: int,
    webp_lossless: bool,
    png_compress_level: int,
    jpeg_quality: int,
    jpeg_background_rgb: tuple[int, int, int] = (248, 248, 248),
) -> None:
    from PIL import Image

    if img.mode != "RGBA":
        img = img.convert("RGBA")
    thumb = img.copy()
    thumb.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "webp":
        save_kw: dict = {
            "format": "WEBP",
            "method": max(0, min(6, int(webp_method))),
        }
        if webp_lossless:
            save_kw["lossless"] = True
        else:
            save_kw["lossless"] = False
            save_kw["quality"] = max(1, min(100, int(webp_quality)))
        thumb.save(dest, **save_kw)
    elif fmt == "png":
        thumb.save(
            dest,
            format="PNG",
            compress_level=max(0, min(9, int(png_compress_level))),
            optimize=True,
        )
    else:
        rgb = Image.new("RGB", thumb.size, jpeg_background_rgb)
        rgb.paste(thumb, mask=thumb.split()[3])
        rgb.save(
            dest,
            format="JPEG",
            quality=max(1, min(95, int(jpeg_quality))),
            optimize=True,
            subsampling=2,
        )


def main() -> int:
    default_root = Path(r"Z:\AOE2\AOE2 Archive Project\Custom Scenarios\Live")
    default_out = _default_minimap_output_dir()

    ap = argparse.ArgumentParser(
        description=(
            "Render scenario minimaps via McMinimap (default: every file under --root). "
            "Default output is WebP with alpha for small files on the web."
        )
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
        help="Render only N randomly chosen files. Default: all matching files (sorted by path).",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed when using -n (ignored when rendering all files).",
    )
    ap.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only scan the root directory, not subfolders.",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=default_out,
        help=f"Output directory (mirrors paths from --root). Default: {default_out}",
    )
    ap.add_argument(
        "--format",
        choices=("webp", "png", "jpeg"),
        default="webp",
        help="Output image type: webp (default, alpha + good compression), png (lossless alpha), jpeg (no alpha).",
    )
    ap.add_argument(
        "--max-edge",
        type=int,
        default=512,
        metavar="PX",
        help=(
            "Thumbnail longest side in pixels (aspect preserved). Default: 512. "
            "For sharp results at high values (e.g. 1024), consider raising --multiplier."
        ),
    )
    ap.add_argument(
        "--multiplier",
        type=int,
        default=3,
        choices=range(1, 11),
        help="McMinimap tile multiplier before thumbnail (lower=faster/less RAM). Default: 3.",
    )
    ap.add_argument(
        "--webp-quality",
        type=int,
        default=80,
        metavar="1-100",
        help="Lossy WebP quality (ignored with --webp-lossless). Default: 80.",
    )
    ap.add_argument(
        "--webp-method",
        type=int,
        default=6,
        choices=range(0, 7),
        help="WebP encoder effort 0-6; higher = smaller files, slower. Default: 6.",
    )
    ap.add_argument(
        "--webp-lossless",
        action="store_true",
        help="Lossless WebP (preserves alpha; often smaller than PNG, larger than lossy WebP).",
    )
    ap.add_argument(
        "--png-level",
        type=int,
        default=9,
        metavar="0-9",
        help="PNG deflate level (9 = smallest PNG). Default: 9.",
    )
    ap.add_argument(
        "--jpeg-quality",
        type=int,
        default=78,
        metavar="1-95",
        help="JPEG quality (--format jpeg only). Default: 78.",
    )
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip if destination image exists and is newer than the scenario file.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Count matching files and exit without rendering.",
    )
    ap.add_argument(
        "--error-log",
        type=Path,
        default=None,
        help="Append failures here (default: <output>/batch_minimap_errors.log).",
    )
    args = ap.parse_args()

    out_fmt: OutputFormat = args.format  # type: ignore[assignment]

    root = args.root.expanduser().resolve()
    out_root = args.output.expanduser().resolve()

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
        print(
            f"No scenario files ({', '.join(sorted(_SCENARIO_SUFFIXES))}) under {root}",
            file=sys.stderr,
        )
        return 1

    if args.count is None:
        files_run = candidates
    else:
        if args.seed is not None:
            random.seed(args.seed)
        k = min(args.count, n_cand)
        files_run = random.sample(candidates, k=k)

    jobs = _build_jobs(root, out_root, files_run, format_name=out_fmt)

    print(f"Corpus root: {root}")
    print(f"Recursive listing: {recursive}")
    print(f"Scenario suffixes: {', '.join(sorted(_SCENARIO_SUFFIXES))}")
    print(f"Candidates matching suffixes: {n_cand}")
    print(f"Random sample limit (-n): {args.count if args.count is not None else '(none - all files)'}")
    print(f"Files to render: {len(jobs)}")
    print(f"Random seed (only if -n): {args.seed!r}")
    print(f"Output directory: {out_root}")
    print(f"Output format: {out_fmt} ({_FORMAT_SUFFIX[out_fmt]})")

    if args.dry_run:
        print("Dry run: no images written.")
        return 0

    _ensure_import_paths()

    try:
        import aoe2_mcminimap as MM  # type: ignore  # noqa: E402
    except ImportError as e:
        print(
            "Cannot import aoe2_mcminimap. Install the released packages with:\n"
            "  pip install --index-url https://test.pypi.org/simple/ "
            "--extra-index-url https://pypi.org/simple/ "
            "AOE2-McMinimap AOE2-McGenieSCX",
            file=sys.stderr,
        )
        print(f"Import error: {e}", file=sys.stderr)
        return 1

    try:
        from AoE2ScenarioParser import settings as asp_settings  # type: ignore  # noqa: E402
    except ImportError:
        asp_settings = None

    if asp_settings is not None:
        asp_settings.PRINT_STATUS_UPDATES = False

    max_edge = max(32, int(args.max_edge))

    mm_settings = MM.MinimapSettings(
        object_mode="square",
        town_center="pixel",
        multiplier_integer=int(args.multiplier),
        final_size=None,
        draw_players=True,
        draw_gaia=True,
        draw_food=True,
        draw_gold=True,
        draw_stone=True,
        draw_relics=True,
        draw_cliffs=True,
        draw_walls=True,
        smooth_walls=True,
    )

    err_log = (
        args.error_log.expanduser().resolve()
        if args.error_log is not None
        else out_root / "batch_minimap_errors.log"
    )

    ok = 0
    skipped = 0
    failures: list[tuple[Path, str]] = []

    def log_failure(src: Path, msg: str) -> None:
        failures.append((src, msg))
        line = f"{datetime.now(timezone.utc).isoformat()}\t{src}\t{msg}\n"
        err_log.parent.mkdir(parents=True, exist_ok=True)
        with err_log.open("a", encoding="utf-8") as lf:
            lf.write(line)

    if out_fmt == "webp":
        enc = "lossless WebP" if args.webp_lossless else f"lossy WebP q={args.webp_quality} method={args.webp_method}"
    elif out_fmt == "png":
        enc = f"PNG level={args.png_level}"
    else:
        enc = f"JPEG q={args.jpeg_quality}"
    print(f"Encode: {enc}; max_edge={max_edge}; multiplier={args.multiplier}")

    for i, (src, dest) in enumerate(jobs, start=1):
        print(f"[{i}/{len(jobs)}] {src.name}", flush=True)

        if args.skip_existing and dest.is_file():
            try:
                if dest.stat().st_mtime >= src.stat().st_mtime:
                    skipped += 1
                    continue
            except OSError:
                pass

        try:
            with MM._apply_settings(mm_settings):
                img = MM.save_minimap(str(src), output_path=None, verbose=False, final_size=None)
            _save_rgba_thumbnail(
                img,
                dest,
                max_edge=max_edge,
                fmt=out_fmt,
                webp_quality=args.webp_quality,
                webp_method=args.webp_method,
                webp_lossless=bool(args.webp_lossless),
                png_compress_level=args.png_level,
                jpeg_quality=args.jpeg_quality,
            )
            ok += 1
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            log_failure(src, msg)
            print(f"FAIL {src.name}: {msg}", file=sys.stderr)

    print("")
    print(
        f"Done: {ok} written, {skipped} skipped, {len(failures)} failed (of {len(jobs)}). "
        f"Failures logged to {err_log}"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
