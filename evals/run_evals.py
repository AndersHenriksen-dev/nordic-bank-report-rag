"""Run the eval set and write evals/results/*.json and evals/RESULTS.md.

python evals/run_evals.py              # retrieval metrics only, no API key needed
python evals/run_evals.py --answers    # also answer every question with Claude (costs money)
"""

from __future__ import annotations

import argparse
import statistics
import sys
from datetime import date
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, TypeAdapter

from bankrag.answer import answer, log_trace
from bankrag.evaluate import citation_ok, load_questions, numbers_match, page_key, percentile, retrieval_scores
from bankrag.ingest import load_chunks
from bankrag.models import Question
from bankrag.retrieve import BM25Retriever, Retriever, routed_search

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
K_VALUES = (1, 3, 6, 10)
SEARCH_DEPTH = 30  # how far down the ranking MRR looks


class RetrievalConfig(NamedTuple):
    """One retrieval setup to compare."""

    name: str
    retriever: Retriever
    route: bool
    expand: bool


class RetrievalResult(BaseModel):
    """Recall at each k and MRR for one retrieval setup."""

    config: str
    questions: int
    recall: dict[int, float]
    mrr: float


class AnswerRecord(BaseModel):
    """How one answer scored."""

    id: str
    category: str
    answerable: bool
    refused: bool
    numbers_ok: bool | None
    has_citation: bool
    citations_ok: bool | None
    cost_usd: float
    latency_s: float
    cache_read_tokens: int
    answer: str
    sources: list[str]


class AnswerSummary(BaseModel):
    """Answer metrics over the whole eval set."""

    numeric_exact: float | None
    numeric_n: int
    answered_with_citation: float
    citations_correct: float | None
    false_refusals: int
    unanswerable_refused: int
    unanswerable_n: int
    cost_usd_mean: float
    cost_usd_p95: float
    latency_s_mean: float
    latency_s_p95: float


class AnswerReport(BaseModel):
    """The answers file: the summary and every record."""

    summary: AnswerSummary
    records: list[AnswerRecord]


_RETRIEVAL_ADAPTER: TypeAdapter[list[RetrievalResult]] = TypeAdapter(list[RetrievalResult])


def _evaluate_config(config: RetrievalConfig, questions: list[Question]) -> RetrievalResult:
    recalls: dict[int, list[float]] = {k: [] for k in K_VALUES}
    reciprocal_ranks = []
    for question in questions:
        for k in K_VALUES:
            # Search at each k, because routing splits k between banks: the top k of a deeper search is not what the
            # answer model would get.
            hits = routed_search(config.retriever, question.question, k=k, route=config.route, expand=config.expand)
            recalls[k].append(retrieval_scores(question, [page_key(hit.chunk) for hit in hits], k)[0])
        hits = routed_search(
            config.retriever,
            question.question,
            k=SEARCH_DEPTH,
            route=config.route,
            expand=config.expand,
        )
        ranked_pages = list(dict.fromkeys(page_key(hit.chunk) for hit in hits))
        reciprocal_ranks.append(retrieval_scores(question, ranked_pages, SEARCH_DEPTH)[1])
    return RetrievalResult(
        config=config.name,
        questions=len(questions),
        recall={k: statistics.mean(values) for k, values in recalls.items()},
        mrr=statistics.mean(reciprocal_ranks),
    )


def retrieval_eval(questions: list[Question], configs: list[RetrievalConfig]) -> list[RetrievalResult]:
    """Score every retrieval setup on the answerable questions."""
    answerable = [question for question in questions if question.answerable]
    return [_evaluate_config(config, answerable) for config in configs]


def _answer_one(question: Question, retriever: Retriever, k: int) -> AnswerRecord:
    hits = routed_search(retriever, question.question, k=k)
    result = answer(question.question, hits)
    log_trace(result, eval_id=question.id)
    citations = [citation_ok(question, source) for source in result.sources]
    return AnswerRecord(
        id=question.id,
        category=question.category,
        answerable=question.answerable,
        refused=result.refused,
        numbers_ok=numbers_match(question, result.text) if question.answerable else None,
        has_citation=bool(result.sources),
        citations_ok=all(citations) if citations else None,
        cost_usd=result.cost_usd,
        latency_s=result.latency_s,
        cache_read_tokens=result.cache_read_tokens,
        answer=result.text,
        sources=[source.label for source in result.sources],
    )


