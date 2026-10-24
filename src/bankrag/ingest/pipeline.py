"""Parse every report in data/raw/ and write pages and chunks to data/processed/.

Parsing is the slow step (table detection takes about a second per page), so
parsed pages are cached in pages.jsonl. Chunking reads that cache, which makes
it cheap to try other chunking strategies.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from bankrag.config import PROCESSED_DIR, RAW_DIR
from bankrag.ingest.chunk import Chunk, chunk_pages
from bankrag.ingest.pdf import Page, parse_pdf

PAGES_FILE = PROCESSED_DIR / "pages.jsonl"


def chunks_file(strategy: str) -> Path:
    return PROCESSED_DIR / f"chunks_{strategy}.jsonl"


def _report_files() -> list[tuple[Path, str, int]]:
    out = []
    for path in sorted(RAW_DIR.glob("*.pdf")):
        m = re.fullmatch(r"([a-z]+)_(\d{4})", path.stem)
        if m:
            out.append((path, m.group(1), int(m.group(2))))
    return out


def _parse_one(args: tuple[Path, str, int]) -> list[dict]:
    path, bank, year = args
    return [p.to_dict() for p in parse_pdf(path, bank, year)]


def parse_all(force: bool = False) -> list[Page]:
    reports = _report_files()
    if not reports:
        raise SystemExit(f"No reports in {RAW_DIR}. Run `python scripts/download.py` first.")

    cached: dict[tuple[str, int], list[dict]] = {}
    if PAGES_FILE.exists() and not force:
        for line in PAGES_FILE.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            cached.setdefault((d["bank"], d["year"]), []).append(d)

    todo = [r for r in reports if (r[1], r[2]) not in cached]
    if todo:
        names = ", ".join(p.name for p, _, _ in todo)
        print(f"parsing {len(todo)} report(s): {names}")
        start = time.time()
        with ProcessPoolExecutor(max_workers=len(todo)) as pool:
            for (_, bank, year), pages in zip(todo, pool.map(_parse_one, todo), strict=True):
                cached[(bank, year)] = pages
                print(f"  {bank} {year}: {len(pages)} pages")
        print(f"parsed in {time.time() - start:.0f}s")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    keys = sorted((b, y) for _, b, y in reports)
    with PAGES_FILE.open("w", encoding="utf-8") as f:
        for key in keys:
            for d in cached[key]:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return [Page.from_dict(d) for key in keys for d in cached[key]]


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
