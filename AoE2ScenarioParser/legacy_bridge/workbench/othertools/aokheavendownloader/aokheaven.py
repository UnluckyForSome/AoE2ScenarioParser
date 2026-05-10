"""
Download files from Age of Kings Heaven — The Blacksmith (aok.heavengames.com).

The site uses JavaScript `get_file(fileid, signature)`; the real URL is:

  /blacksmith/getfile.php?id=<fileid>&dd=1&s=<signature>

Direct `showfile.php?...#` links are in-page anchors only; they do not point at the
archive. This script mirrors what a browser does: read `lister.php` rows (class
`filelist-table`) for `onclick="get_file(...)"`, then GET `getfile.php` with `dd=1`
for the binary.

After each download, archives are extracted and only AoE2 scenario-related file
types are copied into ``extracted/``; other members are discarded.

Completed downloads are recorded under ``downloads/_state/completed_downloads.json``
so re-runs skip re-fetching unless ``--force-download`` is used.

Respect the site: use modest delays, do not re-host or hotlink; for terms see the
site footer. Use only for personal backup or research you are allowed to do.
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

# Longest suffix first so e.g. *.scx2 matches before *.scx.
ALLOWED_EXTENSIONS: tuple[str, ...] = (
    ".aoe2scenario",
    ".aoe2campaign",
    ".scx2",
    ".scn2",
    ".cpn2",
    ".cpx2",
    ".scx",
    ".scn",
    ".cpn",
    ".cpx",
)

DEFAULT_ORIGIN = "https://aok.heavengames.com"
USER_AGENT = (
    "Mozilla/5.0 (compatible; AoKBlacksmithBulk/1.0; +local archival script)"
)

# Matches both lister onclick styles (quoted vs unquoted fileid appears on showfile).
_RE_GET_FILE = re.compile(
    r"get_file\s*\(\s*'?(\d+)'?\s*,\s*'([a-f0-9]+)'\s*\)",
    re.I,
)
_RE_FOUND_COUNT = re.compile(
    r"Found\s*<b>\s*(\d+)\s*</b>\s*files", re.I
)
_RE_ONCLICK_ROW = re.compile(
    r'onclick="get_file\((\d+),\s*\'([a-f0-9]+)\'\)\s*;\s*return false;"'
)
_RE_LISTER_TITLE = re.compile(
    r'<a title="Click for more information" href="showfile\.php\?fileid=\d+">'
    r"([^<]+)</a>"
)


def _request(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("latin-1", "replace")


def _read_body_bytes(url: str) -> tuple[bytes, str | None]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
        ct = r.headers.get("Content-Type")
        return data, ct


def filelist_table_html(page_html: str) -> str:
    i = page_html.find("filelist-table")
    if i < 0:
        return ""
    j = page_html.find("</table>", i)
    if j < 0:
        return page_html[i:]
    return page_html[i : j + 8]


def parse_lister_page(
    lister_html: str,
) -> list[tuple[str, str, str]]:
    """
    Return list of (fileid, signature_hex, title) from the main listing table.
    """
    table = filelist_table_html(lister_html)
    if not table:
        return []
    rows = _RE_ONCLICK_ROW.findall(table)
    titles = _RE_LISTER_TITLE.findall(table)
    out: list[tuple[str, str, str]] = []
    if len(rows) == len(titles):
        for (fid, sig), title in zip(rows, titles):
            out.append((fid, sig, title.strip()))
    else:
        for fid, sig in rows:
            out.append((fid, sig, ""))
    return out


def parse_total_files(lister_html: str) -> int | None:
    m = _RE_FOUND_COUNT.search(lister_html)
    if m:
        return int(m.group(1))
    return None


def parse_showfile_page(html: str) -> tuple[str | None, str | None, str | None]:
    """Return (fileid, signature, title) from a showfile.php HTML page."""
    m = _RE_GET_FILE.search(html)
    fid = m.group(1) if m else None
    sig = m.group(2) if m else None
    tm = re.search(r'<h1 class="filetitle">\s*([^<]+)\s*</h1>', html, re.I)
    title = tm.group(1).strip() if tm else None
    return fid, sig, title


def download_url(origin: str, fileid: str, signature: str) -> str:
    base = origin.rstrip("/")
    return (
        f"{base}/blacksmith/getfile.php?"
        f"id={urllib.parse.quote(fileid)}&dd=1&s={urllib.parse.quote(signature)}"
    )


def safe_filename(title: str, fileid: str) -> str:
    raw = title.strip() if title else f"file_{fileid}"
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", raw)
    cleaned = cleaned.strip(" .") or f"file_{fileid}"
    if len(cleaned) > 180:
        cleaned = cleaned[:180].rstrip()
    return f"{cleaned}_{fileid}"


def guess_extension(body: bytes, content_type: str | None) -> str:
    if body.startswith(b"PK\x03\x04"):
        return ".zip"
    if body.startswith(b"Rar!"):
        return ".rar"
    if body.startswith(b"\x37\x7a\xbc\xaf\x27\x1c"):
        return ".7z"
    ct = (content_type or "").lower()
    if "zip" in ct:
        return ".zip"
    if "x-rar" in ct or "rar" in ct:
        return ".rar"
    return ".bin"


def _matches_allowed_scenario_file(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(ext) for ext in ALLOWED_EXTENSIONS)


def _find_7z_executable() -> str | None:
    exe = shutil.which("7z")
    if exe:
        return exe
    if sys.platform == "win32":
        candidate = Path(r"C:\Program Files\7-Zip\7z.exe")
        if candidate.is_file():
            return str(candidate)
    return None


def _safe_extract_zip(zip_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    root = dest_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.filename.endswith("/"):
                continue
            out_path = (root / info.filename).resolve()
            try:
                out_path.relative_to(root)
            except ValueError:
                continue
            if info.is_dir():
                out_path.mkdir(parents=True, exist_ok=True)
            else:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, open(out_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)


def _extract_with_7z(archive_path: Path, dest_dir: Path) -> bool:
    seven = _find_7z_executable()
    if not seven:
        return False
    dest_dir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [seven, "x", "-y", f"-o{dest_dir}", str(archive_path)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    return r.returncode == 0


def extract_archive_to(archive_path: Path, dest_dir: Path) -> bool:
    """
    Extract `archive_path` into `dest_dir`. Returns True on success.
    Uses zipfile for ZIP; optionally 7-Zip for ZIP/RAR/7z if installed.
    """
    head = archive_path.read_bytes()[:8]
    if head.startswith(b"PK"):
        try:
            _safe_extract_zip(archive_path, dest_dir)
            return True
        except zipfile.BadZipFile:
            pass
        if _extract_with_7z(archive_path, dest_dir):
            return True
        print(f"  extract: bad ZIP and no usable 7-Zip: {archive_path.name}", file=sys.stderr)
        return False

    if _extract_with_7z(archive_path, dest_dir):
        return True

    print(
        f"  extract: unsupported or corrupt archive (install 7-Zip for RAR/7z): "
        f"{archive_path.name}",
        file=sys.stderr,
    )
    return False


def _safe_flat_name(fileid: str, relative: str) -> str:
    flat = relative.replace("\\", "_").replace("/", "_").strip("_")
    flat = re.sub(r'[<>:"|?*]', "_", flat)
    return f"{fileid}_{flat}" if flat else f"{fileid}_file"


def copy_allowed_files_into_extracted(
    unpacked_root: Path,
    extracted_dir: Path,
    fileid: str,
) -> int:
    """
    Copy allowed scenario files from `unpacked_root` into `extracted_dir`.
    Returns number of files copied.
    """
    extracted_dir.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    n = 0
    for p in unpacked_root.rglob("*"):
        if not p.is_file() or not _matches_allowed_scenario_file(p):
            continue
        try:
            rel = str(p.relative_to(unpacked_root))
        except ValueError:
            rel = p.name
        base_name = _safe_flat_name(fileid, rel)
        dest_name = base_name
        if dest_name in used:
            stem = Path(base_name).stem
            suf = Path(base_name).suffix
            i = 2
            while True:
                cand = f"{stem}_{i}{suf}"
                if cand not in used:
                    dest_name = cand
                    break
                i += 1
        used.add(dest_name)
        dest = extracted_dir / dest_name
        shutil.copy2(p, dest)
        n += 1
    return n


def extract_and_collect_scenarios(
    archive_path: Path,
    extracted_dir: Path,
    marker_dir: Path,
    fileid: str,
) -> None:
    """
    Unpack archive to a temp dir, copy allowed extensions into ``extracted_dir``,
    then write ``marker_dir / fileid`` after a successful unpack (even if 0 matches).
    """
    marker = marker_dir / fileid
    if marker.exists():
        return
    if not archive_path.is_file():
        return

    with tempfile.TemporaryDirectory(prefix="aokh_extract_") as tmp:
        tmp_path = Path(tmp)
        if not extract_archive_to(archive_path, tmp_path):
            return
        n = copy_allowed_files_into_extracted(tmp_path, extracted_dir, fileid)
        print(f"  extracted {n} scenario file(s) -> {extracted_dir}", file=sys.stderr)

    marker_dir.mkdir(parents=True, exist_ok=True)
    try:
        marker.touch()
    except OSError as e:
        print(f"  warning: could not write marker {marker}: {e}", file=sys.stderr)


def default_extracted_dir() -> Path:
    return Path(__file__).resolve().parent / "extracted"


def default_downloads_dir() -> Path:
    return Path(__file__).resolve().parent / "downloads"


def download_state_path(out_dir: Path) -> Path:
    return out_dir / "_state" / "completed_downloads.json"


def load_download_state(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, dict):
            out[k] = v
    return out


def save_download_state(path: Path, state: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(state, indent=2, sort_keys=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data + "\n", encoding="utf-8")
    tmp.replace(path)


def record_completed_download(
    state_path: Path,
    state: dict[str, dict[str, Any]],
    fileid: str,
    signature: str,
    archive_path: Path,
    size: int,
) -> None:
    state[fileid] = {
        "signature": signature,
        "archive": archive_path.name,
        "bytes": size,
    }
    save_download_state(state_path, state)


def resolve_archive_path(
    out_dir: Path,
    name_base: str,
    fileid: str,
    state: dict[str, dict[str, Any]],
) -> Path | None:
    ent = state.get(fileid)
    if isinstance(ent, dict):
        name = ent.get("archive")
        if isinstance(name, str):
            p = out_dir / name
            if p.is_file():
                return p
    found = list(out_dir.glob(re.escape(name_base) + ".*"))
    return found[0] if found else None


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    p = argparse.ArgumentParser(description="Bulk-download Blacksmith files.")
    p.add_argument(
        "--origin",
        default=DEFAULT_ORIGIN,
        help="Site origin (default: AoK Heaven)",
    )
    p.add_argument(
        "--category",
        default="single",
        help="lister.php category= value (default: single)",
    )
    p.add_argument(
        "--page-size",
        type=int,
        default=20,
        help="Files per lister page (observed 20)",
    )
    p.add_argument(
        "--start-offset",
        type=int,
        default=0,
        help="First lister start= offset (pagination)",
    )
    p.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Stop after this many downloads (0 = no limit)",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Seconds between HTTP requests",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Directory for downloaded archives (default: script_dir/downloads)",
    )
    p.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download even if this fileid is already recorded in _state/",
    )
    p.add_argument(
        "--extract-to",
        type=Path,
        default=None,
        help="Copy matching scenario files here (default: script_dir/extracted)",
    )
    p.add_argument(
        "--no-extract",
        action="store_true",
        help="Do not unpack archives or copy scenario files",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print URLs only; do not download",
    )
    p.add_argument(
        "--showfile",
        metavar="FILEID",
        help="Download one file by showfile.php fileid (skip lister)",
    )
    args = p.parse_args(argv)

    origin = args.origin.rstrip("/")
    out_dir: Path = args.out if args.out is not None else default_downloads_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    dl_state_path = download_state_path(out_dir)
    download_state = load_download_state(dl_state_path)

    extracted_dir = (
        args.extract_to if args.extract_to is not None else default_extracted_dir()
    )
    marker_dir = extracted_dir / "_extract_done"
    do_extract = not args.no_extract

    def sleep() -> None:
        if args.delay > 0:
            time.sleep(args.delay)

    if args.showfile:
        url = f"{origin}/blacksmith/showfile.php?fileid={args.showfile}"
        print(f"Fetching {url}", file=sys.stderr)
        html = _request(url)
        fid, sig, title = parse_showfile_page(html)
        if not fid or not sig:
            print(
                "Could not find get_file(fileid, signature) on showfile page.",
                file=sys.stderr,
            )
            return 1
        dl = download_url(origin, fid, sig)
        name_base = safe_filename(title or "", fid)
        print(dl)
        if args.dry_run:
            return 0
        path = resolve_archive_path(out_dir, name_base, fid, download_state)
        skip_get = False

        if not args.force_download:
            if path and path.is_file() and fid in download_state:
                print(
                    f"Skip download (recorded in _state): {path.name}",
                    file=sys.stderr,
                )
                skip_get = True
            elif path and path.is_file():
                print(
                    f"Skip download (archive exists): {path.name}",
                    file=sys.stderr,
                )
                skip_get = True
                if fid not in download_state:
                    record_completed_download(
                        dl_state_path,
                        download_state,
                        fid,
                        sig,
                        path,
                        path.stat().st_size,
                    )
            elif fid in download_state:
                print(
                    "Skip download (recorded in _state but archive file "
                    f"missing: {download_state[fid].get('archive')}; "
                    "use --force-download to re-fetch)",
                    file=sys.stderr,
                )
                skip_get = True
                path = None

        if not skip_get:
            sleep()
            body, ct = _read_body_bytes(dl)
            ext = guess_extension(body, ct)
            path = out_dir / f"{name_base}{ext}"
            path.write_bytes(body)
            record_completed_download(
                dl_state_path,
                download_state,
                fid,
                sig,
                path,
                len(body),
            )
            print(f"Wrote {path} ({len(body)} bytes)")
        if do_extract and path is not None and path.is_file():
            extracted_dir.mkdir(parents=True, exist_ok=True)
            extract_and_collect_scenarios(path, extracted_dir, marker_dir, fid)
        return 0

    seen: set[tuple[str, str]] = set()
    downloaded = 0
    dry_printed = 0
    start = args.start_offset

    while True:
        lister_url = (
            f"{origin}/blacksmith/lister.php?"
            f"category={urllib.parse.quote(args.category)}&start={start}"
        )
        print(f"Listing {lister_url}", file=sys.stderr)
        sleep()
        try:
            page_html = _request(lister_url)
        except urllib.error.HTTPError as e:
            print(f"HTTP error on lister: {e}", file=sys.stderr)
            return 1

        rows = parse_lister_page(page_html)
        if not rows:
            total = parse_total_files(page_html)
            print(
                f"No rows at start={start} (total announced: {total}). Done.",
                file=sys.stderr,
            )
            break

        if start == args.start_offset:
            total = parse_total_files(page_html)
            if total is not None:
                print(
                    f"Category lists about {total} files (~{(total + args.page_size - 1) // args.page_size} pages).",
                    file=sys.stderr,
                )

        for fileid, sig, title in rows:
            key = (fileid, sig)
            if key in seen:
                continue
            seen.add(key)

            dl = download_url(origin, fileid, sig)
            name_base = safe_filename(title, fileid)
            if args.dry_run:
                print(f"{dl}\t{name_base}")
                dry_printed += 1
                if args.max_files and dry_printed >= args.max_files:
                    print(
                        f"Stopped after --max-files={args.max_files} (dry-run).",
                        file=sys.stderr,
                    )
                    return 0
            else:
                path = resolve_archive_path(
                    out_dir, name_base, fileid, download_state
                )
                skip_get = False

                if not args.force_download:
                    if path and path.is_file() and fileid in download_state:
                        print(
                            f"Skip download (recorded in _state): {path.name}",
                            file=sys.stderr,
                        )
                        skip_get = True
                    elif path and path.is_file():
                        print(
                            f"Skip download (archive exists): {path.name}",
                            file=sys.stderr,
                        )
                        skip_get = True
                        if fileid not in download_state:
                            record_completed_download(
                                dl_state_path,
                                download_state,
                                fileid,
                                sig,
                                path,
                                path.stat().st_size,
                            )
                    elif fileid in download_state:
                        print(
                            "Skip download (recorded in _state but archive file "
                            f"missing: {download_state[fileid].get('archive')}; "
                            "use --force-download to re-fetch)",
                            file=sys.stderr,
                        )
                        skip_get = True
                        path = None

                if not skip_get:
                    print(f"GET {dl}", file=sys.stderr)
                    sleep()
                    try:
                        body, ct = _read_body_bytes(dl)
                    except urllib.error.HTTPError as e:
                        print(f"  failed: {e}", file=sys.stderr)
                        continue
                    ext = guess_extension(body, ct)
                    path = out_dir / f"{name_base}{ext}"
                    path.write_bytes(body)
                    record_completed_download(
                        dl_state_path,
                        download_state,
                        fileid,
                        sig,
                        path,
                        len(body),
                    )
                    downloaded += 1
                    print(f"  -> {path.name} ({len(body)} bytes)", file=sys.stderr)
                    if args.max_files and downloaded >= args.max_files:
                        print("Reached --max-files.", file=sys.stderr)
                        if do_extract and path.is_file():
                            extracted_dir.mkdir(parents=True, exist_ok=True)
                            extract_and_collect_scenarios(
                                path, extracted_dir, marker_dir, fileid
                            )
                        return 0

                if do_extract and path is not None and path.is_file():
                    extracted_dir.mkdir(parents=True, exist_ok=True)
                    extract_and_collect_scenarios(
                        path, extracted_dir, marker_dir, fileid
                    )

        start += args.page_size

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
