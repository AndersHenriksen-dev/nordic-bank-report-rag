"""Parse one report in its own process, writing each page as soon as it is done.

Run by the pipeline, not by hand:
    python -m bankrag.ingest.worker PDF BANK YEAR OUT [--start N] [--no-layout 3,17]

If PyMuPDF crashes the process, every page before the crash is already on disk,
so the pipeline can restart from the page that crashed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bankrag.ingest.pdf import iter_pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("bank")
    parser.add_argument("year", type=int)
    parser.add_argument("out", type=Path)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--no-layout", default="")
    args = parser.parse_args()

    no_layout = frozenset(int(p) for p in args.no_layout.split(",") if p)
    with args.out.open("a", encoding="utf-8") as f:
        for page in iter_pages(args.pdf, args.bank, args.year, args.start, no_layout):
            f.write(json.dumps(page.to_dict(), ensure_ascii=False) + "\n")
            f.flush()


if __name__ == "__main__":
    main()
