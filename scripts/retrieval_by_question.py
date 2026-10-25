"""Show, question by question, what the search found: recall, the evidence groups it missed, and the pages it ranked.

The eval runner reports averages; this shows which questions are behind them. Pages that are not in a question's gold
lists are marked with *, so each can be checked in the page text (scripts/find_pages.py) before a gold list changes.
Free: it runs the search only, no API calls.

Usage:
    python scripts/retrieval_by_question.py                   # every answerable question, default search, k=6
    python scripts/retrieval_by_question.py --ids q01,q12 --k 10
    python scripts/retrieval_by_question.py --misses           # only questions with recall below 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bankrag.evaluate import load_questions, page_key, retrieval_scores
from bankrag.ingest import load_chunks
from bankrag.models import Question
from bankrag.retrieve import DEFAULT_RETRIEVER, RETRIEVER_KINDS, Retriever, build_retriever, routed_search

QUESTIONS_FILE = Path(__file__).resolve().parent.parent / "evals" / "questions.yaml"


def _report(question: Question, retriever: Retriever, k: int) -> tuple[float, str]:
    hits = routed_search(retriever, question.question, k=k)
    pages = list(dict.fromkeys(page_key(hit.chunk) for hit in hits))
    recall = retrieval_scores(question, [page_key(hit.chunk) for hit in hits], k)[0]
    gold = {page for group in question.evidence for page in group}
    missed = [" or ".join(group) for group in question.evidence if not any(page in pages for page in group)]
    ranked = " ".join(page if page in gold else page + "*" for page in pages)
    lines = [f"{question.id} recall@{k} {recall:.2f}  {question.question}", f"    ranked: {ranked}"]
    if missed:
        lines.append(f"    missed: {'; '.join(missed)}")
    return recall, "\n".join(lines)


def main() -> int:
    """Print one block per question."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a code page without "æøå"
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ids", help="comma-separated question ids, such as q01,q12")
    parser.add_argument("--k", type=int, default=6, help="passages per question, as the answer model gets them")
    parser.add_argument("--retriever", default=DEFAULT_RETRIEVER, choices=RETRIEVER_KINDS)
    parser.add_argument("--misses", action="store_true", help="only show questions with recall below 1")
    args = parser.parse_args()

    wanted = set(args.ids.split(",")) if args.ids else None
    questions = [q for q in load_questions(QUESTIONS_FILE) if q.answerable and (wanted is None or q.id in wanted)]
    retriever = build_retriever(args.retriever, load_chunks("structure"))
    for question in questions:
        recall, block = _report(question, retriever, args.k)
        if recall < 1 or not args.misses:
            print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
