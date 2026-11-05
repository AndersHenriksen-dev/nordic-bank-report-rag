"""Check what Claude is sent for each eval question, without the reports or the models; exit 1 if it got worse.

The full evals need the twelve parsed reports and two 2.3 GB models, which CI does not have. The fixture holds every
chunk on a gold page, plus the chunks that routed BM25 search ranks highest for each question over the full index, so
each question meets the same competing passages as in the full index. CI searches it with BM25, routing and the
Danish glossary, and compares recall@k and MRR with the committed baseline. It also checks that every question gets
exactly the KPI table rows its `key_figures` list. Free: no API calls, no models.

python evals/check_retrieval.py            # compare with the baseline
python evals/check_retrieval.py --update   # accept the current scores as the baseline, after a deliberate change
python evals/check_retrieval.py --rebuild  # rebuild the fixture from data/processed/ and the baseline, after an
                                           # ingest or a change to the eval questions or their gold pages
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from pydantic import BaseModel

from bankrag.evaluate import K_VALUES, load_questions, page_key, score_retrieval
from bankrag.ingest.pipeline import load_chunks
from bankrag.kpi.lookup import figure_key, key_figures_for
from bankrag.models import Chunk, Question, RetrievalScores
from bankrag.retrieve.bm25 import BM25Retriever
from bankrag.retrieve.route import routed_search

EVAL_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = EVAL_DIR / "fixture"
CHUNKS_FILE = FIXTURE_DIR / "chunks.jsonl"
BASELINE_FILE = FIXTURE_DIR / "baseline.json"
DISTRACTORS_PER_QUESTION = 20  # twice the largest k, so the passages that compete for the top 10 are all there
TOLERANCE = 1e-9
REBUILD = "python evals/check_retrieval.py --rebuild"


class Baseline(BaseModel):
    """The fixture's scores: mean recall at each k, MRR, and each question's own scores."""

    chunks: int
    recall: dict[int, float]
    mrr: float
    questions: dict[str, RetrievalScores]


def build_fixture(chunks: list[Chunk], questions: list[Question]) -> list[Chunk]:
    """Pick every chunk on a gold page, and each question's top routed BM25 results over the full index."""
    gold = {page for question in questions for group in question.evidence for page in group}
    keep = {chunk.id for chunk in chunks if page_key(chunk) in gold}
    retriever = BM25Retriever(chunks)
    for question in questions:
        keep |= {hit.chunk.id for hit in routed_search(retriever, question.question, k=DISTRACTORS_PER_QUESTION)}
    return [chunk for chunk in chunks if chunk.id in keep]


def write_fixture(chunks: list[Chunk]) -> None:
    """Write the chunks without `body`, which is `text` without its context line; that halves the file."""
    FIXTURE_DIR.mkdir(exist_ok=True)
    lines = [chunk.model_dump_json(exclude={"body"}) for chunk in chunks]
    CHUNKS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def load_fixture() -> list[Chunk]:
    """Read the fixture's chunks and restore each `body` from its `text`."""
    records = [json.loads(line) for line in CHUNKS_FILE.read_text(encoding="utf-8").splitlines()]
    return [Chunk.model_validate({**record, "body": record["text"].partition("\n")[2]}) for record in records]


def score_fixture(chunks: list[Chunk], questions: list[Question]) -> Baseline:
    """Search the fixture for every question with BM25, routing and the Danish glossary, and score the results."""
    retriever = BM25Retriever(chunks)
    scores = {question.id: score_retrieval(retriever, question) for question in questions}
    return Baseline(
        chunks=len(chunks),
        recall={k: statistics.mean(score.recall[k] for score in scores.values()) for k in K_VALUES},
        mrr=statistics.mean(score.reciprocal_rank for score in scores.values()),
        questions=scores,
    )


def _out_of_step(chunks: list[Chunk], questions: list[Question], baseline: Baseline) -> str | None:
    """Say why the fixture or baseline no longer matches the eval set, or None if they match."""
    fixture_pages = {page_key(chunk) for chunk in chunks}
    missing = sorted({page for q in questions for group in q.evidence for page in group} - fixture_pages)
    if missing:
        return f"The fixture lacks the gold pages {', '.join(missing)}. Rebuild it: {REBUILD}"
    if {question.id for question in questions} != set(baseline.questions):
        return f"The answerable questions differ from the baseline's. Rebuild the fixture: {REBUILD}"
    if len(chunks) != baseline.chunks:
        return "The fixture has changed since the baseline was written: python evals/check_retrieval.py --update"
    return None


