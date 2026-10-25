"""Parse every report in data/raw/ and write pages and chunks to data/processed/.

Parsing is the slow step (table detection takes about a second per page), so
parsed pages are cached per report in data/processed/pages/. Chunking reads that
cache, which makes it cheap to try other chunking strategies.

Each report is parsed in its own child process (see worker.py), because
PyMuPDF's layout model crashes the process on a few pages. When that happens
the child is restarted at the crashing page, with the layout model switched off
for that page only.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bankrag.config import PROCESSED_DIR, RAW_DIR
from bankrag.ingest.chunk import Chunk, chunk_pages
from bankrag.ingest.pdf import Page, fill_sections

PAGES_DIR = PROCESSED_DIR / "pages"
PARALLEL_REPORTS = 3


def chunks_file(strategy: str) -> Path:
    return PROCESSED_DIR / f"chunks_{strategy}.jsonl"


def _report_files() -> list[tuple[Path, str, int]]:
    out = []
    for path in sorted(RAW_DIR.glob("*.pdf")):
        m = re.fullmatch(r"([a-z]+)_(\d{4})", path.stem)
        if m:
            out.append((path, m.group(1), int(m.group(2))))
    return out


def _read_pages(path: Path) -> list[dict]:
    if not path.exists():
        return []
    pages = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            pages.append(json.loads(line))
        except json.JSONDecodeError:
            break  # a line cut off by a crash; the page is parsed again
    return pages


def _parse_report(pdf: Path, bank: str, year: int) -> str:
    """Parse one report into PAGES_DIR/<name>.jsonl, restarting after crashes."""
    partial = PAGES_DIR / f"{pdf.stem}.partial.jsonl"
    no_layout: set[int] = set()  # crashed once: parse again without the layout model
    broken: set[int] = set()  # crashed without the layout model too: keep as an empty page
    while True:
        done = _read_pages(partial)
        start = done[-1]["page"] + 1 if done else 1
        if start in broken:
            done.append(Page(bank=bank, year=year, page=start, section="", heading="").to_dict())
            start += 1
        # Rewrite without any cut-off last line before appending to it.
        partial.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in done), encoding="utf-8")
        cmd = [sys.executable, "-m", "bankrag.ingest.worker", str(pdf), bank, str(year), str(partial)]
        cmd += ["--start", str(start), "--no-layout", ",".join(map(str, sorted(no_layout)))]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode == 0:
            break
        if "Traceback (most recent call last)" in result.stderr:
            # A Python error, not a native crash: restarting would not help.
            raise RuntimeError(f"parsing {pdf.name} failed:\n{result.stderr}")
        done = _read_pages(partial)
        crashed = done[-1]["page"] + 1 if done else 1
        (broken if crashed in no_layout else no_layout).add(crashed)

    final = PAGES_DIR / f"{pdf.stem}.jsonl"
    partial.replace(final)
    notes = ""
    if no_layout:
        notes += f", layout model skipped on page(s) {sorted(no_layout)}"
    if broken:
        notes += f", page(s) {sorted(broken)} left empty"
    return f"{bank} {year}: {len(_read_pages(final))} pages{notes}"


def parse_all(force: bool = False) -> list[Page]:
    reports = _report_files()
    if not reports:
        raise SystemExit(f"No reports in {RAW_DIR}. Run `python scripts/download.py` first.")
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    if force:
        for f in PAGES_DIR.glob("*.jsonl"):
            f.unlink()

    todo = [r for r in reports if not (PAGES_DIR / f"{r[0].stem}.jsonl").exists()]
    if todo:
        print(f"parsing {len(todo)} report(s): {', '.join(p.name for p, _, _ in todo)}")
        start = time.time()
        with ThreadPoolExecutor(max_workers=PARALLEL_REPORTS) as pool:
            for line in pool.map(lambda r: _parse_report(*r), todo):
                print(f"  {line}")
        print(f"parsed in {time.time() - start:.0f}s")

    pages: list[Page] = []
    for pdf, _, _ in reports:
        report_pages = [Page.from_dict(d) for d in _read_pages(PAGES_DIR / f"{pdf.stem}.jsonl")]
        pages.extend(fill_sections(report_pages))
    return pages


def load_chunks(strategy: str = "structure") -> list[Chunk]:
    path = chunks_file(strategy)
    if not path.exists():
        raise SystemExit(f"{path} is missing. Run `bankrag ingest` first.")
    return [Chunk(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]


def run(strategies: tuple[str, ...] = ("structure", "fixed"), force: bool = False) -> None:
    pages = parse_all(force=force)
    for strategy in strategies:
        chunks = chunk_pages(pages, strategy)
        with chunks_file(strategy).open("w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")
        tables = sum(c.has_table for c in chunks)
        print(f"{strategy}: {len(chunks)} chunks ({tables} with tables) -> {chunks_file(strategy)}")
