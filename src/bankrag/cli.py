"""Command line entry point: `bankrag ingest | search | ask | kpi`."""

from __future__ import annotations

import argparse
import sys

from bankrag.answer import answer, log_trace, mark_quotes
from bankrag.config import BANK_NAMES, DISCLAIMER
from bankrag.ingest import load_chunks, run
from bankrag.kpi import KPI_YEARS, METRICS, build_db, compare_banks, extract_table, load_figures, save_figures
from bankrag.models import KpiFigure
from bankrag.retrieve import (
    DEFAULT_RETRIEVER,
    RETRIEVER_KINDS,
    RetrieverKind,
    build_retriever,
    ensure_index,
    routed_search,
)


def ingest(force: bool) -> None:
    """Parse the reports, write the chunks and build the vector index if it is out of date."""
    run(force=force)
    print("vector index rebuilt" if ensure_index(load_chunks("structure")) else "vector index is up to date")


def search(question: str, k: int, retriever: RetrieverKind, route: bool) -> None:
    """Print the chunks retrieved for a question. Needs no API key."""
    hits = routed_search(build_retriever(retriever, load_chunks("structure")), question, k=k, route=route)
    for rank, hit in enumerate(hits, 1):
        chunk = hit.chunk
        print(f"{rank}. {chunk.id}  score {hit.score:.3f}  {chunk.heading or chunk.section}")
        print("   " + chunk.body[:300].replace("\n", "\n   ") + "\n")


def ask(question: str, k: int, retriever: RetrieverKind) -> None:
    """Answer a question with citations, and print its sources, cost and latency."""
    hits = routed_search(build_retriever(retriever, load_chunks("structure")), question, k=k)
    result = answer(question, hits)
    log_trace(result)
    print(mark_quotes(result.text, result.sources, {hit.chunk.id: hit.chunk.body for hit in hits}) + "\n")
    for source in result.sources:
        print(f"[{source.n}] {source.label}  ({source.section})")
    print(
        f"\n{result.model} | {result.input_tokens} in, {result.cache_read_tokens} cached, {result.output_tokens} out"
        f" | USD {result.cost_usd:.5f} (DKK {result.cost_dkk:.4f}) | {result.latency_s:.1f}s",
    )
    print(f"\n{DISCLAIMER}")


def _shown(figure: KpiFigure | None) -> str:
    """Format a figure for the terminal: thousands separators for millions, one decimal otherwise."""
    if figure is None or figure.value is None:
        return "-"
    if figure.unit == "%":
        return f"{figure.value:.1f}%"
    digits = 0 if figure.unit and figure.unit.endswith("million") else 1
    return f"{figure.value:,.{digits}f} {figure.unit}"


def kpi_extract() -> None:
    """Read every figure of the KPI table with Claude and check it, keeping figures already verified by hand."""
    chunks = load_chunks("structure")
    figures, total = [], 0.0
    for figure, cost in extract_table(build_retriever(DEFAULT_RETRIEVER, chunks), chunks, load_figures()):
        figures.append(figure)
        total += cost
        status = "verified" if figure.verified else "; ".join(figure.failed_checks) or "checks passed"
        print(f"{figure.bank:7s} {figure.year} {figure.metric:24s} {_shown(figure):>22s}  p. {figure.page}  {status}")
    save_figures(figures)
    build_db(figures)
    print(f"\n{len(figures)} figures written to kpi/figures.yaml and data/kpi.sqlite. Cost: USD {total:.4f}")


def kpi_show() -> None:
    """Print the KPI table from the database, one row per metric and year, marking figures not yet checked by hand."""
    print(f"{'':30s}" + "".join(f"{name:>24s}" for name in BANK_NAMES.values()))
    for metric in METRICS:
        for year in KPI_YEARS:
            by_bank = {figure.bank: figure for figure in compare_banks(metric, year)}
            cells = []
            for bank in BANK_NAMES:
                figure = by_bank.get(bank)
                mark = "" if figure is None or figure.verified else ("!" if figure.failed_checks else "*")
                cells.append(f"{_shown(figure) + mark:>24s}")
            print(f"{metric + ' ' + str(year):30s}" + "".join(cells))
    print("\n* not yet checked by hand   ! failed an automatic check")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bankrag", description="Questions over Nordic bank annual reports")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest_parser = commands.add_parser("ingest", help="parse the PDFs in data/raw, build chunks and the vector index")
    ingest_parser.add_argument("--force", action="store_true", help="parse again even if pages are cached")

    for name, help_text in [("search", "show the retrieved chunks for a question"), ("ask", "answer with citations")]:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("question")
        command.add_argument("--k", type=int, default=6, help="number of chunks to retrieve")
        command.add_argument("--retriever", default=DEFAULT_RETRIEVER, choices=RETRIEVER_KINDS)
        if name == "search":
            command.add_argument("--no-route", action="store_true", help="ignore banks and years in the question")

    kpi_parser = commands.add_parser("kpi", help="the table of key figures per bank and year")
    kpi_parser.add_argument(
        "action",
        choices=["extract", "build", "show"],
        help="extract: read the figures with Claude (about USD 0.05); build: rebuild data/kpi.sqlite from "
        "kpi/figures.yaml after editing it; show: print the table",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run the chosen command."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a code page without "æøå"
    args = _build_parser().parse_args(argv)
    if args.command == "ingest":
        ingest(force=args.force)
    elif args.command == "search":
        search(args.question, k=args.k, retriever=args.retriever, route=not args.no_route)
    elif args.command == "ask":
        ask(args.question, k=args.k, retriever=args.retriever)
    elif args.action == "extract":
        kpi_extract()
    elif args.action == "build":
        build_db(load_figures())
    else:
        kpi_show()


if __name__ == "__main__":
    main()