def _changed_questions(baseline: Baseline, now: Baseline) -> list[str]:
    lines = []
    for question_id, score in now.questions.items():
        before = baseline.questions[question_id]
        changes = [
            f"recall@{k} {before.recall[k]:.2f} -> {score.recall[k]:.2f}"
            for k in K_VALUES
            if abs(score.recall[k] - before.recall[k]) > TOLERANCE
        ]
        if abs(score.reciprocal_rank - before.reciprocal_rank) > TOLERANCE:
            changes.append(f"reciprocal rank {before.reciprocal_rank:.3f} -> {score.reciprocal_rank:.3f}")
        if changes:
            lines.append(f"  {question_id}: {', '.join(changes)}")
    return lines


def _drops(baseline: Baseline, now: Baseline) -> list[str]:
    drops = [f"recall@{k}" for k in K_VALUES if now.recall[k] < baseline.recall[k] - TOLERANCE]
    if now.mrr < baseline.mrr - TOLERANCE:
        drops.append("MRR")
    return drops


def _table(baseline: Baseline, now: Baseline) -> list[str]:
    rows = [f"{'':10} {'baseline':>8} {'now':>6}"]
    rows += [f"{f'recall@{k}':10} {baseline.recall[k]:8.3f} {now.recall[k]:6.3f}" for k in K_VALUES]
    rows.append(f"{'MRR':10} {baseline.mrr:8.3f} {now.mrr:6.3f}")
    return rows


def _key_figure_mismatches(questions: list[Question]) -> list[str]:
    """Name every question that would get other KPI table rows than its `key_figures` list."""
    lines = []
    for question in questions:
        sent = [figure_key(figure) for figure in key_figures_for(question.question)]
        if sorted(sent) != sorted(question.key_figures):
            lines.append(f"  {question.id}: gets {sent or 'none'}, should get {question.key_figures or 'none'}")
    return lines


def main() -> int:
    """Rebuild or update if asked, then compare the fixture's scores with the baseline and check the key figures."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--update", action="store_true", help="write the current scores as the baseline")
    action.add_argument("--rebuild", action="store_true", help="rebuild the fixture and the baseline from data/")
    args = parser.parse_args()

    all_questions = load_questions(EVAL_DIR / "questions.yaml")
    questions = [question for question in all_questions if question.answerable]
    if args.rebuild:
        write_fixture(build_fixture(load_chunks("structure"), questions))
    chunks = load_fixture()
    now = score_fixture(chunks, questions)
    if args.update or args.rebuild:
        BASELINE_FILE.write_text(now.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
        recalls = "  ".join(f"R@{k} {now.recall[k]:.3f}" for k in K_VALUES)
        print(f"Wrote the baseline: {len(chunks)} chunks, {len(questions)} questions, {recalls}  MRR {now.mrr:.3f}")
        return 0

    baseline = Baseline.model_validate_json(BASELINE_FILE.read_text(encoding="utf-8"))
    problem = _out_of_step(chunks, questions, baseline)
    if problem:
        print(problem)
        return 1
    print(f"BM25 with routing and the Danish glossary, {len(chunks)} chunks, {len(questions)} questions")
    print("\n".join(_table(baseline, now)))
    changed = _changed_questions(baseline, now)
    if changed:
        print("Questions whose scores changed:\n" + "\n".join(changed))
    drops = _drops(baseline, now)
    if drops:
        print(f"FAILED: {', '.join(drops)} fell below the baseline. If the drop is intended, run with --update.")
    else:
        print("OK: no metric fell below the baseline.")

    mismatches = _key_figure_mismatches(all_questions)
    right = len(all_questions) - len(mismatches)
    print(f"\nKey figure rows: {right} of {len(all_questions)} questions get exactly the rows they list")
    if mismatches:
        print("FAILED:\n" + "\n".join(mismatches))
    return 1 if drops or mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
