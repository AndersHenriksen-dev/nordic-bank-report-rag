"""Search the parsed report pages for a pattern, to find and check the source page of an eval answer.

Prints every paragraph or table row that matches, with its report and PDF page number. Reads the page cache that
`bankrag ingest` writes, so the text is exactly what the search indexes.

Usage:
    python scripts/find_pages.py "net interest income" --report jyske_2025
    python scripts/find_pages.py "CET1 capital ratio" --report nordea_2024 --pages 38-44
    python scripts/find_pages.py "Common equity tier 1" --report jyske_2025 --pages 34 --whole-page
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from bankrag.ingest.pipeline import PAGES_DIR
from bankrag.models import Block, Page

LINE_WIDTH = 400  # characters of a matching paragraph to print


def _page_range(text: str) -> tuple[int, int]:
    first, _, last = text.partition("-")
    return int(first), int(last or first)


def _read_pages(path: Path) -> list[Page]:
    return [Page.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _matching_lines(block: Block, pattern: re.Pattern[str]) -> list[str]:
    """Return the rows of a table that match, or the start of a matching paragraph."""
    if not pattern.search(block.text):
        return []
    if block.kind == "table":
        return [row for row in block.text.splitlines() if pattern.search(row)]
    return [block.text[:LINE_WIDTH]]


def main() -> int:
    """Print the matches, one line per paragraph or table row."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a code page without "æøå"
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pattern", help="regular expression, matched without regard to case")
    parser.add_argument("--report", default="*", help="cache file name such as jyske_2025 (default: all six)")
    parser.add_argument("--pages", help="PDF page or range, such as 40 or 38-44")
    parser.add_argument("--whole-page", action="store_true", help="print every block of each matching page in order")
    args = parser.parse_args()

    pattern = re.compile(args.pattern, re.IGNORECASE)
    first, last = _page_range(args.pages) if args.pages else (1, sys.maxsize)
    files = sorted(PAGES_DIR.glob(f"{args.report}.jsonl"))
    if not files:
        print(f"No page cache matches {args.report!r} in {PAGES_DIR}. Run `bankrag ingest` first.")
        return 1
    for path in files:
        for page in _read_pages(path):
            if not first <= page.page <= last:
                continue
            where = f"{path.stem} p{page.page} [{page.section}]"
            if args.whole_page:
                if any(pattern.search(block.text) for block in page.blocks):
                    print(f"== {where}\n" + "\n".join(block.text for block in page.blocks))
                continue
            for block in page.blocks:
                for line in _matching_lines(block, pattern):
                    print(f"{where} {block.kind}: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
