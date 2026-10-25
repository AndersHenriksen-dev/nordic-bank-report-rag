"""Command line entry point: `bankrag ingest | search | ask`."""

from __future__ import annotations

import argparse
import sys

from bankrag.answer import answer, log_trace
from bankrag.config import DISCLAIMER
from bankrag.ingest import load_chunks, run
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
    print(result.text + "\n")
    for source in result.sources:
        print(f"[{source.n}] {source.label}  ({source.section})")
    print(
        f"\n{result.model} | {result.input_tokens} in, {result.cache_read_tokens} cached, {result.output_tokens} out"
        f" | USD {result.cost_usd:.5f} (DKK {result.cost_dkk:.4f}) | {result.latency_s:.1f}s",
    )
    print(f"\n{DISCLAIMER}")


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
    else:
        ask(args.question, k=args.k, retriever=args.retriever)


if __name__ == "__main__":
    main()
