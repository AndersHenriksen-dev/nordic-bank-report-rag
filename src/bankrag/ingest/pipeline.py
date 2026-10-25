"""Parse every report in data/raw/ and write pages and chunks to data/processed/.

Parsing is the slow step (table detection takes about a second per page), so parsed pages are cached per report in
data/processed/pages/ and chunking reads that cache. Each report is parsed in its own child process (see worker.py),
because PyMuPDF's layout model crashes the process on a few pages; the child is then restarted at the crashing page
with the layout model switched off for that page only.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

from pydantic import ValidationError

from bankrag.config import PROCESSED_DIR, RAW_DIR, Bank, parse_bank
from bankrag.ingest.chunk import STRATEGIES, ChunkStrategy, chunk_pages
from bankrag.ingest.pdf import fill_sections
from bankrag.models import Chunk, Page

PAGES_DIR = PROCESSED_DIR / "pages"
PARALLEL_REPORTS = 3
REPORT_NAME_RE = re.compile(r"([a-z]+)_(\d{4})")


class ReportFile(NamedTuple):
    """A downloaded report PDF and the bank and year its file name names."""

    path: Path
    bank: Bank
    year: int


def chunks_file(strategy: ChunkStrategy) -> Path:
    """Return the path of the chunk file for a chunking strategy."""
    return PROCESSED_DIR / f"chunks_{strategy}.jsonl"


def _find_reports() -> list[ReportFile]:
    reports = []
    for path in sorted(RAW_DIR.glob("*.pdf")):
        match = REPORT_NAME_RE.fullmatch(path.stem)
        if match:
            reports.append(ReportFile(path, parse_bank(match.group(1)), int(match.group(2))))
    return reports


def _read_pages(path: Path) -> list[Page]:
    """Read a page cache file, stopping at a line cut off by a crash (that page is parsed again)."""
    if not path.exists():
        return []
    pages = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            pages.append(Page.model_validate_json(line))
        except ValidationError:
            break
    return pages


def _write_pages(path: Path, pages: list[Page]) -> None:
    path.write_text("".join(page.model_dump_json() + "\n" for page in pages), encoding="utf-8")


def _run_worker(report: ReportFile, out: Path, start: int, no_layout: set[int]) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "bankrag.ingest.worker", str(report.path), report.bank, str(report.year)]
    command += [str(out), "--start", str(start), "--no-layout", ",".join(map(str, sorted(no_layout)))]
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)


def _parse_report(report: ReportFile) -> str:
    """Parse one report into PAGES_DIR/<name>.jsonl, restarting after crashes.

    Returns:
        A one-line summary, including any pages that needed the fallback.

    Raises:
        RuntimeError: If the worker fails with a Python error, which a restart would not fix.
    """
    partial = PAGES_DIR / f"{report.path.stem}.partial.jsonl"
    no_layout: set[int] = set()  # crashed once: parse again without the layout model
    broken: set[int] = set()  # crashed without the layout model too: keep as an empty page
    while True:
        done = _read_pages(partial)
        start = done[-1].page + 1 if done else 1
        if start in broken:
            done.append(Page(bank=report.bank, year=report.year, page=start, section="", heading=""))
            start += 1
        _write_pages(partial, done)  # drops a line cut off by the last crash before appending to the file
        result = _run_worker(report, partial, start, no_layout)
        if result.returncode == 0:
            break
        if "Traceback (most recent call last)" in result.stderr:
            raise RuntimeError(f"parsing {report.path.name} failed:\n{result.stderr}")
        done = _read_pages(partial)
        crashed = done[-1].page + 1 if done else 1
        (broken if crashed in no_layout else no_layout).add(crashed)

    final = PAGES_DIR / f"{report.path.stem}.jsonl"
    partial.replace(final)
    notes = ""
    if no_layout:
        notes += f", layout model skipped on page(s) {sorted(no_layout)}"
    if broken:
        notes += f", page(s) {sorted(broken)} left empty"
    return f"{report.bank} {report.year}: {len(_read_pages(final))} pages{notes}"


def _parse_all(force: bool) -> list[Page]:
    reports = _find_reports()
    if not reports:
        raise SystemExit(f"No reports in {RAW_DIR}. Run `python scripts/download.py` first.")
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    if force:
        for cache_file in PAGES_DIR.glob("*.jsonl"):
            cache_file.unlink()

    todo = [report for report in reports if not (PAGES_DIR / f"{report.path.stem}.jsonl").exists()]
    if todo:
        print(f"parsing {len(todo)} report(s): {', '.join(report.path.name for report in todo)}")
        start = time.time()
        with ThreadPoolExecutor(max_workers=PARALLEL_REPORTS) as pool:
            for summary in pool.map(_parse_report, todo):
                print(f"  {summary}")
        print(f"parsed in {time.time() - start:.0f}s")

    pages: list[Page] = []
    for report in reports:
        pages.extend(fill_sections(_read_pages(PAGES_DIR / f"{report.path.stem}.jsonl")))
    return pages


def load_chunks(strategy: ChunkStrategy) -> list[Chunk]:
    """Load the chunks written by the last ingest run.

    Raises:
        SystemExit: If the chunk file does not exist yet.
    """
    path = chunks_file(strategy)
    if not path.exists():
        raise SystemExit(f"{path} is missing. Run `bankrag ingest` first.")
    return [Chunk.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines()]


def run(force: bool) -> None:
    """Parse all reports (reusing cached pages unless `force`) and write the chunks for every strategy."""
    pages = _parse_all(force)
    for strategy in STRATEGIES:
        chunks = chunk_pages(pages, strategy)
        chunks_file(strategy).write_text("".join(chunk.model_dump_json() + "\n" for chunk in chunks), encoding="utf-8")
        with_tables = sum(chunk.has_table for chunk in chunks)
        print(f"{strategy}: {len(chunks)} chunks ({with_tables} with tables) -> {chunks_file(strategy)}")