def _share(flags: list[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def _summarize(records: list[AnswerRecord]) -> AnswerSummary:
    answerable = [record for record in records if record.answerable]
    unanswerable = [record for record in records if not record.answerable]
    numeric = [record.numbers_ok for record in answerable if record.numbers_ok is not None]
    cited = [record.citations_ok for record in answerable if record.citations_ok is not None]
    costs = [record.cost_usd for record in records]
    latencies = [record.latency_s for record in records]
    return AnswerSummary(
        numeric_exact=_share(numeric),
        numeric_n=len(numeric),
        answered_with_citation=_share([r.has_citation and not r.refused for r in answerable]) or 0.0,
        citations_correct=_share(cited),
        false_refusals=sum(record.refused for record in answerable),
        unanswerable_refused=sum(record.refused for record in unanswerable),
        unanswerable_n=len(unanswerable),
        cost_usd_mean=statistics.mean(costs),
        cost_usd_p95=percentile(costs, 95),
        latency_s_mean=statistics.mean(latencies),
        latency_s_p95=percentile(latencies, 95),
    )


def answer_eval(questions: list[Question], retriever: Retriever, k: int) -> tuple[list[AnswerRecord], AnswerSummary]:
    """Answer every question with Claude and score the answers. Calls the paid API once per question."""
    records = []
    for question in questions:
        record = _answer_one(question, retriever, k)
        status = "REFUSED" if record.refused else ("ok" if record.numbers_ok in (True, None) else "WRONG NUMBER")
        print(f"  {record.id} {status:12s} {record.latency_s:4.1f}s  {record.answer[:90]!r}")
        records.append(record)
    return records, _summarize(records)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def write_results_md(retrieval: list[RetrievalResult], answers: AnswerSummary | None, n_questions: int) -> None:
    """Write evals/RESULTS.md from the latest results."""
    lines = [
        "# Eval results",
        "",
        f"Generated by `evals/run_evals.py` on {date.today().isoformat()} over {n_questions} questions.",
        "Do not edit by hand.",
        "",
        "## Retrieval",
        "",
        "Recall@k: share of a question's evidence groups (one per bank or year it needs) with a gold page",
        "among the top k chunks, averaged over answerable questions. MRR: mean reciprocal rank of the first",
        "gold page in the top 30. Routed: search only the banks and years the question names.",
        "Danish glossary: add English report wording for Danish finance terms.",
        "",
        "| Config | " + " | ".join(f"Recall@{k}" for k in K_VALUES) + " | MRR |",
        "|---|" + "---|" * (len(K_VALUES) + 1),
    ]
    for result in retrieval:
        cells = " | ".join(f"{result.recall[k]:.2f}" for k in K_VALUES)
        lines.append(f"| {result.config} | {cells} | {result.mrr:.2f} |")
    if answers:
        lines += [
            "",
            "## Answers",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Numeric answers exact | {_percent(answers.numeric_exact)} of {answers.numeric_n} |",
            f"| Answerable questions answered with a citation | {_percent(answers.answered_with_citation)} |",
            f"| Answers whose citations all check out | {_percent(answers.citations_correct)} |",
            f"| Answerable questions wrongly refused | {answers.false_refusals} |",
            f"| Unanswerable questions refused | {answers.unanswerable_refused} of {answers.unanswerable_n} |",
            f"| Cost per question, mean / p95 (USD) | {answers.cost_usd_mean:.5f} / {answers.cost_usd_p95:.5f} |",
            f"| Latency per question, mean / p95 (s) | {answers.latency_s_mean:.1f} / {answers.latency_s_p95:.1f} |",
        ]
    (EVAL_DIR / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    """Run the retrieval evals, and the answer evals if asked, then write the results."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a code page without "æøå"
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", action="store_true", help="also run the answer evals (needs an API key)")
    parser.add_argument("--k", type=int, default=6, help="chunks passed to the answer model")
    args = parser.parse_args()

    questions = load_questions(EVAL_DIR / "questions.yaml")
    structure = BM25Retriever(load_chunks("structure"))
    fixed = BM25Retriever(load_chunks("fixed"))
    configs = [
        RetrievalConfig("BM25, fixed chunks", fixed, route=False, expand=False),
        RetrievalConfig("BM25, structure chunks", structure, route=False, expand=False),
        RetrievalConfig("BM25, structure chunks, routed", structure, route=True, expand=False),
        RetrievalConfig("BM25, structure chunks, routed, Danish glossary", structure, route=True, expand=True),
    ]
    retrieval = retrieval_eval(questions, configs)
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "retrieval.json").write_bytes(_RETRIEVAL_ADAPTER.dump_json(retrieval, indent=2) + b"\n")
    for result in retrieval:
        recalls = "  ".join(f"R@{k} {result.recall[k]:.2f}" for k in K_VALUES)
        print(f"{result.config:50s} {recalls}  MRR {result.mrr:.2f}")

    summary = None
    if args.answers:
        print("\nanswering...")
        records, summary = answer_eval(questions, structure, args.k)
        report = AnswerReport(summary=summary, records=records)
        (RESULTS_DIR / "answers.json").write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(summary.model_dump_json(indent=2))

    write_results_md(retrieval, summary, len(questions))
    return 0


if __name__ == "__main__":
    sys.exit(main())
