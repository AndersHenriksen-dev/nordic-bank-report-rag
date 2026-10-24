"""Command line entry point: `bankrag ingest | search | ask`."""

from __future__ import annotations

import argparse
import sys

DISCLAIMER = (
    "Built on public annual reports for demonstration. Not investment advice. "
    "Figures should be checked against the source page."
)


def _retriever(strategy: str):
    from bankrag.ingest.pipeline import load_chunks
    from bankrag.retrieve.bm25 import BM25Retriever

    return BM25Retriever(load_chunks(strategy))


def cmd_ingest(args: argparse.Namespace) -> None:
    from bankrag.ingest.pipeline import run

    run(force=args.force)


def cmd_search(args: argparse.Namespace) -> None:
    from bankrag.retrieve.route import routed_search

    hits = routed_search(_retriever(args.strategy), args.question, k=args.k, route=not args.no_route)
    for i, h in enumerate(hits, 1):
        c = h.chunk
        print(f"{i}. {c.id}  score {h.score:.2f}  {c.heading or c.section}")
        print("   " + c.body[:300].replace("\n", "\n   ") + "\n")


def cmd_ask(args: argparse.Namespace) -> None:
    from bankrag.answer.generate import answer, log_trace
    from bankrag.retrieve.route import routed_search

    hits = routed_search(_retriever(args.strategy), args.question, k=args.k)
    ans = answer(args.question, hits)
    log_trace(ans)
    print(ans.text + "\n")
    for s in ans.sources:
        print(f"[{s.n}] {s.label}  ({s.section})")
    print(
        f"\n{ans.model} | {ans.input_tokens} in, {ans.cache_read_tokens} cached, {ans.output_tokens} out"
        f" | USD {ans.cost_usd:.5f} (DKK {ans.cost_dkk:.4f}) | {ans.latency_s:.1f}s"
    )
    print(f"\n{DISCLAIMER}")


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="bankrag", description="Questions over Nordic bank annual reports")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("ingest", help="parse the PDFs in data/raw and build chunks")
    p.add_argument("--force", action="store_true", help="parse again even if pages are cached")
    p.set_defaults(func=cmd_ingest)

    for name, func, help_text in [
        ("search", cmd_search, "show the retrieved chunks for a question"),
        ("ask", cmd_ask, "answer a question with citations"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("question")
        p.add_argument("--k", type=int, default=6, help="number of chunks to retrieve")
        p.add_argument("--strategy", default="structure", choices=["structure", "fixed"])
        if name == "search":
            p.add_argument("--no-route", action="store_true", help="ignore banks and years in the question")
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
